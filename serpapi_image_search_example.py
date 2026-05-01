import argparse
import json
import os
import sys
from typing import Any, Dict, List
from urllib.parse import urlencode
from urllib.request import Request, urlopen


SERPAPI_ENDPOINT = "https://serpapi.com/search.json"


def search_images(api_key: str, query: str, num: int = 10) -> Dict[str, Any]:
    params = {
        "engine": "google_images",
        "q": query,
        "api_key": api_key,
        "num": num,
    }
    url = f"{SERPAPI_ENDPOINT}?{urlencode(params)}"
    req = Request(url, headers={"User-Agent": "Mozilla/5.0"})

    with urlopen(req, timeout=30) as resp:
        raw = resp.read().decode("utf-8")

    data = json.loads(raw)
    if "error" in data:
        raise RuntimeError(f"SerpApi error: {data['error']}")
    return data


def format_results(images_results: List[Dict[str, Any]]) -> None:
    if not images_results:
        print("No image results found.")
        return

    for i, item in enumerate(images_results, start=1):
        title = item.get("title", "(no title)")
        image_url = item.get("original") or item.get("thumbnail") or "(no image url)"
        source = item.get("source", "(no source)")
        link = item.get("link", "(no link)")

        print(f"[{i}] {title}")
        print(f"    Image:  {image_url}")
        print(f"    Source: {source}")
        print(f"    Page:   {link}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="SerpApi image search example")
    parser.add_argument("query", help="Search query, e.g. 'red panda'")
    parser.add_argument(
        "--num",
        type=int,
        default=10,
        help="Number of image results to request (default: 10)",
    )
    parser.add_argument(
        "--api-key",
        default=os.getenv("SERPAPI_API_KEY", ""),
        help="SerpApi API key (default: read from SERPAPI_API_KEY)",
    )
    parser.add_argument(
        "--save-json",
        default="",
        help="Optional path to save the full JSON response",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    if not args.api_key:
        print("Missing API key. Use --api-key or set SERPAPI_API_KEY.", file=sys.stderr)
        return 1

    try:
        data = search_images(api_key=args.api_key, query=args.query, num=args.num)
    except Exception as exc:
        print(f"Search failed: {exc}", file=sys.stderr)
        return 1

    images_results = data.get("images_results", [])
    format_results(images_results)

    if args.save_json:
        with open(args.save_json, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f"\nSaved full response to: {args.save_json}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
