import os
import time
from pathlib import Path
from google import genai
from google.genai import errors
from google.genai import types


DEFAULT_MODEL = "gemma-4-31b-it"
ANALYSIS_PROMPT_WITH_EXISTING = """分析以下類別名稱列表，找出哪些意思相同或相似，並整理成表格建議統一方式。

要求：
1. 使用 English 名稱（不使用中文或雙語格式）
2. 採用 sentence case（例如："Dropdown menu" 而非 "Dropdown Menu"）
3. 當有多個變體時，選擇最常出現的名稱
4. 對於純中文的系統名稱（無英文對應），保持中文原樣

**重要約束（必須遵守）**：
以下是已存在的類別名稱映射，**建議統一名稱不可更改**：
{}

對於新的類別名稱：
- 如果與現有映射的原始類別名稱相似或相同，**必須使用相同的建議統一名稱**，並增加到該映射的原始類別名稱中
- 只有完全新的、與現有映射無關的類別名稱才能創建新的建議統一名稱
- 避免同一個詞出現在多個不同的建議統一名稱中

請以 Markdown 表格格式輸出，包含以下欄位：
- **原始類別名稱**：列出所有變體（用逗號分隔）
- **語意分析**：說明這些名稱的含義
- **建議統一名稱**：標準化後的名稱
- **變體數量**：有多少個不同的變體

類別名稱列表：
{}
"""

