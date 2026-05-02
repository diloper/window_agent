# 需安裝 google-search-results
import argparse
from collections import Counter
import json
import os
import re
from pathlib import Path

import requests
from serpapi import GoogleSearch
from upload_to_postimg import upload_to_postimg

API_KEY = os.getenv("SERPAPI_API_KEY", "")


def validate_image_url(url: str) -> None:
    response = requests.get(url, timeout=15)
    response.raise_for_status()


def upload_local_image_to_postimg(image_path: Path) -> dict:
    """上傳圖片到 Postimages，使用 Playwright 自動化流程。回傳包含所有連結的字典。"""
    return upload_to_postimg(str(image_path), headless=True)


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


def main():
    parser = argparse.ArgumentParser(description="用 Google Lens 進行反向圖片搜尋，並分析搜尋結果")
    parser.add_argument(
        "image_path",
        help="本地圖片路徑",
    )
    args = parser.parse_args()

    if not API_KEY:
        raise RuntimeError("Missing SERPAPI_API_KEY environment variable.")

    local_image_path = Path(args.image_path)

    params = {
        "engine": "google_lens",
        "url": "",
        "api_key": API_KEY,
        "hl": "en",
        "q": "what is this",
        "type": "all",
        "safe": "active",
    }

    upload_result = upload_local_image_to_postimg(local_image_path)
    image_url = upload_result["direct_url"]
    removal_url = upload_result["removal_url"]
    validate_image_url(image_url)
    params["url"] = image_url

    print(f"Uploaded image_url: {image_url}")
    search = GoogleSearch(params)
    results = search.get_dict()
    visual_matches = results.get("visual_matches", [])

    top_repetition_result = analyze_top_repetition_from_titles(visual_matches)
    print("\nTop repetition result from visual_matches titles:")
    print(json.dumps(top_repetition_result, ensure_ascii=False, indent=2))

    # 得到分析結果後刪除上傳的圖片
    print(f"\n正在刪除上傳的圖片...")
    try:
        response = requests.get(removal_url, timeout=15)
        if response.status_code == 200:
            print(f"圖片已刪除")
        else:
            print(f"刪除失敗，狀態碼: {response.status_code}")
    except Exception as e:
        print(f"刪除時發生錯誤: {e}")


if __name__ == "__main__":
    main()

