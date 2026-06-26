"""wifi_connect.py — 自動連線指定 WiFi (Windows)

Usage:
    # 連線已存在的 profile
    python wifi_connect.py --ssid "MyNetwork"

    # 建立新 profile 並連線
    python wifi_connect.py --ssid "MyNetwork" --password "MyPassword"

    # 指定網路介面卡
    python wifi_connect.py --ssid "MyNetwork" --interface "Wi-Fi"

Notes:
    - 建立新 profile (需 --password) 可能需要系統管理員權限。
    - 「連線已存在 profile」通常不需要提權。
"""

import argparse
import subprocess
import sys
import tempfile
import time
import os


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _run(cmd: list[str]) -> tuple[int, str, str]:
    """執行命令，回傳 (returncode, stdout, stderr)。"""
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return result.returncode, result.stdout, result.stderr


def _get_interfaces() -> list[str]:
    """回傳系統上所有無線網路介面名稱。"""
    _, out, _ = _run(["netsh", "wlan", "show", "interfaces"])
    interfaces = []
    for line in out.splitlines():
        stripped = line.strip()
        if stripped.lower().startswith("name"):
            parts = stripped.split(":", 1)
            if len(parts) == 2:
                interfaces.append(parts[1].strip())
    return interfaces


def _profile_exists(ssid: str) -> bool:
    """回傳 True 若 Windows 中已存在此 SSID 的 profile。"""
    _, out, _ = _run(["netsh", "wlan", "show", "profiles"])
    for line in out.splitlines():
        stripped = line.strip()
        # 中文 Windows: "所有使用者設定檔 : SSID"
        # 英文 Windows: "All User Profile     : SSID"
        if ":" in stripped:
            profile_name = stripped.split(":", 1)[1].strip()
            if profile_name.lower() == ssid.lower():
                return True
    return False


def _build_wpa2_xml(ssid: str, password: str) -> str:
    """產生 WPA2-Personal (PSK/AES) 的 WLAN profile XML。"""
    # hex encode SSID for the <hex> element
    ssid_hex = ssid.encode("utf-8").hex().upper()
    return f"""<?xml version="1.0"?>
<WLANProfile xmlns="http://www.microsoft.com/networking/WLAN/profile/v1">
    <name>{ssid}</name>
    <SSIDConfig>
        <SSID>
            <hex>{ssid_hex}</hex>
            <name>{ssid}</name>
        </SSID>
    </SSIDConfig>
    <connectionType>ESS</connectionType>
    <connectionMode>manual</connectionMode>
    <MSM>
        <security>
            <authEncryption>
                <authentication>WPA2PSK</authentication>
                <encryption>AES</encryption>
                <useOneX>false</useOneX>
            </authEncryption>
            <sharedKey>
                <keyType>passPhrase</keyType>
                <protected>false</protected>
                <keyMaterial>{password}</keyMaterial>
            </sharedKey>
        </security>
    </MSM>
</WLANProfile>
"""


def _build_open_xml(ssid: str) -> str:
    """產生開放式 (無密碼) 的 WLAN profile XML。"""
    ssid_hex = ssid.encode("utf-8").hex().upper()
    return f"""<?xml version="1.0"?>
<WLANProfile xmlns="http://www.microsoft.com/networking/WLAN/profile/v1">
    <name>{ssid}</name>
    <SSIDConfig>
        <SSID>
            <hex>{ssid_hex}</hex>
            <name>{ssid}</name>
        </SSID>
    </SSIDConfig>
    <connectionType>ESS</connectionType>
    <connectionMode>manual</connectionMode>
    <MSM>
        <security>
            <authEncryption>
                <authentication>open</authentication>
                <encryption>none</encryption>
                <useOneX>false</useOneX>
            </authEncryption>
        </security>
    </MSM>
</WLANProfile>
"""