ANALYSIS_PROMPT_NEW = """分析以下類別名稱列表，找出哪些意思相同或相似，並整理成表格建議統一方式。

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


def parse_existing_mappings(reference_file: Path) -> dict[str, dict]:
    """Parse existing class name mappings from reference file.
    
    Returns dict with structure:
    {
        "Confirm button": {
            "original_names": ["確定 button", "確定", ...],
            "semantic_analysis": "確認操作的按鈕",
            "variant_count": 5
        },
        ...
    }
    """
    if not reference_file.exists():
        return {}
    
    content = reference_file.read_text(encoding="utf-8")
    lines = content.split('\n')
    mappings = {}
    
    in_table = False
    for line in lines:
        stripped = line.strip()
        
        # Skip header and separator rows
        if '|' in stripped and (':---' in stripped or '原始類別名稱' in stripped):
            in_table = True
            continue
        
        if in_table and '|' in stripped and not stripped.startswith('---'):
            parts = [p.strip() for p in stripped.split('|')]
            if len(parts) >= 5:  # | original | semantic | unified | count |
                original_names_str = parts[1]
                semantic_analysis = parts[2]
                unified_name = parts[3]
                try:
                    variant_count = int(parts[4])
                except (ValueError, IndexError):
                    variant_count = 1
                
                if unified_name and unified_name != "建議統一名稱":
                    mappings[unified_name] = {
                        "original_names": [n.strip() for n in original_names_str.split(',')],
                        "semantic_analysis": semantic_analysis,
                        "variant_count": variant_count
                    }
    
    return mappings


def parse_table_to_mappings(table_content: str) -> dict[str, dict]:
    """Parse markdown table content to mappings dictionary.
    
    Returns dict with structure similar to parse_existing_mappings.
    """
    lines = table_content.split('\n')
    mappings = {}
    
    for line in lines:
        stripped = line.strip()
        
        # Skip header and separator rows
        if '|' in stripped and (':---' in stripped or '原始類別名稱' in stripped):
            continue
        
        if '|' in stripped and not stripped.startswith('---'):
            parts = [p.strip() for p in stripped.split('|')]
            if len(parts) >= 5:  # | original | semantic | unified | count |
                original_names_str = parts[1]
                semantic_analysis = parts[2]
                unified_name = parts[3]
                try:
                    variant_count = int(parts[4])
                except (ValueError, IndexError):
                    variant_count = len([n for n in original_names_str.split(',') if n.strip()])
                
                if unified_name and unified_name not in ['建議統一名稱', '']:
                    original_names = [n.strip() for n in original_names_str.split(',') if n.strip()]
                    mappings[unified_name] = {
                        "original_names": original_names,
                        "semantic_analysis": semantic_analysis,
                        "variant_count": variant_count
                    }
    
    return mappings


def merge_mappings(existing: dict[str, dict], new: dict[str, dict]) -> dict[str, dict]:
    """Merge new mappings with existing ones, preserving existing unified names.
    
    Rules:
    1. Existing unified names are never changed
    2. If a new original name matches an existing mapping, add it there
    3. Only create new mappings for truly new original names
    4. Avoid duplicates - each original name appears only once
    """
    merged = dict(existing)  # Start with existing mappings
    
    # Build a reverse index: original_name -> unified_name from existing
    original_to_unified = {}
    for unified_name, data in existing.items():
        for orig in data["original_names"]:
            original_to_unified[orig.lower()] = unified_name
    
    # Process new mappings
    for new_unified, new_data in new.items():
        new_originals = new_data["original_names"]
        
        # Check if any of the new original names already exist in our mappings
        matched_unified = None
        for orig in new_originals:
            if orig.lower() in original_to_unified:
                matched_unified = original_to_unified[orig.lower()]
                break
        
        if matched_unified:
            # Add new original names to existing mapping
            existing_originals = set(merged[matched_unified]["original_names"])
            for orig in new_originals:
                if orig not in existing_originals:
                    existing_originals.add(orig)
                    original_to_unified[orig.lower()] = matched_unified
            
            merged[matched_unified]["original_names"] = sorted(existing_originals)
            merged[matched_unified]["variant_count"] = len(existing_originals)
            print(f"[MERGE] Added variants to existing mapping: {matched_unified}", flush=True)
        else:
            # Check if this is truly new (not just a renamed unified name for existing originals)
            is_truly_new = True
            for orig in new_originals:
                if orig.lower() in original_to_unified:
                    is_truly_new = False
                    break
            
            if is_truly_new:
                # This is a completely new mapping
                merged[new_unified] = new_data
                for orig in new_originals:
                    original_to_unified[orig.lower()] = new_unified
                print(f"[MERGE] Created new mapping: {new_unified} ({len(new_originals)} variants)", flush=True)
    
    return merged


def format_mappings_as_table(mappings: dict[str, dict]) -> str:
    """Format mappings dictionary as a markdown table."""
    lines = [
        "| 原始類別名稱 | 語意分析 | 建議統一名稱 | 變體數量 |",
        "| :--- | :--- | :--- | :---: |"
    ]
    
    # Sort by variant count (descending) then by unified name
    sorted_items = sorted(
        mappings.items(),
        key=lambda x: (-x[1]["variant_count"], x[0])
    )
    
    for unified_name, data in sorted_items:
        original_names_str = ", ".join(data["original_names"])
        semantic = data["semantic_analysis"]
        count = data["variant_count"]
        
        lines.append(f"| {original_names_str} | {semantic} | {unified_name} | {count} |")
    
    return "\n".join(lines)


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
    reference_file: Path,
    model: str = DEFAULT_MODEL,
    api_key: str | None = None,
) -> str:
    classes_file = Path(classes_file)
    if not classes_file.exists():
        raise FileNotFoundError(f"Classes file not found: {classes_file}")

    # Read all class names
    class_names = classes_file.read_text(encoding="utf-8").strip().split("\n")
    class_names_text = "\n".join(f"- {name}" for name in class_names if name.strip())
    
    # Check for existing mappings
    existing_mappings = parse_existing_mappings(reference_file)
    
    if existing_mappings:
        print(f"[INFO] Found {len(existing_mappings)} existing mappings", flush=True)
        # Build constraint text from existing mappings
        mapping_lines = []
        for unified_name, data in existing_mappings.items():
            original_str = ", ".join(data["original_names"][:3])  # Show first 3 for brevity
            if len(data["original_names"]) > 3:
                original_str += f" (共{data['variant_count']}個)"
            mapping_lines.append(f"- {original_str} → **{unified_name}**")
        
        existing_mappings_text = "\n".join(mapping_lines)
        prompt = ANALYSIS_PROMPT_WITH_EXISTING.format(existing_mappings_text, class_names_text)
    else:
        print(f"[INFO] No existing mappings found, performing initial analysis", flush=True)
        prompt = ANALYSIS_PROMPT_NEW.format(class_names_text)
    
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
    output_file = classes_file.parent / "class_name_unification_analysis.md"
    reference_file = Path("class_mapping_reference.md")

    try:
        print(f"[INFO] Starting analysis...", flush=True)
        result = analyze_class_names(classes_file, reference_file)
        
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
            # Parse new mappings from AI result
            new_mappings = parse_table_to_mappings(table_content)
            print(f"[INFO] Parsed {len(new_mappings)} mappings from AI result", flush=True)
            
            # Read existing mappings again for merging
            existing_mappings = parse_existing_mappings(reference_file)
            print(f"[INFO] Loaded {len(existing_mappings)} existing mappings for merge", flush=True)
            
            # Merge with protection of existing unified names
            merged_mappings = merge_mappings(existing_mappings, new_mappings)
            print(f"[INFO] Final merged mappings: {len(merged_mappings)} entries", flush=True)
            
            # Format as table
            final_table = format_mappings_as_table(merged_mappings)
            reference_content = f"""# Class Name Mapping Reference

**Last Updated**: {time.strftime("%Y-%m-%d %H:%M:%S")}  
**Source**: `{classes_file}`  
**Model**: {DEFAULT_MODEL}

## Standardization Rules
- **Language**: English names only
- **Capitalization**: Sentence case
- **Conflict Resolution**: Pick the most frequent variant
- **Protection**: Existing unified names are never changed

## Unified Class Name Mapping

{final_table}

---
*This file is auto-generated and incrementally updated. Existing unified names are preserved.*
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
