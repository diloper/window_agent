# 需安裝 google-search-results
from collections import Counter
import json
import os
import re
from pathlib import Path

import requests
from serpapi import GoogleSearch
from upload_to_postimg import upload_to_postimg

api_key = os.getenv("SERPAPI_API_KEY", "")
if not api_key:
    raise RuntimeError("Missing SERPAPI_API_KEY environment variable.")

local_image_path = Path(os.getenv("LOCAL_IMAGE_PATH", "A/frame_00000.jpg"))


def validate_image_url(url: str) -> None:
    response = requests.get(url, timeout=15)
    response.raise_for_status()


def upload_local_image_to_postimg(image_path: Path) -> str:
    """上傳圖片到 Postimages，使用 Playwright 自動化流程。"""
    result = upload_to_postimg(str(image_path), headless=True)
    return result["direct_url"]


def analyze_top_repetition_from_titles(matches: list[dict]) -> dict:
    titles = [item.get("title", "").strip() for item in matches if item.get("title")]
    if not titles:
        return {"result": "", "count": 0, "mode": "no_titles"}

    exact_counts = Counter(titles)
    top_title, top_count = exact_counts.most_common(1)[0]
    if top_count > 1:
        return {
            "result": top_title,
            "count": top_count,
            "mode": "exact_title",
        }

    stop_words = {
        "the",
        "and",
        "for",
        "with",
        "from",
        "this",
        "that",
        "what",
        "how",
        "your",
        "you",
        "new",
        "best",
        "app",
    }
    token_counter = Counter()
    for title in titles:
        tokens = re.findall(r"[a-z0-9']+", title.lower())
        filtered = [token for token in tokens if len(token) >= 3 and token not in stop_words]
        token_counter.update(filtered)

    if not token_counter:
        return {
            "result": top_title,
            "count": top_count,
            "mode": "fallback_title",
        }

    keyword, keyword_count = token_counter.most_common(1)[0]
    related_titles = [title for title in titles if re.search(rf"\b{re.escape(keyword)}\b", title, re.IGNORECASE)]
    return {
        "result": keyword,
        "count": keyword_count,
        "mode": "keyword",
        "sample_titles": related_titles[:5],
    }

params = {
    "engine": "google_lens",
    "url": "",
    "api_key": api_key,
    "hl": "en",
    "q": "what is this",
    "type": "all",
    "safe": "active",
}

image_url = upload_local_image_to_postimg(local_image_path)
validate_image_url(image_url)
params["url"] = image_url

print(f"Uploaded image_url: {image_url}")
search = GoogleSearch(params)
results = search.get_dict()
visual_matches = results.get("visual_matches", [])


top_repetition_result = analyze_top_repetition_from_titles(visual_matches)
print("\nTop repetition result from visual_matches titles:")
print(json.dumps(top_repetition_result, ensure_ascii=False, indent=2))
