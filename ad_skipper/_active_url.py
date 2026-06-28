"""Phase 6 - active-tab gate that decides whether the foreground window is a
YouTube *watch* page (and therefore whether the ad-skipper should capture and
run detection).

Layered decision (see PHASES_GUIDE.md "Phase 6"):
    1. Title pre-filter  - foreground process is a known browser AND the window
       title contains "YouTube" (works even in fullscreen). Otherwise NONE.
    2. UIA URL read      - when the address bar is reachable (windowed), read the
       omnibox value via UI Automation and classify WATCH / SHORTS / OTHER. The
       result is cached per window handle (keyed by hwnd + title).
    3. Per-window cache  - in fullscreen the address bar is gone; reuse the last
       known classification for that window (title still matches the cached tab).
    4. Title fallback    - if the URL is unreadable AND there is no usable cache,
       fall back to a lightweight title heuristic (best effort).

This module is Windows-only (it relies on user32 / UI Automation). It degrades
gracefully if ``uiautomation`` is missing: detection falls back to the title
heuristic only.
"""

from __future__ import annotations

import re
import sys
from typing import Dict, Optional, Tuple

# Classification constants -------------------------------------------------
WATCH = "WATCH"
SHORTS = "SHORTS"
OTHER = "OTHER"
NONE = "NONE"

_BROWSERS = {"chrome.exe", "msedge.exe", "firefox.exe"}

# --- Win32 helpers (ctypes) ----------------------------------------------
try:
    import ctypes
    from ctypes import wintypes

    _user32 = ctypes.windll.user32
    _WIN32_OK = True
except Exception:  # pragma: no cover - non-Windows safety net
    _WIN32_OK = False

try:
    import psutil
except Exception:  # pragma: no cover - dependency guard
    psutil = None  # type: ignore

# --- UI Automation (optional) --------------------------------------------
try:
    import uiautomation as _auto  # type: ignore

    # Keep implicit element searches snappy; we mostly use GetChildren which is
    # immediate, but this guards any internal waits from blocking the loop.
    try:
        _auto.SetGlobalSearchTimeout(1)
    except Exception:
        pass
    _UIA_OK = True
except Exception:
    _auto = None  # type: ignore
    _UIA_OK = False


def _foreground_hwnd() -> int:
    if not _WIN32_OK:
        return 0
    try:
        return int(_user32.GetForegroundWindow())
    except Exception:
        return 0


def _window_title(hwnd: int) -> str:
    if not _WIN32_OK or not hwnd:
        return ""
    try:
        length = int(_user32.GetWindowTextLengthW(hwnd))
        if length <= 0:
            return ""
        buf = ctypes.create_unicode_buffer(length + 1)
        _user32.GetWindowTextW(hwnd, buf, length + 1)
        return buf.value
    except Exception:
        return ""


def _process_name(hwnd: int) -> str:
    if not _WIN32_OK or not hwnd or psutil is None:
        return ""
    try:
        pid = wintypes.DWORD()
        _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        return psutil.Process(pid.value).name().lower()
    except Exception:
        return ""


def _looks_like_url(value: Optional[str]) -> bool:
    """Heuristic: distinguish an omnibox URL from a page-internal text box.

    Real omnibox URLs have no internal spaces and contain a dot (or a scheme),
    e.g. ``youtube.com/watch?v=...``. Search/comment boxes are usually empty or
    contain free text with spaces.
    """
    if not value:
        return False
    s = value.strip()
    if not s or " " in s:
        return False
    return ("." in s) or s.lower().startswith("http")


def _iter_edit_controls(control, max_depth: int, depth: int = 0):
    """Depth-first walk yielding Edit controls under ``control``.

    Uses ``GetChildren`` (immediate, no implicit waits) to stay responsive.
    """
    try:
        children = control.GetChildren()
    except Exception:
        return
    for child in children:
        try:
            is_edit = child.ControlType == _auto.ControlType.EditControl
        except Exception:
            is_edit = False
        if is_edit:
            yield child
        if depth < max_depth:
            yield from _iter_edit_controls(child, max_depth, depth + 1)


