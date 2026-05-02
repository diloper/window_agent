import argparse
from pathlib import Path

try:
    from playwright.sync_api import Error as PlaywrightError
    from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
    from playwright.sync_api import sync_playwright
except ImportError:
    PlaywrightError = None
    PlaywrightTimeoutError = None
    sync_playwright = None


def upload_to_postimg(file_path, headless=True, timeout_ms=60000):
    image_path = Path(file_path).expanduser().resolve()
    if not image_path.is_file():
        raise FileNotFoundError(f"找不到檔案: {image_path}")

    if sync_playwright is None:
        raise RuntimeError(
            "缺少 Playwright。請先執行: pip install playwright，然後執行: playwright install chromium"
        )

    with sync_playwright() as playwright:
        try:
            browser = playwright.chromium.launch(channel="chromium", headless=headless)
        except PlaywrightError as exc:
            raise RuntimeError(
                "缺少 Playwright 瀏覽器。請先執行: playwright install chromium"
            ) from exc
        page = browser.new_page()
        try:
            page.goto("https://postimages.org/", wait_until="domcontentloaded")
            page.locator('input[type="file"]').set_input_files(str(image_path))

            try:
                page.wait_for_url("https://postimg.cc/**", timeout=timeout_ms)
            except PlaywrightTimeoutError as exc:
                error_text = page.locator("text=Unsupported or unrecognized file format")
                if error_text.count() and error_text.first.is_visible():
                    raise RuntimeError("上傳失敗: Postimages 不接受此圖檔格式") from exc
                raise RuntimeError(f"上傳逾時，最後頁面: {page.url}") from exc

            field_values = page.locator('input[type="text"]').evaluate_all(
                "elements => elements.map(element => element.value)"
            )
            page_url = next(
                (value for value in field_values if value.startswith("https://postimg.cc/") and "/delete/" not in value),
                None,
            )
            direct_url = next(
                (value for value in field_values if value.startswith("https://i.postimg.cc/")),
                None,
            )
            removal_url = next(
                (value for value in field_values if value.startswith("https://postimg.cc/delete/")),
                None,
            )
            if not page_url or not direct_url or not removal_url:
                raise RuntimeError("上傳成功，但無法從結果頁擷取完整連結")

            return {
                "page_url": page_url,
                "direct_url": direct_url,
                "removal_url": removal_url,
            }
        finally:
            browser.close()


def main():
    parser = argparse.ArgumentParser(description="用 Playwright 自動上傳圖片到 Postimages")
    parser.add_argument("file_path", help="要上傳的圖片路徑")
    parser.add_argument("--show-browser", action="store_true", help="顯示瀏覽器視窗")
    parser.add_argument("--timeout-ms", type=int, default=60000, help="等待上傳完成的逾時毫秒數")
    args = parser.parse_args()

    result = upload_to_postimg(
        args.file_path,
        headless=not args.show_browser,
        timeout_ms=args.timeout_ms,
    )
    print(f"上傳成功！頁面網址: {result['page_url']}")
    print(f"直接圖片網址: {result['direct_url']}")
    print(f"刪除網址: {result['removal_url']}")


if __name__ == "__main__":
    main()
