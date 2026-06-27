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

DEFAULT_MODEL = HERE / "models" / "skip_ad_yolo.pt"

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
        print(f"Model not found: {model_path}. Train it first (train_skip_model.py).", file=sys.stderr)
        return 2

    try:
        from ultralytics import YOLO
    except Exception as exc:  # noqa: BLE001
        print(f"ultralytics not installed: {exc}", file=sys.stderr)
        return 2

    model = YOLO(str(model_path))
    capture = ScreenCapture(monitor_index=args.monitor)
    mon_left, mon_top = capture.monitor_offset()

    signal.signal(signal.SIGINT, _handle_sigint)

    last_center: Optional[Tuple[float, float]] = None
    stable_hits = 0
    last_click = 0.0
    print(f"Running ({'dry-run' if args.dry_run else 'live'}). Ctrl+C to stop.")

    try:
        while not _stop:
            loop_start = time.perf_counter()
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
                        print(f"[dry-run] skip button @ screen ({sx}, {sy}) conf>={args.conf}")
                    else:
                        cursor_preserving_click(sx, sy)
                        print(f"Clicked skip @ ({sx}, {sy})")
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
    return p


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return run(args)
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
