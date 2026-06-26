"""download_wordlist.py — 下載並過濾 WPA 密碼字典 (支援中斷續傳)

Usage:
    # 下載預設 rockyou.txt 並過濾 WPA 長度 (8-63 字元)
    python tools/download_wordlist.py

    # 指定輸出目錄
    python tools/download_wordlist.py --out-dir tools/wordlists

    # 下載後不過濾，保留原始檔案
    python tools/download_wordlist.py --no-filter

    # 自訂下載來源
    python tools/download_wordlist.py --url https://example.com/passwords.txt
"""

import argparse
import os
import sys
from pathlib import Path

import requests

# ---------------------------------------------------------------------------
# 常數
# ---------------------------------------------------------------------------

DEFAULT_URL = (
    "https://github.com/brannondorsey/naive-hashcat/releases/download/data/rockyou.txt"
)
DEFAULT_OUT_DIR = Path(__file__).parent / "wordlists"
CHUNK_SIZE = 1024 * 1024          # 1 MB per read chunk
PROGRESS_INTERVAL = 5 * 1024 * 1024  # 每 5 MB 更新一次進度

# WPA-Personal 密碼長度限制
WPA_MIN = 8
WPA_MAX = 63


# ---------------------------------------------------------------------------
# 下載 (支援 Range 續傳)
# ---------------------------------------------------------------------------

def download(url: str, dest: Path) -> Path:
    """
    將 url 下載到 dest 目錄，檔名從 URL 末段取得。
    若已存在 .part 暫存檔則從斷點續傳。
    回傳完整檔案路徑。
    """
    filename = url.split("/")[-1]
    dest.mkdir(parents=True, exist_ok=True)
    final_path = dest / filename
    part_path = dest / (filename + ".part")

    # 若完整檔案已存在，直接跳過下載
    if final_path.exists():
        print(f"[INFO] 檔案已存在，跳過下載: {final_path}")
        return final_path

    # 取得已下載的位元組數 (用於續傳)
    downloaded = part_path.stat().st_size if part_path.exists() else 0

    headers = {}
    if downloaded:
        headers["Range"] = f"bytes={downloaded}-"
        print(f"[INFO] 從斷點續傳，已下載 {downloaded / 1024 / 1024:.1f} MB")

    with requests.get(url, headers=headers, stream=True, timeout=30) as resp:
        if resp.status_code == 416:
            # Range Not Satisfiable → 伺服器認為已完整，重新從頭下載
            print("[WARN] 伺服器拒絕 Range 請求，從頭重新下載 ...")
            downloaded = 0
            headers.pop("Range", None)
            resp = requests.get(url, headers=headers, stream=True, timeout=30)
            resp.raise_for_status()
        elif resp.status_code not in (200, 206):
            resp.raise_for_status()

        total_raw = resp.headers.get("Content-Length")
        total = (int(total_raw) + downloaded) if total_raw else None

        mode = "ab" if downloaded else "wb"
        next_report = downloaded + PROGRESS_INTERVAL

        with open(part_path, mode) as f:
            for chunk in resp.iter_content(chunk_size=CHUNK_SIZE):
                if not chunk:
                    continue
                f.write(chunk)
                downloaded += len(chunk)
                if downloaded >= next_report:
                    if total:
                        pct = downloaded / total * 100
                        print(
                            f"\r[DL] {downloaded / 1024 / 1024:.0f} MB / "
                            f"{total / 1024 / 1024:.0f} MB  ({pct:.1f}%)",
                            end="",
                            flush=True,
                        )
                    else:
                        print(
                            f"\r[DL] {downloaded / 1024 / 1024:.0f} MB",
                            end="",
                            flush=True,
                        )
                    next_report = downloaded + PROGRESS_INTERVAL

    print()  # 換行
    part_path.rename(final_path)
    print(f"[OK] 下載完成: {final_path}  ({final_path.stat().st_size / 1024 / 1024:.1f} MB)")
    return final_path


# ---------------------------------------------------------------------------
# WPA 長度過濾
# ---------------------------------------------------------------------------

def filter_wpa(src: Path, dst: Path) -> int:
    """
    從 src 逐行讀取，保留長度在 WPA_MIN-WPA_MAX 之間的密碼，寫入 dst。
    回傳保留的行數。
    """
    if dst.exists():
        print(f"[INFO] 過濾後的字典已存在，跳過過濾: {dst}")
        # 快速計行數
        count = sum(1 for _ in open(dst, "rb"))
        return count

    print(f"[INFO] 過濾 WPA 長度 ({WPA_MIN}-{WPA_MAX} 字元)，請稍候 ...")
    kept = 0
    total_read = 0

    with open(src, "rb") as fin, open(dst, "wb") as fout:
        for raw in fin:
            total_read += 1
            line = raw.rstrip(b"\r\n")
            if WPA_MIN <= len(line) <= WPA_MAX:
                fout.write(line + b"\n")
                kept += 1
            if total_read % 1_000_000 == 0:
                print(f"  已處理 {total_read // 1_000_000}M 行，保留 {kept:,} 筆 ...", flush=True)

    print(f"[OK] 過濾完成: {kept:,} 筆 WPA 密碼 → {dst}")
    return kept


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="下載資安常用密碼字典並過濾為 WPA 適用格式",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--url",
        default=DEFAULT_URL,
        help=f"字典下載網址 (預設: rockyou.txt GitHub mirror)",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=DEFAULT_OUT_DIR,
        help=f"輸出目錄 (預設: {DEFAULT_OUT_DIR})",
    )
    parser.add_argument(
        "--no-filter",
        action="store_true",
        help="下載後不過濾 WPA 長度，保留原始字典",
    )
    args = parser.parse_args()

    try:
        raw_path = download(args.url, args.out_dir)
    except KeyboardInterrupt:
        print("\n[中斷] 下載已暫停，下次執行將從斷點續傳。")
        return 1
    except requests.RequestException as exc:
        print(f"[ERROR] 下載失敗: {exc}", file=sys.stderr)
        return 1

    if args.no_filter:
        return 0

    stem = raw_path.stem
    wpa_path = args.out_dir / f"{stem}_wpa.txt"

    try:
        count = filter_wpa(raw_path, wpa_path)
    except KeyboardInterrupt:
        print("\n[中斷] 過濾已暫停。")
        return 1

    print(f"\n字典路徑 : {wpa_path}")
    print(f"密碼總數 : {count:,}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
