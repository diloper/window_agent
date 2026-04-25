"""Headless auto-labeling CLI without PyQt6 dependency.

This script uses ONNX backends directly:
- SAM1: anylabeling.services.auto_labeling.sam_onnx.SegmentAnythingONNX
- SAM2: anylabeling.services.auto_labeling.__base__.sam2.SegmentAnything2ONNX

Usage examples
--------------
# Rectangle (axis-aligned bounding box, default):
#   python tools/autolabel.py \\
#       --image  R:/SAM/tools/frame_00000.jpg \\
#       --encoder C:/Users/User/xanylabeling_data/models/sam2_hiera_large-r20240801/sam2.1_hiera_large.encoder.onnx \\
#       --decoder C:/Users/User/xanylabeling_data/models/sam2_hiera_large-r20240801/sam2.1_hiera_large.decoder.onnx \\
#       --points 640,698 \\
#       --output-mode rectangle
#
# Polygon (contour outline):
#   python tools/autolabel.py \\
#       --image  R:/SAM/tools/frame_00000.jpg \\
#       --encoder C:/Users/User/xanylabeling_data/models/sam2_hiera_large-r20240801/sam2.1_hiera_large.encoder.onnx \\
#       --decoder C:/Users/User/xanylabeling_data/models/sam2_hiera_large-r20240801/sam2.1_hiera_large.decoder.onnx \\
#       --points 640,698 \\
#       --output-mode polygon
#
# Rotation (minimum rotated bounding box):
#   python tools/autolabel.py \\
#       --image  R:/SAM/tools/frame_00000.jpg \\
#       --encoder C:/Users/User/xanylabeling_data/models/sam2_hiera_large-r20240801/sam2.1_hiera_large.encoder.onnx \\
#       --decoder C:/Users/User/xanylabeling_data/models/sam2_hiera_large-r20240801/sam2.1_hiera_large.decoder.onnx \\
#       --points 640,698 \\
#       --output-mode rotation
"""

import argparse
import json
import os
import sys

import cv2
import numpy as np
import onnxruntime
from autolabel_backends.sam2 import SegmentAnything2ONNX
from autolabel_backends.sam_onnx import SegmentAnythingONNX

# Detect best available ONNX provider for --device default
_AVAILABLE_PROVIDERS = onnxruntime.get_available_providers()
_DEFAULT_DEVICE = (
    "gpu" if "CUDAExecutionProvider" in _AVAILABLE_PROVIDERS else "cpu"
)


def parse_args():
    parser = argparse.ArgumentParser(
        description="Headless auto-labeling using SAM/SAM2 ONNX models"
    )
    parser.add_argument("--image", required=True, help="Input image path")
    parser.add_argument("--encoder", required=True, help="Encoder ONNX path")
    parser.add_argument("--decoder", required=True, help="Decoder ONNX path")
    parser.add_argument(
        "--points",
        action="append",
        default=[],
        metavar="x,y[,label]",
        help="Interactive point prompt. label=1 (add, default) or 0 (remove)",
    )
    parser.add_argument(
        "--rect",
        default=None,
        metavar="x1,y1,x2,y2",
        help="Rect prompt, can be combined with points",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Output JSON path. Default: <image_stem>.json",
    )
    parser.add_argument(
        "--output-mode",
        default="rectangle",
        choices=["polygon", "rectangle", "rotation"],
        help=(
            "Output shape type (default: rectangle): "
            "polygon=contour points, "
            "rectangle=axis-aligned bbox, "
            "rotation=minimum rotated bbox"
        ),
    )
    parser.add_argument(
        "--model-type",
        default="auto",
        choices=["auto", "segment_anything", "segment_anything_2"],
        help="Inference backend. auto detects from model filename",
    )
    parser.add_argument(
        "--device",
        default=_DEFAULT_DEVICE,
        choices=["cpu", "gpu"],
        help="SAM2 device selection",
    )
    parser.add_argument(
        "--label",
        default="object",
        help="Label name in output JSON",
    )
    parser.add_argument(
        "--epsilon",
        type=float,
        default=0.001,
        help="Contour approximation epsilon multiplier",
    )
    return parser.parse_args()


def build_marks(args):
    marks = []
    for pt in args.points:
        parts = [p.strip() for p in pt.split(",")]
        if len(parts) < 2:
            print(f"[WARN] Skipping invalid point '{pt}', expected x,y[,label]")
            continue
        x = float(parts[0])
        y = float(parts[1])
        label = int(parts[2]) if len(parts) >= 3 else 1
        label = 1 if label != 0 else 0
        marks.append({"type": "point", "data": [x, y], "label": label})

    if args.rect:
        parts = [p.strip() for p in args.rect.split(",")]
        if len(parts) == 4:
            x1, y1, x2, y2 = (float(p) for p in parts)
            marks.append({"type": "rectangle", "data": [x1, y1, x2, y2], "label": 1})
        else:
            print(
                f"[WARN] Skipping invalid rect '{args.rect}', expected x1,y1,x2,y2"
            )
    return marks


def detect_model_type(args):
    if args.model_type != "auto":
        return args.model_type
    name = (os.path.basename(args.encoder) + os.path.basename(args.decoder)).lower()
    if "sam2" in name or "hiera" in name:
        return "segment_anything_2"
    return "segment_anything"


def load_image_rgb(image_path):
    data = np.fromfile(image_path, dtype=np.uint8)
    bgr = cv2.imdecode(data, -1)
    if bgr is None:
        raise FileNotFoundError(f"Cannot read image: {image_path}")
    if len(bgr.shape) == 2:
        bgr = cv2.cvtColor(bgr, cv2.COLOR_GRAY2BGR)
    return cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)