def _read_omnibox_value(hwnd: int) -> Optional[str]:
    """Return the address-bar URL via UI Automation, or ``None`` if unreadable.

    We pick the first Edit control whose value looks like a URL, which avoids
    grabbing page-internal inputs (YouTube search/comment boxes).
    """
    if not _UIA_OK or not hwnd:
        return None
    try:
        win = _auto.ControlFromHandle(hwnd)
    except Exception:
        win = None
    if not win:
        return None
    for edit in _iter_edit_controls(win, max_depth=12):
        try:
            value = edit.GetValuePattern().Value
        except Exception:
            continue
        if _looks_like_url(value):
            return value.strip()
    return None


def classify_url(url: str) -> str:
    u = url.lower()
    if "youtube.com/shorts" in u or "/shorts/" in u:
        return SHORTS
    if "youtube.com/watch" in u or "youtu.be/" in u:
        return WATCH
    if "youtube.com" in u or "youtu.be" in u:
        return OTHER
    return OTHER


def classify_title(title: str) -> str:
    """Best-effort fallback when no URL is available.

    - title contains "shorts" -> SHORTS
    - "<real video title> - YouTube ..." -> WATCH (notification counts like
      "(12)" are stripped; a bare "YouTube" prefix is treated as home/feed)
    - otherwise -> NONE (conservative)
    """
    t = title.lower()
    if "shorts" in t:
        return SHORTS
    m = re.search(r"^(.*?)(?:\s[-—–]\s)youtube\b", t)
    if m:
        prefix = re.sub(r"^\(\d+\)\s*", "", m.group(1)).strip()
        if prefix:
            return WATCH
    return NONE


class ActiveUrlGate:
    """Stateful gate that classifies the foreground window per the layered rules."""

    def __init__(self, fallback: str = "title") -> None:
        if fallback not in {"title", "none", "watch"}:
            raise ValueError("fallback must be one of: title, none, watch")
        self.fallback = fallback
        # hwnd -> (classification, title) for the last successful URL read.
        self._cache: Dict[int, Tuple[str, str]] = {}

    def classify(self) -> str:
        hwnd = _foreground_hwnd()
        if not hwnd:
            return NONE
        if _process_name(hwnd) not in _BROWSERS:
            return NONE

        title = _window_title(hwnd)
        if "youtube" not in title.lower():
            self._cache.pop(hwnd, None)
            return NONE

        # Layer 2: live URL read (windowed).
        url = _read_omnibox_value(hwnd)
        if url:
            cls = classify_url(url)
            self._cache[hwnd] = (cls, title)
            return cls

        # Layer 3: per-window cache (fullscreen reuses last known tab state).
        cached = self._cache.get(hwnd)
        if cached and cached[1] == title:
            return cached[0]

        # Layer 4: lightweight title fallback.
        if self.fallback == "none":
            return NONE
        if self.fallback == "watch":
            return WATCH
        return classify_title(title)

    def should_detect(self) -> bool:
        return self.classify() == WATCH


def _main() -> int:
    """Manual test harness: print the live classification once per second."""
    import time

    gate = ActiveUrlGate(fallback="title")
    print(
        f"UIA available: {_UIA_OK} | Win32 available: {_WIN32_OK}. Ctrl+C to stop.",
        file=sys.stderr,
    )
    try:
        while True:
            hwnd = _foreground_hwnd()
            proc = _process_name(hwnd)
            title = _window_title(hwnd)
            url = _read_omnibox_value(hwnd) if proc in _BROWSERS else None
            print(
                f"proc={proc or '-'} | url={url or '-'} | "
                f"class={gate.classify()} | title={title[:60]!r}"
            )
            time.sleep(1.0)
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(_main())
