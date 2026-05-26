import os
import time
from pathlib import Path
from google import genai
from google.genai import errors
from google.genai import types


DEFAULT_MODEL = "gemma-4-31b-it"
ANALYSIS_PROMPT = """分析以下類別名稱列表，找出哪些意思相同或相似，並整理成表格建議統一方式。

要求：
1. 使用 English 名稱（不使用中文或雙語格式）
2. 採用 sentence case（例如："Dropdown menu" 而非 "Dropdown Menu"）
3. 當有多個變體時，選擇最常出現的名稱
4. 對於純中文的系統名稱（無英文對應），保持中文原樣

請以 Markdown 表格格式輸出，包含以下欄位：
- **原始類別名稱**：列出所有變體（用逗號分隔）
- **語意分析**：說明這些名稱的含義
- **建議統一名稱**：標準化後的名稱
- **變體數量**：有多少個不同的變體

類別名稱列表：
{}"""


def build_client(api_key: str) -> genai.Client:
    return genai.Client(api_key=api_key)


def get_api_key(api_key: str | None = None) -> str:
    resolved = api_key or os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")
    if not resolved:
        raise RuntimeError("Missing API key. Set GOOGLE_API_KEY or GEMINI_API_KEY.")
    return resolved


def is_retryable_internal_error(exc: Exception) -> bool:
    if not isinstance(exc, errors.ServerError):
        return False
    status_code = getattr(exc, "code", None)
    if status_code != 500:
        return False
    return "INTERNAL" in str(exc).upper()


def is_high_demand_error(exc: Exception) -> bool:
    """Check if the error is 503 high demand error."""
    if not isinstance(exc, errors.ServerError):
        return False
    status_code = getattr(exc, "code", None)
    if status_code != 503:
        return False
    error_msg = str(exc).upper()
    return "HIGH DEMAND" in error_msg or "OVERLOADED" in error_msg


def generate_text_with_retry(
    api_key: str,
    model: str,
    contents,
    generate_content_config: types.GenerateContentConfig,
    max_attempts: int = 5,
    retry_delay_seconds: int = 5,
    fallback_model: str = "gemma-4-26b-a4b-it",
) -> str:
    last_error: Exception | None = None
    current_model = model
    model_switched = False

    for attempt in range(1, max_attempts + 1):
        client = build_client(api_key)
        try:
            print(f"[DEBUG] Attempt {attempt}/{max_attempts}: Sending request to Gemini API...", flush=True)
            print(f"[DEBUG] Using model: {current_model}", flush=True)
            chunks: list[str] = []
            chunk_count = 0
            for chunk in client.models.generate_content_stream(
                model=current_model,
                contents=contents,
                config=generate_content_config,
            ):
                if text := chunk.text:
                    chunks.append(text)
                    chunk_count += 1
                    if chunk_count % 5 == 0:
                        print(f"[DEBUG] Received {chunk_count} chunks...", flush=True)
            
            result = "".join(chunks).strip()
            print(f"[DEBUG] Total chunks received: {chunk_count}", flush=True)
            print(f"[DEBUG] Result length: {len(result)} characters", flush=True)
            
            if not result:
                raise RuntimeError("API returned empty result")
            
            return result
        except Exception as exc:
            print(f"[ERROR] Attempt {attempt} failed: {exc}", flush=True)
            last_error = exc
            
            # Check for 503 high demand error and switch to fallback model
            if not model_switched and is_high_demand_error(exc):
                print(
                    f"\n[WARN] Model {current_model} is experiencing high demand (503). "
                    f"Switching to fallback model: {fallback_model}", flush=True
                )
                current_model = fallback_model
                model_switched = True
                time.sleep(2)  # Brief pause before retry with new model
                continue
            
            # Handle 500 INTERNAL errors with exponential backoff
            if attempt < max_attempts and is_retryable_internal_error(exc):
                retry_delay = retry_delay_seconds * (2 ** (attempt - 1))
                print(
                    f"\n[WARN] Gemini ServerError 500 INTERNAL encountered on attempt {attempt}/{max_attempts}. "
                    f"Waiting {retry_delay} seconds before retrying with a new session...", flush=True
                )
                time.sleep(retry_delay)
                continue
            break

    assert last_error is not None
    raise RuntimeError(
        f"Gemini request failed after {max_attempts} attempt(s): {last_error}"
    ) from last_error


def build_text_contents(prompt: str):
    return [
        types.Content(
            role="user",
            parts=[
                types.Part.from_text(text=prompt),
            ],
        ),
    ]


def build_generate_content_config() -> types.GenerateContentConfig:
    return types.GenerateContentConfig(
        temperature=0.3,
    )


