"""Phase 3 - prepare a YOLO dataset with a GROUP-AWARE train/val split.

Mirrors the folder/yaml conventions of the repo's ``auto_prepare_dataset.py``
but assigns whole capture groups (``<session>_<adIdx>``) to a single split so
near-duplicate ad frames never leak across train and val (otherwise validation
mAP is meaningless). The group key is the filename minus the trailing
``_<seq>`` (and is cross-checked against raw_boxes json when present).
"""

from __future__ import annotations

import argparse
import json
import random
import re
import shutil
import sys
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional

HERE = Path(__file__).resolve().parent
DATASET_DIR = HERE / "dataset"
IMAGES_DIR = DATASET_DIR / "images"
LABELS_DIR = DATASET_DIR / "labels"
RAW_BOXES_DIR = DATASET_DIR / "raw_boxes"
YOLO_DIR = DATASET_DIR / "yolo"
CLASSES_FILE = HERE / "ad_classes.txt"

_SEQ_SUFFIX = re.compile(r"_\d+$")


def _group_key(stem: str) -> str:
    """Derive the group key from an image stem, e.g. ``sess-ab12_0003`` -> ``sess-ab12``."""
    raw = RAW_BOXES_DIR / f"{stem}.json"
    if raw.exists():
        try:
            meta = json.loads(raw.read_text(encoding="utf-8"))
            if meta.get("group"):
                return str(meta["group"])
        except Exception:
            pass
    return _SEQ_SUFFIX.sub("", stem)


def _load_classes() -> List[str]:
    if not CLASSES_FILE.exists():
        raise FileNotFoundError(f"classes file not found: {CLASSES_FILE}")
    return [ln.strip() for ln in CLASSES_FILE.read_text(encoding="utf-8").splitlines() if ln.strip()]


def _reset_output() -> None:
    if YOLO_DIR.exists():
        shutil.rmtree(YOLO_DIR)
    for sub in ("train/images", "train/labels", "val/images", "val/labels"):
        (YOLO_DIR / sub).mkdir(parents=True, exist_ok=True)


def prepare(train_ratio: float, seed: int) -> int:
    images = sorted(p for p in IMAGES_DIR.glob("*.png"))
    if not images:
        print(f"No images in {IMAGES_DIR}", file=sys.stderr)
        return 2

    groups: Dict[str, List[Path]] = defaultdict(list)
    for img in images:
        groups[_group_key(img.stem)].append(img)

    group_keys = sorted(groups)
    random.Random(seed).shuffle(group_keys)

    # Assign whole groups, steering toward the target FRAME ratio.
    total_frames = len(images)
    target_train = int(round(total_frames * train_ratio))
    train_keys: set = set()
    running = 0
    for key in group_keys:
        if running < target_train:
            train_keys.add(key)
            running += len(groups[key])
    # Guarantee val is non-empty.
    if len(train_keys) == len(group_keys) and len(group_keys) > 1:
        train_keys.discard(group_keys[-1])

    _reset_output()
    classes = _load_classes()
    counts = {"train": 0, "val": 0}

    for key in group_keys:
        split = "train" if key in train_keys else "val"
        for img in groups[key]:
            shutil.copy(img, YOLO_DIR / split / "images" / img.name)
            label = LABELS_DIR / (img.stem + ".txt")
            dst_label = YOLO_DIR / split / "labels" / (img.stem + ".txt")
            if label.exists():
                shutil.copy(label, dst_label)
            else:
                dst_label.write_text("", encoding="utf-8")
            counts[split] += 1

    # Sanity: no group key may appear in both splits.
    overlap = train_keys & (set(group_keys) - train_keys)
    assert not overlap, f"group leakage detected: {overlap}"

    data_yaml = YOLO_DIR / "data.yaml"
    data_yaml.write_text(
        "path: {}\n"
        "train: train/images\n"
        "val: val/images\n\n"
        "nc: {}\n"
        "names: {}\n".format(YOLO_DIR.as_posix(), len(classes), classes),
        encoding="utf-8",
    )

    print(
        f"Prepared dataset: groups={len(group_keys)} "
        f"train_frames={counts['train']} val_frames={counts['val']} "
        f"train_groups={len(train_keys)} val_groups={len(group_keys) - len(train_keys)}"
    )
    print(f"data.yaml -> {data_yaml}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Group-aware YOLO dataset prep (Phase 3)")
    p.add_argument("--train-ratio", type=float, default=0.8, help="Approx train fraction by frames")
    p.add_argument("--seed", type=int, default=42, help="Shuffle seed for reproducibility")
    return p


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    if not 0.0 < args.train_ratio < 1.0:
        print("--train-ratio must be in (0, 1)", file=sys.stderr)
        return 2
    return prepare(args.train_ratio, args.seed)


if __name__ == "__main__":
    raise SystemExit(main())
