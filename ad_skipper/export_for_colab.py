"""Phase 4 (Colab prep) - package the YOLO dataset for Google Colab training.

Zips the group-split dataset produced by ``prepare_ad_dataset.py`` together with
a Colab-friendly ``data.yaml`` whose ``path`` points at the extraction dir on
Colab (default ``/content/ad_skipper_dataset``). Upload the resulting zip to
Colab and train with ``Train_Skip_Ad_Colab.ipynb``.

Example:
    python export_for_colab.py
    python export_for_colab.py --colab-dir /content/ad_skipper_dataset \
        --output ad_skipper/ad_skipper_dataset.zip
"""

from __future__ import annotations

import argparse
import sys
import zipfile
from pathlib import Path
from typing import List, Optional

HERE = Path(__file__).resolve().parent
YOLO_DIR = HERE / "dataset" / "yolo"
CLASSES_FILE = HERE / "ad_classes.txt"
DEFAULT_OUTPUT = HERE / "ad_skipper_dataset.zip"
DEFAULT_COLAB_DIR = "/content/ad_skipper_dataset"


def _load_classes() -> List[str]:
    if not CLASSES_FILE.exists():
        raise FileNotFoundError(f"classes file not found: {CLASSES_FILE}")
    return [ln.strip() for ln in CLASSES_FILE.read_text(encoding="utf-8").splitlines() if ln.strip()]


def _colab_yaml(colab_dir: str, classes: List[str]) -> str:
    return (
        f"path: {colab_dir}\n"
        "train: train/images\n"
        "val: val/images\n\n"
        f"nc: {len(classes)}\n"
        f"names: {classes}\n"
    )


def export(colab_dir: str, output: Path) -> int:
    if not YOLO_DIR.exists():
        print(f"Dataset not found: {YOLO_DIR}. Run prepare_ad_dataset.py first.", file=sys.stderr)
        return 2

    files = [p for p in YOLO_DIR.rglob("*") if p.is_file() and p.name != "data.yaml"]
    if not files:
        print(f"No dataset files under {YOLO_DIR}", file=sys.stderr)
        return 2

    classes = _load_classes()
    output.parent.mkdir(parents=True, exist_ok=True)

    img_count = lbl_count = 0
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in files:
            arcname = f.relative_to(YOLO_DIR).as_posix()
            zf.writestr(  # stream to avoid loading huge files at once
                arcname, f.read_bytes()
            )
            if f.suffix.lower() in {".png", ".jpg", ".jpeg"}:
                img_count += 1
            elif f.suffix.lower() == ".txt":
                lbl_count += 1
        # Colab-relative data.yaml at the archive root.
        zf.writestr("data.yaml", _colab_yaml(colab_dir, classes))

    size_mb = output.stat().st_size / (1024 * 1024)
    print(
        f"Wrote {output} ({size_mb:.1f} MB): images={img_count} labels={lbl_count} "
        f"classes={classes} colab_path={colab_dir}"
    )
    print("Upload this zip in the Colab notebook (Train_Skip_Ad_Colab.ipynb).")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Package YOLO dataset for Colab (Phase 4)")
    p.add_argument("--colab-dir", default=DEFAULT_COLAB_DIR, help="Extraction dir on Colab (data.yaml path)")
    p.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="Output zip path")
    return p


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    return export(args.colab_dir, args.output)


if __name__ == "__main__":
    raise SystemExit(main())
