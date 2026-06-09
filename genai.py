import os
import time
from pathlib import Path
from google import genai
from google.genai import errors
from google.genai import types


DEFAULT_MODEL = "gemma-4-26b-a4b-it"
DEFAULT_PROMPT = (
    "Please look at the red box in this image and try to identify the name of the icon "
    "inside it. Give a brief answer. If you can't identify it, reply with 'NULL'."
)


def build_client(api_key: str) -> genai.Client:
    return genai.Client(api_key=api_key)


def get_api_key(api_key: str | None = None) -> str:
    resolved = api_key or os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")
    if not resolved:
        raise RuntimeError("Missing API key. Set GOOGLE_API_KEY or GEMINI_API_KEY.")
    return resolved


def detect_mime_type(image_path: Path) -> str:
    image_suffix = image_path.suffix.lower()
    if image_suffix == ".png":
        return "image/png"
    if image_suffix in {".jpg", ".jpeg"}:
        return "image/jpeg"
    raise RuntimeError(f"Unsupported image format for MIME type detection: {image_path}")


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
    text = generate_text_with_retry(
        api_key=api_key,
        model=model,
        contents=contents,
        generate_content_config=generate_content_config,
        max_attempts=max_attempts,
        retry_delay_seconds=retry_delay_seconds,
    )
    if text:
        print(text, end="")


def generate_text_with_retry(
    api_key: str,
    model: str,
    contents,
    generate_content_config: types.GenerateContentConfig,
    max_attempts: int = 5,
    retry_delay_seconds: int = 5,
) -> str:
    last_error: Exception | None = None

    for attempt in range(1, max_attempts + 1):
        client = build_client(api_key)
        try:
            chunks: list[str] = []
            for chunk in client.models.generate_content_stream(
                model=model,
                contents=contents,
                config=generate_content_config,
            ):
                if text := chunk.text:
                    chunks.append(text)
            return "".join(chunks).strip()
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


def build_image_contents(image_path: Path, prompt: str):
    image_data = image_path.read_bytes()
    mime_type = detect_mime_type(image_path)
    return [
        types.Content(
            role="user",
            parts=[
                types.Part.from_bytes(
                    data=image_data,
                    mime_type=mime_type,
                ),
                types.Part.from_text(text=prompt),
            ],
        ),
    ]


def build_generate_content_config() -> types.GenerateContentConfig:
    tools = [
        types.Tool(googleSearch=types.GoogleSearch()),
    ]
    return types.GenerateContentConfig(
        temperature=0,
        thinking_config=types.ThinkingConfig(
            thinking_level="HIGH",
        ),
        tools=tools,
    )


def analyze_image_file(
    image_path: str | Path,
    prompt: str = DEFAULT_PROMPT,
    model: str = DEFAULT_MODEL,
    api_key: str | None = None,
) -> str:
    image_path = Path(image_path)
    if not image_path.exists():
        raise FileNotFoundError(f"Image file not found: {image_path}")

    return generate_text_with_retry(
        api_key=get_api_key(api_key),
        model=model,
        contents=build_image_contents(image_path, prompt),
        generate_content_config=build_generate_content_config(),
    )

def generate():
    image_path = Path("tools/red box.jpg")

    try:
        text = analyze_image_file(image_path)
        if text:
            print(text, end="")
    except RuntimeError as exc:
        print(f"\n[ERROR] {exc}")
        raise SystemExit(1)

if __name__ == "__main__":
    generate()
