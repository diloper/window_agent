"""Phase 4 - train the skip-button YOLO model locally with Ultralytics.

Trains from the group-split dataset produced by ``prepare_ad_dataset.py`` and
copies the best weights to ``ad_skipper/models/skip_ad_yolo.pt`` for runtime.
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path
from typing import List, Optional

HERE = Path(__file__).resolve().parent
DATA_YAML = HERE / "dataset" / "yolo" / "data.yaml"
MODELS_DIR = HERE / "models"
RUNS_DIR = HERE / "runs"
OUTPUT_WEIGHTS = MODELS_DIR / "skip_ad_yolo.pt"


def train(args: argparse.Namespace) -> int:
    if not DATA_YAML.exists():
        print(f"data.yaml not found: {DATA_YAML}. Run prepare_ad_dataset.py first.", file=sys.stderr)
        return 2

    try:
        from ultralytics import YOLO
    except Exception as exc:  # noqa: BLE001
        print(f"ultralytics not installed: {exc}", file=sys.stderr)
        return 2

    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    model = YOLO(args.base_model)
    results = model.train(
        data=str(DATA_YAML),
        epochs=args.epochs,
        imgsz=args.imgsz,
        batch=args.batch,
        device=args.device,
        seed=args.seed,
        project=str(RUNS_DIR),
        name=args.name,
        exist_ok=True,
    )

    save_dir = Path(getattr(results, "save_dir", RUNS_DIR / args.name))
    best = save_dir / "weights" / "best.pt"
    if best.exists():
        shutil.copy(best, OUTPUT_WEIGHTS)
        print(f"Best weights -> {OUTPUT_WEIGHTS}")
    else:
        print(f"WARNING: best.pt not found under {save_dir}", file=sys.stderr)
        return 1
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Train skip-button YOLO model (Phase 4)")
    p.add_argument("--base-model", default="yolo11n.pt", help="Pretrained base checkpoint")
    p.add_argument("--epochs", type=int, default=100)
    p.add_argument("--imgsz", type=int, default=640)
    p.add_argument("--batch", type=int, default=16)
    p.add_argument("--device", default=None, help="cuda device id, 'cpu', or None for auto")
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--name", default="train", help="Run name under ad_skipper/runs/")
    return p


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    return train(args)


if __name__ == "__main__":
    raise SystemExit(main())
