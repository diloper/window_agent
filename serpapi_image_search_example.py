import argparse
import json
import mimetypes
import os
import sys
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from google.auth.transport.requests import Request as GoogleAuthRequest
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload


SERPAPI_ENDPOINT = "https://serpapi.com/search.json"
GOOGLE_DRIVE_SCOPES = ["https://www.googleapis.com/auth/drive.file"]


def create_drive_service_oauth(
    client_secrets_path: str, token_path: str = ".secrets/drive_token.json"
) -> Any:
    secrets_path = Path(client_secrets_path)
    if not secrets_path.exists() or not secrets_path.is_file():
        raise FileNotFoundError(
            f"Google OAuth client secrets file not found: {client_secrets_path}"
        )

    token_file = Path(token_path)
    creds: Optional[Credentials] = None

    if token_file.exists() and token_file.is_file():
        creds = Credentials.from_authorized_user_file(
            str(token_file), GOOGLE_DRIVE_SCOPES
        )

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(GoogleAuthRequest())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                str(secrets_path), GOOGLE_DRIVE_SCOPES
            )
            creds = flow.run_local_server(port=0)

        if token_file.parent and not token_file.parent.exists():
            token_file.parent.mkdir(parents=True, exist_ok=True)
        token_file.write_text(creds.to_json(), encoding="utf-8")

    return build("drive", "v3", credentials=creds)


def upload_file_to_drive(
    drive_service: Any, image_file_path: str, folder_id: str = ""
) -> str:
    image_path = Path(image_file_path)
    if not image_path.exists() or not image_path.is_file():
        raise FileNotFoundError(f"Image file not found: {image_file_path}")

    file_metadata: Dict[str, Any] = {"name": image_path.name}
    if folder_id.strip():
        file_metadata["parents"] = [folder_id.strip()]

    media = MediaFileUpload(str(image_path), resumable=False)
    created = (
        drive_service.files()
        .create(body=file_metadata, media_body=media, fields="id")
        .execute()
    )
    file_id = str(created.get("id", "")).strip()
    if not file_id:
        raise RuntimeError("Drive upload did not return a file id.")
    return file_id


def make_drive_file_public_and_get_url(drive_service: Any, file_id: str) -> str:
    drive_service.permissions().create(
        fileId=file_id,
        body={"type": "anyone", "role": "reader"},
    ).execute()

    return f"https://drive.google.com/uc?export=download&id={file_id}"


def delete_drive_file(drive_service: Any, file_id: str) -> None:
    drive_service.files().delete(fileId=file_id).execute()


def search_images_by_url(api_key: str, image_url: str, num: int = 10) -> Dict[str, Any]:
    params = {
        "engine": "google_reverse_image",
        "image_url": image_url,
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


def search_images_by_file(
    api_key: str, image_file_path: str, num: int = 10
) -> Dict[str, Any]:
    """
    Perform reverse image search using a local image file.

    Args:
        api_key: SerpApi API key
        image_file_path: Path to local image file (jpg, png, gif, webp, etc.)
        num: Number of results to return

    Returns:
        SerpApi response as dict

    Raises:
        FileNotFoundError: If image file not found
        RuntimeError: If API returns error
    """
    img_path = Path(image_file_path)
    if not img_path.exists():
        raise FileNotFoundError(f"Image file not found: {image_file_path}")

    if not img_path.is_file():
        raise ValueError(f"Not a file: {image_file_path}")

    # Read image file as binary
    with open(img_path, "rb") as f:
        image_data = f.read()

    # Build multipart/form-data body
    boundary = str(uuid.uuid4())
    body_parts: List[bytes] = []

    # Add engine parameter
    body_parts.append(f"--{boundary}".encode("utf-8"))
    body_parts.append(b"Content-Disposition: form-data; name=\"engine\"")
    body_parts.append(b"")
    body_parts.append(b"google_reverse_image")

    # Add num parameter
    body_parts.append(f"--{boundary}".encode("utf-8"))
    body_parts.append(b"Content-Disposition: form-data; name=\"num\"")
    body_parts.append(b"")
    body_parts.append(str(num).encode("utf-8"))

    # Add api_key parameter
    body_parts.append(f"--{boundary}".encode("utf-8"))
    body_parts.append(b"Content-Disposition: form-data; name=\"api_key\"")
    body_parts.append(b"")
    body_parts.append(api_key.encode("utf-8"))

    # Add image file
    body_parts.append(f"--{boundary}".encode("utf-8"))
    mime_type, _ = mimetypes.guess_type(str(img_path))
    if mime_type is None:
        mime_type = "application/octet-stream"

    content_disposition = (
        f'Content-Disposition: form-data; name="image"; filename="{img_path.name}"'
    ).encode("utf-8")
    body_parts.append(content_disposition)
    body_parts.append(f"Content-Type: {mime_type}".encode("utf-8"))
    body_parts.append(b"")
    body_parts.append(image_data)

    # Final boundary
    body_parts.append(f"--{boundary}--".encode("utf-8"))
    body_parts.append(b"")

    body = b"\r\n".join(body_parts)

    # Make POST request
    url = SERPAPI_ENDPOINT
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Content-Type": f"multipart/form-data; boundary={boundary}",
    }
    req = Request(url, data=body, headers=headers, method="POST")

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
    parser = argparse.ArgumentParser(
        description="SerpApi image search: text query or reverse image search from file"
    )
    parser.add_argument(
        "query", nargs="?", default="", help="Search query, e.g. 'red panda'"
    )
    parser.add_argument(
        "--image",
        default="",
        help="Path to local image file for reverse image search (jpg, png, gif, webp, etc.)",
    )
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

    # Determine search mode
    has_query = bool(args.query.strip())
    has_image = bool(args.image.strip())

    if not has_query and not has_image:
        print(
            "Error: Provide either a search QUERY or an --image file path.",
            file=sys.stderr,
        )
        parser = argparse.ArgumentParser()
        parser.print_help()
        return 1

    # Prioritize image search if both provided
    if has_image:
        try:
            data = search_images_by_file(
                api_key=args.api_key, image_file_path=args.image, num=args.num
            )
            print(f"Reverse image search: {args.image}")
        except Exception as exc:
            print(f"Image search failed: {exc}", file=sys.stderr)
            return 1
    else:
        try:
            data = search_images(api_key=args.api_key, query=args.query, num=args.num)
            print(f"Text query: {args.query}")
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
