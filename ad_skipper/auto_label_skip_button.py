"""Phase 2 (OPTIONAL) - review / refine auto-generated skip-button labels.

Phase 1 already writes YOLO labels directly, so this script is only for QA:
  * --overlay : render bbox overlays for every positive frame for visual review.
  * --repad   : regenerate YOLO txt from raw_boxes json with extra padding.
  * --report  : summarize positive/negative counts and flag missing labels.

It never deletes images; it only (re)writes labels or debug overlays.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import List, Optional

import cv2

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from _capture import BBox, draw_bbox  # noqa: E402

DATASET_DIR = HERE / "dataset"
IMAGES_DIR = DATASET_DIR / "images"
LABELS_DIR = DATASET_DIR / "labels"
RAW_BOXES_DIR = DATASET_DIR / "raw_boxes"
REVIEW_DIR = DATASET_DIR / "review"


def _iter_raw() -> List[Path]:
    return sorted(RAW_BOXES_DIR.glob("*.json"))


def repad(pad_frac: float) -> int:
    count = 0
    for raw_path in _iter_raw():
        meta = json.loads(raw_path.read_text(encoding="utf-8"))
        if not meta.get("positive"):
            continue
        box = meta.get("bbox_image_px")
        img_w, img_h = meta["img_w"], meta["img_h"]
        if not box:
            continue
        x, y, w, h = box
        px, py = w * pad_frac, h * pad_frac
        bbox = BBox(x=x - px, y=y - py, w=w + 2 * px, h=h + 2 * py)
        nx, ny, nw, nh = bbox.to_yolo(img_w, img_h)
        LABELS_DIR.joinpath(raw_path.stem + ".txt").write_text(
            f"0 {nx:.6f} {ny:.6f} {nw:.6f} {nh:.6f}\n", encoding="utf-8"
        )
        count += 1
    print(f"Re-padded {count} positive labels (pad={pad_frac}).")
    return count


def overlay() -> int:
    REVIEW_DIR.mkdir(parents=True, exist_ok=True)
    count = 0
    for raw_path in _iter_raw():
        meta = json.loads(raw_path.read_text(encoding="utf-8"))
        if not meta.get("positive"):
            continue
        box = meta.get("bbox_image_px")
        if not box:
            continue
        img_path = IMAGES_DIR / meta["image"]
        if not img_path.exists():
            continue
        frame = cv2.imread(str(img_path))
        if frame is None:
            continue
        bbox = BBox(*box)
        cv2.imwrite(str(REVIEW_DIR / meta["image"]), draw_bbox(frame, bbox))
        count += 1
    print(f"Wrote {count} overlay images -> {REVIEW_DIR}")
    return count


def report() -> int:
    images = sorted(IMAGES_DIR.glob("*.png"))
    positives = negatives = missing = 0
    for img in images:
        label = LABELS_DIR / (img.stem + ".txt")
        if not label.exists():
            missing += 1
            continue
        if label.read_text(encoding="utf-8").strip():
            positives += 1
        else:
            negatives += 1
    total = len(images)
    neg_frac = negatives / total if total else 0.0
    print(
        f"images={total} positive={positives} negative={negatives} "
        f"missing_label={missing} neg_ratio={neg_frac:.2f}"
    )
    if missing:
        print(f"WARNING: {missing} images have no label file.", file=sys.stderr)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Review/refine skip-button labels (Phase 2, optional)")
    p.add_argument("--overlay", action="store_true", help="Render bbox overlays for QA")
    p.add_argument("--repad", type=float, metavar="FRAC", help="Re-pad positive boxes by fraction (e.g. 0.15)")
    p.add_argument("--report", action="store_true", help="Print dataset label summary")
    return p


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    if not (args.overlay or args.repad is not None or args.report):
        args.report = True
    if args.repad is not None:
        repad(args.repad)
    if args.overlay:
        overlay()
    if args.report:
        report()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