def extract_table_from_result(result: str) -> str:
    """Extract the markdown table from the analysis result."""
    lines = result.split('\n')
    table_lines = []
    in_table = False
    
    for line in lines:
        stripped = line.strip()
        # Detect table start (header or separator line)
        if '|' in stripped and (':---' in stripped or stripped.startswith('|')):
            in_table = True
        
        if in_table:
            if '|' in stripped:
                table_lines.append(line)
            elif stripped and not stripped.startswith('#') and table_lines:
                # End of table (non-empty line without | after table started)
                break
    
    return '\n'.join(table_lines) if table_lines else ""


def analyze_class_names(
    classes_file: str | Path,
    model: str = DEFAULT_MODEL,
    api_key: str | None = None,
) -> str:
    classes_file = Path(classes_file)
    if not classes_file.exists():
        raise FileNotFoundError(f"Classes file not found: {classes_file}")

    # Read all class names
    class_names = classes_file.read_text(encoding="utf-8").strip().split("\n")
    class_names_text = "\n".join(f"- {name}" for name in class_names if name.strip())
    
    # Build the prompt with class names
    prompt = ANALYSIS_PROMPT.format(class_names_text)
    
    print(f"[INFO] Analyzing {len(class_names)} class names from {classes_file.name}...", flush=True)
    print(f"[INFO] Using model: {model}", flush=True)
    print("-" * 80, flush=True)
    
    return generate_text_with_retry(
        api_key=get_api_key(api_key),
        model=model,
        contents=build_text_contents(prompt),
        generate_content_config=build_generate_content_config(),
    )


def main():
    classes_file = Path("recordings/auto_labels_preview_screen_20260515_161232/classes_preview.txt")
    output_file = Path("class_name_unification_analysis.md")
    reference_file = Path("class_mapping_reference.md")

    try:
        print(f"[INFO] Starting analysis...", flush=True)
        result = analyze_class_names(classes_file)
        
        print(f"\n[DEBUG] Result type: {type(result)}", flush=True)
        print(f"[DEBUG] Result length: {len(result)} characters", flush=True)
        
        if not result:
            raise RuntimeError("Analysis returned empty result")
        
        print(f"\n[RESULT] Analysis output:", flush=True)
        print("-" * 80, flush=True)
        print(result, flush=True)
        print("-" * 80, flush=True)
        
        # Save to file
        output_content = f"""# Class Name Unification Analysis

Generated from: `{classes_file}`
Date: {time.strftime("%Y-%m-%d %H:%M:%S")}
Model: {DEFAULT_MODEL}

## Standardization Rules
- **Language**: English names only (no Chinese or bilingual format)
- **Capitalization**: Sentence case for all English terms
- **Conflict Resolution**: Pick the most frequent name variant
- **Chinese-Only Systems**: Keep Chinese names as-is when no English equivalent exists

## Analysis Result

{result}
"""
        
        print(f"[DEBUG] Writing {len(output_content)} characters to {output_file}", flush=True)
        output_file.write_text(output_content, encoding="utf-8")
        print(f"[SUCCESS] Analysis saved to: {output_file}", flush=True)
        
        # Verify file was written
        if output_file.exists():
            saved_size = output_file.stat().st_size
            print(f"[VERIFY] File size: {saved_size} bytes", flush=True)
        
        # Extract and save reference table
        print(f"\n[INFO] Extracting mapping table...", flush=True)
        table_content = extract_table_from_result(result)
        
        if table_content:
            reference_content = f"""# Class Name Mapping Reference

**Last Updated**: {time.strftime("%Y-%m-%d %H:%M:%S")}  
**Source**: `{classes_file}`  
**Model**: {DEFAULT_MODEL}

## Standardization Rules
- **Language**: English names only
- **Capitalization**: Sentence case
- **Conflict Resolution**: Pick the most frequent variant

## Unified Class Name Mapping

{table_content}

---
*This file is auto-generated. Use this as reference for standardizing class names.*
"""
            
            reference_file.write_text(reference_content, encoding="utf-8")
            print(f"[SUCCESS] Reference table saved to: {reference_file}", flush=True)
            
            if reference_file.exists():
                ref_size = reference_file.stat().st_size
                print(f"[VERIFY] Reference file size: {ref_size} bytes", flush=True)
        else:
            print(f"[WARN] No table found in analysis result", flush=True)
        
    except RuntimeError as exc:
        print(f"\n[ERROR] {exc}", flush=True)
        raise SystemExit(1)
    except FileNotFoundError as exc:
        print(f"\n[ERROR] {exc}", flush=True)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
