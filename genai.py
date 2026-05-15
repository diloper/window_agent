import os
import base64
import time
from pathlib import Path
from google import genai
from google.genai import errors
from google.genai import types


def build_client(api_key: str) -> genai.Client:
    return genai.Client(api_key=api_key)


def is_retryable_internal_error(exc: Exception) -> bool:
    if not isinstance(exc, errors.ServerError):
        return False
    status_code = getattr(exc, "code", None)
    if status_code != 500:
        return False
    return "INTERNAL" in str(exc).upper()


def stream_with_retry(
    api_key: str,
    model: str,
    contents,
    generate_content_config: types.GenerateContentConfig,
    max_attempts: int = 5,
    retry_delay_seconds: int = 5,
) -> None:
    last_error: Exception | None = None

    for attempt in range(1, max_attempts + 1):
        client = build_client(api_key)
        try:
            for chunk in client.models.generate_content_stream(
                model=model,
                contents=contents,
                config=generate_content_config,
            ):
                if text := chunk.text:
                    print(text, end="")
            return
        except Exception as exc:
            last_error = exc
            if attempt < max_attempts and is_retryable_internal_error(exc):
                retry_delay = retry_delay_seconds * (2 ** (attempt - 1))
                print(
                    f"\n[WARN] Gemini ServerError 500 INTERNAL encountered on attempt {attempt}/{max_attempts}. "
                    f"Waiting {retry_delay} seconds before retrying with a new session..."
                )
                time.sleep(retry_delay)
                continue
            break

    assert last_error is not None
    raise RuntimeError(
        f"Gemini request failed after {max_attempts} attempt(s): {last_error}"
    ) from last_error

def generate():
    api_key = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("Missing API key. Set GOOGLE_API_KEY or GEMINI_API_KEY.")

    # 1. 讀取本地圖片檔案 (例如 E.jpg)
    image_path = "tools/red box.jpg"
    with open(image_path, "rb") as f:
        image_data = f.read()

    image_suffix = Path(image_path).suffix.lower()
    if image_suffix == ".png":
        mime_type = "image/png"
    elif image_suffix in {".jpg", ".jpeg"}:
        mime_type = "image/jpeg"
    else:
        raise RuntimeError(f"Unsupported image format for MIME type detection: {image_path}")

    model = "gemma-4-26b-a4b-it" # 請確保您的模型支援多模態輸入

    contents = [
        types.Content(
            role="user",
            parts=[
                # 2. 將圖片數據加入 parts
                types.Part.from_bytes(
                    data=image_data,
                    mime_type=mime_type
                ),
                # 3. 加入您的文字問題
                types.Part.from_text(text="Please look at the red box in this image and try to identify the name of the icon inside it. Give a brief answer. If you can't identify it, reply with ‘NULL’."),
                #types.Part.from_text(text="Please look at the red box below this image and try to identify the name of the icon inside it. Give a brief answer. If you can't identify it, reply with ‘NULL’."),
            ],
        ),
    ]

    tools = [
        types.Tool(googleSearch=types.GoogleSearch()),
    ]

    generate_content_config = types.GenerateContentConfig(
        thinking_config=types.ThinkingConfig(
            thinking_level="MINIMAL",
        ),
        tools=tools,
    )

    try:
        stream_with_retry(
            api_key=api_key,
            model=model,
            contents=contents,
            generate_content_config=generate_content_config,
        )
    except RuntimeError as exc:
        print(f"\n[ERROR] {exc}")
        raise SystemExit(1)

if __name__ == "__main__":
    generate()
