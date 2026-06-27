"""Phase 1 - Selenium-driven YouTube ad-frame harvester.

Auto-watches YouTube in a Selenium-controlled headed Chrome, deterministically
detects when an ad is showing (via the player's ``ad-showing`` class /
``getAdState()``), captures the REAL desktop with ``mss``, and writes a YOLO
label directly from the skip button's exact ``element.rect`` (#5). It also
collects negative / hard-negative frames (#6) and randomizes the player layout
(#2) so the trained model generalizes.

Non-intrusive: Selenium drives its own window, the process runs at below-normal
priority, and screen grabs only happen on relevant events.

Example:
    python collect_ad_frames.py --query "music video" --max-frames 400 \
        --neg-ratio 0.4 --vary-layout --draw
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import time
import uuid
from pathlib import Path
from typing import List, Optional

import cv2

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from _capture import (  # noqa: E402
    BBox,
    ScreenCapture,
    draw_bbox,
    viewport_rect_to_image_bbox,
)

DATASET_DIR = HERE / "dataset"
IMAGES_DIR = DATASET_DIR / "images"
LABELS_DIR = DATASET_DIR / "labels"
RAW_BOXES_DIR = DATASET_DIR / "raw_boxes"
DEBUG_DIR = DATASET_DIR / "debug"

# Verbose status output is ON by default; pass --quiet to silence it.
_VERBOSE = True


def _log(msg: str) -> None:
    """Print a status line to stderr when verbose mode is on (the default)."""
    if _VERBOSE:
        print(f"[collect] {msg}", file=sys.stderr, flush=True)


# Configurable selector candidates (YouTube renames these periodically).
SKIP_BUTTON_SELECTORS = (
    ".ytp-ad-skip-button-modern",
    ".ytp-ad-skip-button",
    ".ytp-skip-ad-button",
)

# JS snippet: returns ad state + skip-button rect (viewport CSS px) in one round-trip.
_PLAYER_STATE_JS = """
const selectors = arguments[0];
const player = document.querySelector('#movie_player') ||
               document.querySelector('.html5-video-player');
