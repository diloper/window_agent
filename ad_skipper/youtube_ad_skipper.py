"""Phase 5 - runtime YouTube ad skipper.

Runs the trained YOLO model on the real desktop (any normal browser, NOT
Selenium) via the shared capture helper, and clicks the detected skip button
without disturbing the user's cursor. A stability gate requires the button to
be detected on >=2 consecutive frames at a consistent location before clicking
to avoid single-frame false positives.

Example:
    python youtube_ad_skipper.py            # live
    python youtube_ad_skipper.py --dry-run  # detect + log only, no click
"""

from __future__ import annotations

import argparse
import logging
import math
import signal
import sys
import time
from pathlib import Path
from typing import List, Optional, Tuple

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from _capture import ScreenCapture, cursor_preserving_click, image_point_to_screen  # noqa: E402
from _active_url import ActiveUrlGate  # noqa: E402

DEFAULT_MODEL = HERE / "models" / "skip_ad_yolo.pt"

_MUTEX_NAME = "Global\\SAM_youtube_ad_skipper"
_MUTEX_HANDLE = None

logger = logging.getLogger("ad_skipper.youtube_ad_skipper")

_stop = False


def _handle_sigint(_sig, _frm) -> None:
    global _stop
    _stop = True
    print("\nStopping...", file=sys.stderr)


def _center_distance(a: Tuple[float, float], b: Tuple[float, float]) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def run(args: argparse.Namespace) -> int:
    model_path = Path(args.model)
    if not model_path.exists():
        logger.error("Model not found: %s. Train it first (train_skip_model.py).", model_path)
        return 2

    try:
        from ultralytics import YOLO
    except Exception as exc:  # noqa: BLE001
        logger.error("ultralytics not installed: %s", exc)
        return 2

    model = YOLO(str(model_path))
    capture = ScreenCapture(monitor_index=args.monitor)
    mon_left, mon_top = capture.monitor_offset()

    signal.signal(signal.SIGINT, _handle_sigint)

    gate = ActiveUrlGate(fallback=args.fallback) if args.only_youtube_watch else None
    last_gate_check = 0.0
    gate_open = True
    prev_gate_open = True

    last_center: Optional[Tuple[float, float]] = None
    stable_hits = 0
    last_click = 0.0
    logger.info(
        "Running (%s%s). Ctrl+C to stop.",
        "dry-run" if args.dry_run else "live",
        ", watch-only gate" if gate is not None else "",
    )

    try:
        while not _stop:
            loop_start = time.perf_counter()

            if gate is not None:
                now = time.monotonic()
                if now - last_gate_check >= args.url_poll:
                    gate_open = gate.should_detect()
                    last_gate_check = now
                    if gate_open != prev_gate_open:
                        logger.info(
                            "URL gate %s",
                            "OPEN (YouTube watch)" if gate_open else "CLOSED (not a watch page)",
                        )
                        prev_gate_open = gate_open
                if not gate_open:
                    stable_hits = 0
                    last_center = None
                    time.sleep(args.interval)
                    continue

            frame = capture.grab()
            results = model.predict(frame, conf=args.conf, verbose=False)

            box = _best_box(results)
            if box is not None:
                cx, cy = (box[0] + box[2]) / 2.0, (box[1] + box[3]) / 2.0
                if last_center is not None and _center_distance((cx, cy), last_center) <= args.stable_px:
                    stable_hits += 1
                else:
                    stable_hits = 1
                last_center = (cx, cy)

                now = time.monotonic()
                if stable_hits >= args.stable_frames and (now - last_click) >= args.cooldown:
                    sx, sy = image_point_to_screen(cx, cy, mon_left, mon_top)
                    if args.dry_run:
                        logger.info("[dry-run] skip button @ screen (%s, %s) conf>=%s", sx, sy, args.conf)
                    else:
                        cursor_preserving_click(sx, sy)
                        logger.info("Clicked skip @ (%s, %s)", sx, sy)
                    last_click = now
                    stable_hits = 0
                    last_center = None
            else:
                stable_hits = 0
                last_center = None

            elapsed = time.perf_counter() - loop_start
            sleep_s = args.interval - elapsed
            if sleep_s > 0:
                time.sleep(sleep_s)
        return 0
    finally:
        capture.close()


def _best_box(results) -> Optional[Tuple[float, float, float, float]]:
    """Return the highest-confidence box as (x1, y1, x2, y2) in image px."""
    best = None
    best_conf = -1.0
    for r in results:
        boxes = getattr(r, "boxes", None)
        if boxes is None:
            continue
        for b in boxes:
            conf = float(b.conf[0]) if b.conf is not None else 0.0
            if conf > best_conf:
                xyxy = b.xyxy[0].tolist()
                best = (xyxy[0], xyxy[1], xyxy[2], xyxy[3])
                best_conf = conf
    return best


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Runtime YouTube ad skipper (Phase 5)")
    p.add_argument("--model", default=str(DEFAULT_MODEL), help="Path to trained .pt weights")
    p.add_argument("--monitor", type=int, default=1, help="mss monitor index (1=primary)")
    p.add_argument("--interval", type=float, default=0.5, help="Seconds between detections")
    p.add_argument("--conf", type=float, default=0.5, help="Detection confidence threshold")
    p.add_argument("--stable-frames", type=int, default=2, help="Consecutive detections before click")
    p.add_argument("--stable-px", type=float, default=25.0, help="Max center drift to count as stable")
    p.add_argument("--cooldown", type=float, default=2.0, help="Min seconds between clicks")
    p.add_argument("--dry-run", action="store_true", help="Log detections, do not click")
    p.add_argument(
        "--only-youtube-watch",
        action="store_true",
        help="Phase 6: only capture/detect when the foreground tab is a YouTube watch page",
    )
    p.add_argument("--url-poll", type=float, default=1.0, help="Seconds between URL-gate checks")
    p.add_argument(
        "--fallback",
        choices=["title", "none", "watch"],
        default="title",
        help="Gate decision when URL is unreadable and no cache exists",
    )
    p.add_argument("--log-file", default=None, help="Write logs to this file (for hidden/background runs)")
    p.add_argument(
        "--single-instance",
        action="store_true",
        help="Exit cleanly (0) if another instance is already running",
    )
    return p


def _setup_logging(args: argparse.Namespace) -> None:
    handlers: List[logging.Handler] = [logging.StreamHandler(sys.stderr)]
    if args.log_file:
        log_path = Path(args.log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(log_path, encoding="utf-8"))
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=handlers,
    )


def _acquire_single_instance(name: str):
    """Return a held mutex handle, or ``None`` if another instance owns it."""
    try:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.windll.kernel32
        kernel32.CreateMutexW.restype = wintypes.HANDLE
        kernel32.CreateMutexW.argtypes = [wintypes.LPCVOID, wintypes.BOOL, wintypes.LPCWSTR]
        handle = kernel32.CreateMutexW(None, False, name)
        error_already_exists = 183
        if not handle:
            return None
        if kernel32.GetLastError() == error_already_exists:
            kernel32.CloseHandle(handle)
            return None
        return handle
    except Exception:  # pragma: no cover - non-Windows safety net
        # Without a mutex we cannot guarantee single instance; allow running.
        return True


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    _setup_logging(args)

    if args.single_instance:
        global _MUTEX_HANDLE
        _MUTEX_HANDLE = _acquire_single_instance(_MUTEX_NAME)
        if _MUTEX_HANDLE is None:
            logger.info("Another instance is already running; exiting.")
            return 0

    try:
        return run(args)
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