def _add_profile(ssid: str, password: str | None, interface: str) -> bool:
    """建立並加入 WiFi profile，成功回傳 True。"""
    xml_content = _build_wpa2_xml(ssid, password) if password else _build_open_xml(ssid)

    # 寫入暫存檔，加入 profile 後立即刪除，避免密碼殘留在磁碟
    tmp_path = None
    try:
        fd, tmp_path = tempfile.mkstemp(suffix=".xml", prefix="wlan_profile_")
        os.close(fd)
        with open(tmp_path, "w", encoding="utf-8") as f:
            f.write(xml_content)

        rc, out, err = _run(
            ["netsh", "wlan", "add", "profile",
             f"filename={tmp_path}",
             f"interface={interface}",
             "user=all"]
        )
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.remove(tmp_path)

    if rc != 0:
        print(f"[ERROR] 加入 profile 失敗: {err.strip() or out.strip()}", file=sys.stderr)
        return False
    return True


def _wait_for_connection(ssid: str, interface: str, timeout: int = 15) -> bool:
    """輪詢直到連線成功或逾時，回傳是否連線成功。"""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        _, out, _ = _run(["netsh", "wlan", "show", "interfaces"])
        lines = out.splitlines()
        state = ""
        connected_ssid = ""
        for line in lines:
            stripped = line.strip().lower()
            if stripped.startswith("state") and ":" in stripped:
                state = line.split(":", 1)[1].strip().lower()
            if stripped.startswith("ssid") and "bssid" not in stripped and ":" in stripped:
                connected_ssid = line.split(":", 1)[1].strip()
        if state in ("connected", "已連線") and connected_ssid.lower() == ssid.lower():
            return True
        time.sleep(1)
    return False


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="自動連線 Windows 指定 WiFi 網路",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--ssid", required=True, help="目標 WiFi 的 SSID 名稱")
    parser.add_argument("--password", default=None, help="WiFi 密碼 (WPA2-Personal)；省略則視為已存在 profile 或開放式網路")
    parser.add_argument("--interface", default=None, help="無線網路介面卡名稱 (預設自動偵測)")
    parser.add_argument("--timeout", type=int, default=15, help="等待連線的秒數 (預設 15)")
    args = parser.parse_args()

    # 偵測介面卡
    if args.interface:
        interface = args.interface
    else:
        interfaces = _get_interfaces()
        if not interfaces:
            print("[ERROR] 找不到無線網路介面卡，請確認 Wi-Fi 功能已開啟。", file=sys.stderr)
            return 1
        interface = interfaces[0]
        if len(interfaces) > 1:
            print(f"[INFO] 偵測到多個介面卡，使用第一個: {interface!r}")

    print(f"[INFO] 使用介面卡: {interface!r}")
    print(f"[INFO] 目標 SSID : {args.ssid!r}")

    # 決定是否需要建立 profile
    exists = _profile_exists(args.ssid)

    if args.password:
        print(f"[INFO] 已提供密碼，{'更新' if exists else '建立'}並加入 profile ...")
        if not _add_profile(args.ssid, args.password, interface):
            return 1
    elif not exists:
        print(
            f"[ERROR] SSID {args.ssid!r} 的 profile 不存在，且未提供 --password。\n"
            "請加上 --password 參數以建立新 profile。",
            file=sys.stderr,
        )
        return 1
    else:
        print("[INFO] 找到既有 profile，直接連線 ...")

    # 觸發連線
    rc, out, err = _run(
        ["netsh", "wlan", "connect",
         f"name={args.ssid}",
         f"interface={interface}"]
    )
    if rc != 0:
        print(f"[ERROR] 連線指令失敗: {err.strip() or out.strip()}", file=sys.stderr)
        return 1

    print(f"[INFO] 等待連線完成 (最多 {args.timeout} 秒) ...")
    if _wait_for_connection(args.ssid, interface, args.timeout):
        print(f"[OK] 已成功連線至 {args.ssid!r}")
        return 0
    else:
        print(
            f"[WARN] {args.timeout} 秒內未確認連線至 {args.ssid!r}，"
            "可能仍在連線中或密碼錯誤。",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())