def squeeze_mask(masks):
    mask = np.asarray(masks)
    while mask.ndim > 2:
        mask = mask[0]
    return mask


def get_approx_contours(mask, epsilon):
    m = mask.copy()
    m[m > 0.0] = 255
    m[m <= 0.0] = 0
    m = m.astype(np.uint8)
    contours, _ = cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)

    approx_contours = []
    for contour in contours:
        eps = epsilon * cv2.arcLength(contour, True)
        approx_contours.append(cv2.approxPolyDP(contour, eps, True))

    if len(approx_contours) > 1:
        image_size = m.shape[0] * m.shape[1]
        areas = [cv2.contourArea(c) for c in approx_contours]
        approx_contours = [
            c for c, a in zip(approx_contours, areas) if a < image_size * 0.9
        ]

    if len(approx_contours) > 1:
        areas = [cv2.contourArea(c) for c in approx_contours]
        avg_area = np.mean(areas)
        approx_contours = [
            c for c, a in zip(approx_contours, areas) if a > avg_area * 0.2
        ]

    return approx_contours


def contours_to_shapes(approx_contours, output_mode, label_name):
    shapes = []

    if output_mode == "polygon":
        for approx in approx_contours:
            points = approx.reshape(-1, 2).tolist()
            if len(points) < 3:
                continue
            points = [[int(x), int(y)] for x, y in points]
            points.append(points[0])
            shapes.append(
                {
                    "label": label_name,
                    "score": None,
                    "points": points,
                    "group_id": None,
                    "description": "",
                    "difficult": False,
                    "shape_type": "polygon",
                    "flags": {},
                    "attributes": {},
                }
            )
        return shapes

    if output_mode == "rectangle":
        x_min, y_min = 10**9, 10**9
        x_max, y_max = 0, 0
        for approx in approx_contours:
            points = approx.reshape(-1, 2).tolist()
            if len(points) < 3:
                continue
            for x, y in points:
                x_min = min(x_min, x)
                y_min = min(y_min, y)
                x_max = max(x_max, x)
                y_max = max(y_max, y)

        if x_min <= x_max and y_min <= y_max:
            shapes.append(
                {
                    "label": label_name,
                    "score": None,
                    "points": [
                        [int(x_min), int(y_min)],
                        [int(x_max), int(y_min)],
                        [int(x_max), int(y_max)],
                        [int(x_min), int(y_max)],
                    ],
                    "group_id": None,
                    "description": "",
                    "difficult": False,
                    "shape_type": "rectangle",
                    "flags": {},
                    "attributes": {},
                }
            )
        return shapes

    if output_mode == "rotation":
        if not approx_contours:
            return shapes
        contour = max(approx_contours, key=cv2.contourArea)
        rect = cv2.minAreaRect(contour)
        box = cv2.boxPoints(rect).astype(int).tolist()
        shapes.append(
            {
                "label": label_name,
                "score": None,
                "points": box,
                "group_id": None,
                "description": "",
                "difficult": False,
                "shape_type": "rotation",
                "flags": {},
                "attributes": {},
            }
        )
        return shapes

    return shapes


def to_labelme(shapes, image_path, image_rgb):
    h, w = image_rgb.shape[:2]
    return {
        "version": "5.0.0",
        "flags": {},
        "shapes": shapes,
        "imagePath": os.path.basename(image_path),
        "imageData": None,
        "imageHeight": h,
        "imageWidth": w,
    }


def run_prediction(args, image_rgb, marks):
    model_type = detect_model_type(args)
    print(f"[INFO] Using backend: {model_type}")

    if model_type == "segment_anything":
        model = SegmentAnythingONNX(args.encoder, args.decoder)
        embedding = model.encode(image_rgb)
        masks = model.predict_masks(embedding, marks)
        return squeeze_mask(masks)

    if model_type == "segment_anything_2":
        model = SegmentAnything2ONNX(args.encoder, args.decoder, args.device)
        embedding = model.encode(image_rgb)
        masks = model.predict_masks(embedding, marks)
        return squeeze_mask(masks)

    raise ValueError(f"Unsupported model type: {model_type}")


def default_output_path(image_path):
    return os.path.splitext(image_path)[0] + ".json"


def main():
    args = parse_args()

    if not os.path.isfile(args.image):
        print(f"[ERROR] Image not found: {args.image}")
        sys.exit(1)
    if not os.path.isfile(args.encoder):
        print(f"[ERROR] Encoder ONNX not found: {args.encoder}")
        sys.exit(1)
    if not os.path.isfile(args.decoder):
        print(f"[ERROR] Decoder ONNX not found: {args.decoder}")
        sys.exit(1)

    marks = build_marks(args)
    if not marks:
        print("[ERROR] No prompt marks. Use --points x,y or --rect x1,y1,x2,y2")
        sys.exit(1)

    print(f"[INFO] Loading image: {args.image}")
    image_rgb = load_image_rgb(args.image)

    print(f"[INFO] Running prompt-based segmentation with {len(marks)} mark(s)")
    mask = run_prediction(args, image_rgb, marks)

    approx_contours = get_approx_contours(mask, args.epsilon)
    shapes = contours_to_shapes(approx_contours, args.output_mode, args.label)

    if not shapes:
        print("[WARN] No shapes generated from predicted mask")
        sys.exit(0)

    output_path = args.output or default_output_path(args.image)
    payload = to_labelme(shapes, args.image, image_rgb)
    with open(output_path, "w", encoding="utf-8") as fp:
        json.dump(payload, fp, indent=2, ensure_ascii=False)

    print(f"[INFO] Saved {len(shapes)} shape(s) to: {output_path}")


if __name__ == "__main__":
    main()
