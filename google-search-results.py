# 需安裝 google-search-results
import argparse
from collections import Counter
import json
import os
from pathlib import Path
import re

import requests
from serpapi import GoogleSearch
from upload_to_postimg import upload_to_postimg
from easyocr_checker import detect_target_text_types, DEFAULT_OCR_MIN_CONFIDENCE

API_KEY = os.getenv("SERPAPI_API_KEY", "")


def validate_image_url(url: str) -> None:
    response = requests.get(url, timeout=15)
    response.raise_for_status()


def upload_local_image_to_postimg(image_path: Path) -> dict:
    """上傳圖片到 Postimages，使用 Playwright 自動化流程。回傳包含所有連結的字典。"""
    return upload_to_postimg(str(image_path), headless=True)


def delete_uploaded_image(removal_url: str) -> None:
    response = requests.get(removal_url, timeout=15)
    response.raise_for_status()


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


def analyze_local_image_with_google_lens(
    image_path: Path,
    api_key: str,
    *,
    validate_ocr: bool = True,
    ocr_min_confidence: float = DEFAULT_OCR_MIN_CONFIDENCE,
    ocr_engine: str = "paddleocr",
) -> dict:
    """Upload a local image, run Google Lens search, and return analysis details."""
    if validate_ocr:
        ocr_summary = detect_target_text_types(
            image_path,
            min_confidence=ocr_min_confidence,
            engine=ocr_engine,
        )
        if not ocr_summary["has_target_text"]:
            return {
                "ok": False,
                "reason": "ocr_filtered",
                "ocr_summary": ocr_summary,
                "results": {},
                "visual_matches": [],
                "top_repetition_result": {"result": "", "count": 0, "mode": "no_titles"},
            }
    else:
        ocr_summary = None

    params = {
        "engine": "google_lens",
        "url": "",
        "api_key": api_key,
        "hl": "en",
        "q": "what is this",
        "type": "all",
        "safe": "active",
    }

    upload_result = upload_local_image_to_postimg(image_path)
    image_url = upload_result["direct_url"]
    removal_url = upload_result["removal_url"]

    try:
        validate_image_url(image_url)
        params["url"] = image_url
        search = GoogleSearch(params)
        results = search.get_dict()
        visual_matches = results.get("visual_matches", [])
        top_repetition_result = analyze_top_repetition_from_titles(visual_matches)
        return {
            "ok": True,
            "reason": "ok",
            "ocr_summary": ocr_summary,
            "results": results,
            "visual_matches": visual_matches,
            "top_repetition_result": top_repetition_result,
            "image_url": image_url,
        }
    finally:
        try:
            delete_uploaded_image(removal_url)
        except Exception:
            pass


def main():
    parser = argparse.ArgumentParser(description="用 Google Lens 進行反向圖片搜尋，並分析搜尋結果")
    parser.add_argument(
        "image_path",
        help="本地圖片路徑",
    )
    parser.add_argument(
        "--ocr-min-confidence",
        type=float,
        default=DEFAULT_OCR_MIN_CONFIDENCE,
        help="OCR 最低信心分數門檻，範圍 0.0 到 1.0，預設 0.6",
    )
    parser.add_argument(
        "--ocr-engine",
        choices=["easyocr", "paddleocr"],
        default="paddleocr",
        help="OCR 引擎，'paddleocr'（預設）或 'easyocr'",
    )
    args = parser.parse_args()

    local_image_path = Path(args.image_path)

    try:
        ocr_summary = detect_target_text_types(
            local_image_path,
            min_confidence=args.ocr_min_confidence,
            engine=args.ocr_engine,
        )
    except Exception as exc:
        print(f"\nOCR pre-check failed: {exc}")
        return

    print("\nOCR pre-check:")
    print(json.dumps(ocr_summary, ensure_ascii=False, indent=2))

    if not ocr_summary["has_target_text"]:
        print(
            "\n圖片未辨識到符合門檻的中文/英文/數字，停止後續上傳與搜尋流程。"
        )
        return

    if not API_KEY:
        raise RuntimeError("Missing SERPAPI_API_KEY environment variable.")

    analysis = analyze_local_image_with_google_lens(
        local_image_path,
        API_KEY,
        validate_ocr=False,
    )
    print(f"Uploaded image_url: {analysis.get('image_url', '')}")
    print("\nTop repetition result from visual_matches titles:")
    print(json.dumps(analysis["top_repetition_result"], ensure_ascii=False, indent=2))
    print("\n圖片已刪除")


if __name__ == "__main__":
    main()

