import os

from google import genai
import PIL.Image

# 設定 API Key
api_key = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")
if not api_key:
	raise RuntimeError("Missing API key. Set GOOGLE_API_KEY or GEMINI_API_KEY in environment variables.")

client = genai.Client(api_key=api_key)


def normalize_model_name(raw_name: str) -> str:
	if raw_name.startswith("models/"):
		return raw_name.split("/", 1)[1]
	return raw_name


def list_available_models() -> list[str]:
	"""Return normalized model names from google.genai list API."""
	names: list[str] = []
	for m in client.models.list():
		name = normalize_model_name(str(getattr(m, "name", "")))
		if name:
			names.append(name)
	return names


def choose_model_name(available_names: list[str]) -> str:
	"""Prefer flash-lite model, then fallback to other flash/pro models."""
	preferred = [
		"gemini-3.1-flash-lite",
		"gemini-2.5-flash-lite",
		"gemini-2.5-flash",
		"gemini-2.0-flash-lite",
		"gemini-2.0-flash",
		"gemini-1.5-flash",
		"gemini-1.5-pro",
	]

	available_set = set(available_names)
	for name in preferred:
		if name in available_set:
			return name

	if not available_names:
		# Fallback to requested model when list API is unavailable.
		return preferred[0]

	return sorted(available_names)[0]


try:
	available_models = list_available_models()
except Exception as exc:
	print(f"list models failed: {exc}")
	available_models = []

selected_model = choose_model_name(available_models)
print(f"Using model: {selected_model}")

# 依可用模型自動選擇，避免固定模型名稱造成 404
# 載入圖片
img = PIL.Image.open('recordings/D.png')

# 發送請求：提示詞與圖片可以同時傳入
try:
	response = client.models.generate_content(
		model=selected_model,
		# contents=["What is the dotted red box in this image?", img],
        contents=["Describe what the dotted red box in this image is. Please keep your answer brief—use a noun, for example.", img],
	)
except Exception as exc:
	print(f"generate_content failed with model {selected_model}: {exc}")
	raise SystemExit(1)

print(response.text)
