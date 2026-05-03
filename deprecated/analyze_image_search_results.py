import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from serpapi_image_search_example import (
    create_drive_service_oauth,
    delete_drive_file,
    make_drive_file_public_and_get_url,
    search_images,
    search_images_by_file,
    search_images_by_url,
    upload_file_to_drive,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Analyze image search results using SerpApi from image path or query."
    )
    parser.add_argument(
        "--image",
        default="",
        help="Path to local image file. If only filename is given, recordings/<name> is also checked.",
    )
    parser.add_argument(
        "--query",
        default="",
        help="Optional explicit query. If omitted, derived from image filename stem.",
    )
    parser.add_argument(
        "--num",
        type=int,
        default=10,
        help="Number of image search results to request.",
    )
    parser.add_argument(
        "--api-key",
        default=os.getenv("SERPAPI_API_KEY", ""),
        help="SerpApi API key (default: SERPAPI_API_KEY environment variable).",
    )
    parser.add_argument(
        "--save-json",
        default="",
        help="Optional path to save the full JSON response.",
    )
    parser.add_argument(
        "--save-summary",
        default="",
        help="Optional path to save a text summary.",
    )
    parser.add_argument(
        "--use-drive-public-url",
        action="store_true",
        help="Upload image to Google Drive and search by public URL, then delete the Drive file.",
    )
    parser.add_argument(
        "--drive-oauth-client-secrets",
        default="",
        help="Path to Google OAuth client secrets JSON file (required with --use-drive-public-url).",
    )
    parser.add_argument(
        "--drive-oauth-token",
        default=".secrets/drive_token.json",
        help="Path to cached Google OAuth token JSON.",
    )
    parser.add_argument(
        "--drive-folder-id",
        default="",
        help="Optional Google Drive folder ID to upload temporary image into.",
    )
    return parser.parse_args()


def resolve_image_path(raw_path: str) -> Optional[Path]:
    if not raw_path:
        return None

    direct = Path(raw_path)
    candidates = [direct]

    if not direct.is_absolute() and direct.parent == Path("."):
        candidates.append(Path("recordings") / direct.name)

    for p in candidates:
        if p.exists() and p.is_file():
            return p

    return None


def derive_query(image_path: Optional[Path], explicit_query: str) -> str:
    if explicit_query.strip():
        return explicit_query.strip()
    if image_path is None:
        return ""
    stem = image_path.stem.strip()
    if not stem:
        return ""
    return stem.replace("_", " ").replace("-", " ")


def summarize_results(query: str, data: Dict[str, Any], num: int) -> Tuple[str, List[str]]:
    images_results = data.get("images_results", [])
    lines: List[str] = []
    lines.append(f"Query: {query}")
    lines.append(f"Requested: {num}")
    lines.append(f"Returned: {len(images_results)}")

    if not images_results:
        lines.append("No image results found.")
        return "\n".join(lines), lines

    lines.append("")
    lines.append("Top results:")
    for idx, item in enumerate(images_results, start=1):
        title = str(item.get("title", "(no title)"))
        source = str(item.get("source", "(no source)"))
        link = str(item.get("link", "(no link)"))
        image_url = str(item.get("original") or item.get("thumbnail") or "(no image url)")

        lines.append(f"[{idx}] {title}")
        lines.append(f"    Source: {source}")
        lines.append(f"    Page:   {link}")
        lines.append(f"    Image:  {image_url}")

    return "\n".join(lines), lines


def ensure_parent(path: Path) -> None:
    if path.parent and not path.parent.exists():
        path.parent.mkdir(parents=True, exist_ok=True)


def main() -> int:
    args = parse_args()

    if not args.api_key:
        print("Missing API key. Use --api-key or set SERPAPI_API_KEY.", file=sys.stderr)
        return 1

    # Determine search mode: image file upload vs text query
    has_query = bool(args.query.strip())
    has_image = bool(args.image.strip())

    if has_image:
        # Image file upload (reverse image search)
        image_path = resolve_image_path(args.image)
        if image_path is None:
            print(
                f"Image file not found: {args.image}. Also checked recordings/{Path(args.image).name}",
                file=sys.stderr,
            )
            return 1

        if args.use_drive_public_url:
            if not args.drive_oauth_client_secrets.strip():
                print(
                    "Missing --drive-oauth-client-secrets for Drive public URL mode.",
                    file=sys.stderr,
                )
                return 1

            try:
                drive_service = create_drive_service_oauth(
                    client_secrets_path=args.drive_oauth_client_secrets,
                    token_path=args.drive_oauth_token,
                )
            except Exception as exc:
                print(f"Failed to initialize Google Drive OAuth client: {exc}", file=sys.stderr)
                return 1

            drive_file_id: Optional[str] = None
            search_error: Optional[Exception] = None

            try:
                drive_file_id = upload_file_to_drive(
                    drive_service=drive_service,
                    image_file_path=str(image_path),
                    folder_id=args.drive_folder_id,
                )
                public_image_url = make_drive_file_public_and_get_url(
                    drive_service=drive_service,
                    file_id=drive_file_id,
                )
                data = search_images_by_url(
                    api_key=args.api_key,
                    image_url=public_image_url,
                    num=max(1, args.num),
                )
            except Exception as exc:
                search_error = exc
                data = {}
            finally:
                if drive_file_id:
                    try:
                        delete_drive_file(drive_service=drive_service, file_id=drive_file_id)
                        print(f"Deleted Drive file: {drive_file_id}")
                    except Exception as cleanup_exc:
                        print(f"Failed to delete Drive file {drive_file_id}: {cleanup_exc}", file=sys.stderr)
                        return 1

            if search_error is not None:
                print(f"Image search failed: {search_error}", file=sys.stderr)
                return 1
        else:
            try:
                data = search_images_by_file(
                    api_key=args.api_key,
                    image_file_path=str(image_path),
                    num=max(1, args.num),
                )
            except Exception as exc:
                print(f"Image search failed: {exc}", file=sys.stderr)
                return 1

        # Use image filename stem as display label for summary
        search_label = f"Image: {image_path}"
        summary_text, _ = summarize_results(search_label, data, max(1, args.num))
        print(search_label)
        print(summary_text)

    elif has_query:
        # Text query search
        try:
            data = search_images(api_key=args.api_key, query=args.query, num=max(1, args.num))
        except Exception as exc:
            print(f"Search failed: {exc}", file=sys.stderr)
            return 1

        summary_text, _ = summarize_results(f"Query: {args.query}", data, max(1, args.num))
        print(summary_text)

    else:
        print(
            "Missing input. Provide --image for reverse image search or --query for text search.",
            file=sys.stderr,
        )
        return 1

    if args.save_json:
        json_path = Path(args.save_json)
        ensure_parent(json_path)
        json_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Saved JSON: {json_path}")

    if args.save_summary:
        summary_path = Path(args.save_summary)
        ensure_parent(summary_path)
        summary_path.write_text(summary_text + "\n", encoding="utf-8")
        print(f"Saved summary: {summary_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