if (!player) return {ready: false};
const cls = player.classList || {contains: () => false};
let adState = null;
try { if (typeof player.getAdState === 'function') adState = player.getAdState(); } catch (e) {}
const adShowing = cls.contains('ad-showing') || cls.contains('ad-interrupting') || adState === 1;
let rect = null;
for (const sel of selectors) {
    const el = document.querySelector(sel);
    if (el && el.offsetParent !== null) {
        const r = el.getBoundingClientRect();
        if (r.width > 0 && r.height > 0) {
            rect = {x: r.x, y: r.y, width: r.width, height: r.height};
            break;
        }
    }
}
return {
    ready: true,
    adShowing: !!adShowing,
    skip: rect,
    toolbar: window.outerHeight - window.innerHeight,
    dpr: window.devicePixelRatio || 1,
};
"""


def _set_low_priority() -> None:
    """Best-effort below-normal process priority (non-intrusive)."""
    try:
        import psutil

        p = psutil.Process()
        if sys.platform.startswith("win"):
            p.nice(psutil.BELOW_NORMAL_PRIORITY_CLASS)
        else:
            p.nice(10)
    except Exception:
        pass


def _build_driver(profile: Optional[str], profile_directory: Optional[str], headless: bool):
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options

    options = Options()
    if profile:
        options.add_argument(f"--user-data-dir={profile}")
        if profile_directory:
            options.add_argument(f"--profile-directory={profile_directory}")
    if headless:
        options.add_argument("--headless=new")
    options.add_argument("--autoplay-policy=no-user-gesture-required")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])

    try:
        from selenium.webdriver.chrome.service import Service
        from webdriver_manager.chrome import ChromeDriverManager

        return webdriver.Chrome(
            service=Service(ChromeDriverManager().install()), options=options
        )
    except Exception:
        # Fall back to Selenium Manager (bundled with Selenium 4.6+).
        return webdriver.Chrome(options=options)


def _resolve_video_urls(driver, urls: List[str], query: Optional[str], limit: int) -> List[str]:
    if urls:
        _log(f"using {len(urls)} explicit URL(s)")
        return urls
    if not query:
        raise ValueError("Provide --urls or --query")

    from urllib.parse import quote_plus

    _log(f"resolving videos from query {query!r} (limit={limit}) ...")
    driver.get(f"https://www.youtube.com/results?search_query={quote_plus(query)}")
    time.sleep(3.0)
    ids = driver.execute_script(
        """
        const out = [];
        for (const a of document.querySelectorAll('a#video-title, a#thumbnail')) {
            const href = a.getAttribute('href') || '';
            const m = href.match(/[?&]v=([\\w-]{11})/);
            if (m && !out.includes(m[1])) out.push(m[1]);
        }
        return out;
        """
    )
    resolved = [f"https://www.youtube.com/watch?v={vid}" for vid in ids[:limit]]
    _log(f"resolved {len(resolved)} video(s) from query")
    return resolved


def _apply_layout(driver, vary: bool) -> None:
    if not vary:
        return
    width = random.choice([960, 1100, 1280, 1366, 1600])
    height = random.choice([600, 720, 800, 900])
    try:
        driver.set_window_size(width, height)
        driver.set_window_position(random.randint(0, 60), random.randint(0, 60))
    except Exception:
        pass


def _save_frame(
    frame,
    group: str,
    seq: int,
    bbox: Optional[BBox],
    raw_rect: Optional[dict],
    draw: bool,
) -> None:
    name = f"{group}_{seq:04d}"
    img_h, img_w = frame.shape[:2]
    cv2.imwrite(str(IMAGES_DIR / f"{name}.png"), frame)

    label_path = LABELS_DIR / f"{name}.txt"
    if bbox is not None:
        nx, ny, nw, nh = bbox.to_yolo(img_w, img_h)
        label_path.write_text(f"0 {nx:.6f} {ny:.6f} {nw:.6f} {nh:.6f}\n", encoding="utf-8")
    else:
        # Negative / hard-negative frame: empty label file.
        label_path.write_text("", encoding="utf-8")

    RAW_BOXES_DIR.joinpath(f"{name}.json").write_text(
        json.dumps(
            {
                "group": group,
                "seq": seq,
                "image": f"{name}.png",
                "img_w": img_w,
                "img_h": img_h,
                "rect_viewport": raw_rect,
                "bbox_image_px": None if bbox is None else [bbox.x, bbox.y, bbox.w, bbox.h],
                "positive": bbox is not None,
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    if draw and bbox is not None:
        DEBUG_DIR.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(DEBUG_DIR / f"{name}.png"), draw_bbox(frame, bbox))


def _phash(frame):
    try:
        import imagehash
        from PIL import Image

        return imagehash.phash(Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)))
    except Exception:
        return None


def harvest(args: argparse.Namespace) -> int:
    for d in (IMAGES_DIR, LABELS_DIR, RAW_BOXES_DIR):
        d.mkdir(parents=True, exist_ok=True)

    _set_low_priority()
    capture = ScreenCapture(monitor_index=args.monitor)
    mon_left, mon_top = capture.monitor_offset()

    _log(
        f"launching Chrome (profile={args.profile or 'temporary'}, "
        f"profile-directory={args.profile_directory}, headless={args.headless})"
    )
    driver = _build_driver(args.profile, args.profile_directory, args.headless)
    _log("Chrome launched; resolving video sources ...")
    saved = 0
    saved_pos = 0
    saved_neg = 0
    seen_hashes: set = set()

    def want_negative() -> bool:
        total = saved_pos + saved_neg
        if total == 0:
            return False
        return (saved_neg / total) < args.neg_ratio

    try:
        urls = _resolve_video_urls(driver, args.urls or [], args.query, args.url_limit)
        if not urls:
            print("No videos resolved.", file=sys.stderr)
            return 2

        total = len(urls)
        for vi, url in enumerate(urls, 1):
            if saved >= args.max_frames:
                break
            _apply_layout(driver, args.vary_layout)
            try:
                driver.get(url)
            except Exception as exc:  # noqa: BLE001
                print(f"skip {url}: {exc}", file=sys.stderr)
                continue
            _log(f"video {vi}/{total}: {url}")
            time.sleep(2.5)

            frames_this_ad = 0
            ad_group = f"{args.session_id}-{uuid.uuid4().hex[:6]}"
            video_deadline = time.monotonic() + args.per_video_seconds
            last_status = 0.0
            last_ad_showing: Optional[bool] = None

            while time.monotonic() < video_deadline and saved < args.max_frames:
                try:
                    state = driver.execute_script(_PLAYER_STATE_JS, list(SKIP_BUTTON_SELECTORS))
                except Exception:
                    state = None

                now = time.monotonic()
                if not state or not state.get("ready"):
                    if now - last_status >= 5.0:
                        _log(f"status: video {vi}/{total} | player not ready yet")
                        last_status = now
                    time.sleep(args.poll_interval)
                    continue

                ad_showing = state.get("adShowing")
                skip_rect = state.get("skip")

                if ad_showing != last_ad_showing:
                    if ad_showing:
                        _log(f"ad showing (skip button ready={bool(skip_rect)})")
                    else:
                        _log("content playing (no ad)")
                    last_ad_showing = ad_showing
                if now - last_status >= 5.0:
                    remaining = max(0.0, video_deadline - now)
                    _log(
                        f"status: video {vi}/{total} | "
                        f"ad={'yes' if ad_showing else 'no'} | "
                        f"saved={saved} (pos={saved_pos}, neg={saved_neg}) | "
                        f"time_left={remaining:.0f}s"
                    )
                    last_status = now

                if ad_showing and skip_rect:
                    frame = capture.grab()
                    win = driver.get_window_rect()
                    bbox = viewport_rect_to_image_bbox(
                        rect=skip_rect,
                        window_rect=win,
                        toolbar_height=float(state.get("toolbar", 0) or 0),
                        device_pixel_ratio=float(state.get("dpr", 1) or 1),
                        monitor_left=mon_left,
                        monitor_top=mon_top,
                    )
                    h = _phash(frame)
                    if h is not None and h in seen_hashes:
                        time.sleep(args.poll_interval)
                        continue
                    if h is not None:
                        seen_hashes.add(h)
                    _save_frame(frame, ad_group, frames_this_ad, bbox, skip_rect, args.draw)
                    saved += 1
                    saved_pos += 1
                    frames_this_ad += 1
                    _log(
                        f"saved positive frame (saved={saved}, "
                        f"pos={saved_pos}, neg={saved_neg})"
                    )
                    if frames_this_ad >= args.frames_per_ad:
                        # Skip the ad to move on and find a different one.
                        _log("enough frames for this ad; clicking skip")
                        _click_skip(driver)
                        time.sleep(1.0)
                        frames_this_ad = 0
                        ad_group = f"{args.session_id}-{uuid.uuid4().hex[:6]}"
                elif not ad_showing and want_negative():
                    frame = capture.grab()
                    h = _phash(frame)
                    if h is not None and h in seen_hashes:
                        time.sleep(args.poll_interval)
                        continue
                    if h is not None:
                        seen_hashes.add(h)
                    neg_group = f"{args.session_id}-neg-{uuid.uuid4().hex[:6]}"
                    _save_frame(frame, neg_group, 0, None, None, args.draw)
                    saved += 1
                    saved_neg += 1
                    _log(
                        f"saved negative frame (saved={saved}, "
                        f"pos={saved_pos}, neg={saved_neg})"
                    )

                time.sleep(args.poll_interval)

        print(
            f"Done. saved={saved} (positive={saved_pos}, negative={saved_neg}) -> {IMAGES_DIR}"
        )
        return 0
    finally:
        capture.close()
        try:
            driver.quit()
        except Exception:
            pass


def _click_skip(driver) -> None:
    for sel in SKIP_BUTTON_SELECTORS:
        try:
            els = driver.find_elements("css selector", sel)
            for el in els:
                if el.is_displayed():
                    el.click()
                    return
        except Exception:
            continue


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Selenium YouTube ad-frame harvester (Phase 1)")
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--urls", nargs="+", help="Explicit YouTube watch URLs")
    src.add_argument("--query", help="YouTube search query to source videos")
    p.add_argument("--url-limit", type=int, default=15, help="Max videos to resolve from --query")
    p.add_argument("--profile", help="Chrome user-data-dir (real profile = real ads)")
    p.add_argument(
        "--profile-directory",
        default="Default",
        help="Chrome profile folder name to pick an account (e.g. 'Default', 'Profile 16')",
    )
    p.add_argument("--monitor", type=int, default=1, help="mss monitor index (1=primary)")
    p.add_argument("--poll-interval", type=float, default=0.4, help="Player poll seconds")
    p.add_argument("--max-frames", type=int, default=300, help="Stop after this many saved frames")
    p.add_argument("--frames-per-ad", type=int, default=4, help="Frames to grab per ad instance")
    p.add_argument("--neg-ratio", type=float, default=0.4, help="Target negative-frame fraction (0..1)")
    p.add_argument("--per-video-seconds", type=float, default=120.0, help="Max watch time per video")
    p.add_argument("--vary-layout", action="store_true", help="Randomize window size/position (#2)")
    p.add_argument("--headless", action="store_true", help="Run Chrome headless (fewer ads)")
    p.add_argument("--draw", action="store_true", help="Save bbox-overlay debug images")
    p.add_argument(
        "--quiet",
        action="store_true",
        help="Silence verbose status output (verbose is on by default)",
    )
    p.add_argument("--session-id", default=time.strftime("%Y%m%d-%H%M%S"), help="Group-key session id")
    return p


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    global _VERBOSE
    _VERBOSE = not args.quiet
    if not 0.0 <= args.neg_ratio <= 1.0:
        print("--neg-ratio must be in [0, 1]", file=sys.stderr)
        return 2
    _log(
        f"starting harvester | source={'urls' if args.urls else 'query'} | "
        f"max_frames={args.max_frames} | neg_ratio={args.neg_ratio} | "
        f"frames_per_ad={args.frames_per_ad}"
    )
    try:
        return harvest(args)
    except KeyboardInterrupt:
        print("\nInterrupted by user; partial dataset kept.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
