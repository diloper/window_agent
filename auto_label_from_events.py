import argparse
import bisect
import copy
import csv
import importlib.util
import json
import os
import re
import subprocess
import sys
import time
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from types import ModuleType
from typing import Any, Dict, List, Optional, Sequence, Tuple

import cv2
import numpy as np
from PIL import Image

import genai as genai_helper


_GOOGLE_SEARCH_RESULTS_MODULE: Optional[ModuleType] = None
_GOOGLE_SEARCH_RESULTS_LOAD_ERROR: Optional[Exception] = None

_ANALYZE_CLASSES_MODULE: Optional[ModuleType] = None
_ANALYZE_CLASSES_LOAD_ERROR: Optional[Exception] = None

_IMAGEHASH_MODULE: Optional[ModuleType] = None
_IMAGEHASH_LOAD_ERROR: Optional[Exception] = None


try:
    _script_path = Path(__file__).with_name("google-search-results.py")
    if not _script_path.exists():
        raise FileNotFoundError(f"google-search-results.py not found: {_script_path}")

    _spec = importlib.util.spec_from_file_location("google_search_results_script", _script_path)
    if _spec is None or _spec.loader is None:
        raise RuntimeError(f"Cannot load module spec from {_script_path}")

    _module = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(_module)
    _GOOGLE_SEARCH_RESULTS_MODULE = _module
except Exception as exc:
    _GOOGLE_SEARCH_RESULTS_LOAD_ERROR = exc

try:
    _analyze_path = Path(__file__).with_name("analyze_classes.py")
    if not _analyze_path.exists():
        raise FileNotFoundError(f"analyze_classes.py not found: {_analyze_path}")

    _spec = importlib.util.spec_from_file_location("analyze_classes_module", _analyze_path)
    if _spec is None or _spec.loader is None:
        raise RuntimeError(f"Cannot load module spec from {_analyze_path}")

    _module = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(_module)
    _ANALYZE_CLASSES_MODULE = _module
except Exception as exc:
    _ANALYZE_CLASSES_LOAD_ERROR = exc

try:
    import imagehash as _imagehash_module

    _IMAGEHASH_MODULE = _imagehash_module
except Exception as exc:
    _IMAGEHASH_LOAD_ERROR = exc


def search_images(api_key: str, query: str, num: int = 10) -> Dict[str, Any]:
    """Proxy text-query search through statically loaded google-search-results.py module."""
    if _GOOGLE_SEARCH_RESULTS_MODULE is None:
        raise RuntimeError(
            f"Failed to load google-search-results.py: {_GOOGLE_SEARCH_RESULTS_LOAD_ERROR}"
        )

    params = {
        "engine": "google_images",
        "q": query,
        "api_key": api_key,
        "num": num,
    }
    search = _GOOGLE_SEARCH_RESULTS_MODULE.GoogleSearch(params)
    return search.get_dict()


TIMESTAMP_PATTERN = re.compile(r"(\d{8}_\d{6})")
GENAI_MARKED_PROMPT = (
    "Please inspect the UI element inside the red rectangle in this marked image and "
    "identify the icon or control name. Give a brief answer only. If you cannot identify it, reply with 'NULL'."
)


@dataclass
class MouseEvent:
    event_id: int
    event_type: str
    x: int
    y: int
    timestamp_iso: str
    rel_seconds: float


@dataclass
class FrameSample:
    sample_id: int
    event_id: int
    event_type: str
    x: int
    y: int
    timestamp_iso: str
    frame_index: int
    image_path: Path
    annotation_path: Path
    marked_path: Optional[Path] = None
    status: str = "pending"
    error: str = ""
    inferred_label: str = ""
    crop_path: Optional[Path] = None
    crop_width: int = 0
    crop_height: int = 0
    search_label: str = ""
    search_status: str = ""
    similarity_hash: str = ""
    similarity_group_id: int = 0
    similarity_group_size: int = 0
    similarity_representative: int = 0
    similarity_sync_source: str = ""
    similarity_status: str = ""


class LocalClassProvider:
    """Interface for local class inference providers."""

    def score_candidates(
        self,
        image_path: Path,
        candidates: Sequence[str],
        context_text: str,
    ) -> Dict[str, float]:
        raise NotImplementedError


def load_dotenv_file(dotenv_path: Path) -> None:
    if not dotenv_path.exists():
        return
    for raw_line in dotenv_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


class SerpApiClassProvider(LocalClassProvider):
    """Score candidate labels using SerpApi image search results."""

    def __init__(self, api_key: str, query_template: str, num: int = 10):
        self.api_key = api_key
        self.query_template = query_template
        self.num = max(1, num)
        self.cache: Dict[str, Dict[str, Any]] = {}

    def _tokenize(self, text: str) -> List[str]:
        return [token for token in re.findall(r"[a-z0-9_]+", text.lower()) if token]

    def _query_for_candidate(self, candidate: str, context_text: str) -> str:
        try:
            return self.query_template.format(candidate=candidate, context=context_text)
        except Exception:
            return f"{candidate} {context_text}".strip()

    def _fetch(self, query: str) -> Dict[str, Any]:
        if query not in self.cache:
            self.cache[query] = search_images(self.api_key, query, self.num)
        return self.cache[query]

    def score_candidates(
        self,
        image_path: Path,
        candidates: Sequence[str],
        context_text: str,
    ) -> Dict[str, float]:
        scores: Dict[str, float] = {}
        for candidate in candidates:
            cl = candidate.strip().lower()
            if not cl:
                continue

            query = self._query_for_candidate(cl, context_text)
            try:
                data = self._fetch(query)
            except Exception:
                scores[candidate] = 0.0
                continue

            token_pool: List[str] = []
            for item in data.get("images_results", []):
                chunk = " ".join(
                    [
                        str(item.get("title", "")),
                        str(item.get("source", "")),
                        str(item.get("link", "")),
                    ]
                )
                token_pool.extend(self._tokenize(chunk))

            result_tokens = set(token_pool)
            candidate_tokens = [p for p in re.split(r"[^a-z0-9]+", cl) if p]
            if not candidate_tokens:
                scores[candidate] = 0.0
                continue

            overlap = sum(1 for token in candidate_tokens if token in result_tokens)
            scores[candidate] = overlap / len(candidate_tokens)
        return scores


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Auto-label video frames from events JSON and export LabelMe + YOLO preview outputs.",
    )
    parser.add_argument(
        "--events-json",
        required=False,
        default=None,
        help="Path to events_*.json recorded by screen_event_recorder.py. If not specified, will be inferred from --video filename.",
    )
    parser.add_argument(
        "--video",
        required=True,
        help="Path to screen_*.mp4 recorded by screen_event_recorder.py",
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Output preview directory (default: recordings/auto_labels_preview_<video filename>)",
    )
    parser.add_argument(
        "--window-before-ms",
        type=int,
        default=0,
        help="Sampling window before event in milliseconds",
    )
    parser.add_argument(
        "--window-after-ms",
        type=int,
        default=0,
        help="Sampling window after event in milliseconds",
    )
    parser.add_argument(
        "--max-frames-per-event",
        type=int,
        default=3,
        help="Max sampled frames per mouse event",
    )
    parser.add_argument(
        "--encoder",
        default=r"model/sam2_hiera_tiny_encoder.onnx",
        help="Encoder ONNX path for tools/autolabel.py",
    )
    parser.add_argument(
        "--decoder",
        default=r"model/sam2_hiera_tiny_decoder.onnx",
        help="Decoder ONNX path for tools/autolabel.py",
    )
    parser.add_argument(
        "--output-mode",
        default="rectangle",
        choices=["rectangle", "polygon", "rotation"],
        help="autolabel shape mode",
    )
    parser.add_argument(
        "--label-policy",
        default="genai-marked-direct",
        choices=["serpapi-topk", "fixed", "crop-search-direct", "genai-marked-direct"],
        help="Class assignment strategy (default: genai-marked-direct)",
    )
    parser.add_argument(
        "--fixed-label",
        default="object",
        help="Used when --label-policy fixed",
    )
    parser.add_argument(
        "--topk",
        type=int,
        default=3,
        help="Top-k candidates used in voting",
    )
    parser.add_argument(
        "--class-file",
        default="classes.txt",
        help="Candidate class list file for class provider",
    )
    parser.add_argument(
        "--serpapi-api-key",
        default="",
        help="SerpApi API key. If empty, read SERPAPI_API_KEY from env or .env",
    )
    parser.add_argument(
        "--dotenv-path",
        default=".env",
        help="Path to dotenv file used to load SERPAPI_API_KEY",
    )
    parser.add_argument(
        "--serpapi-num",
        type=int,
        default=10,
        help="Number of SerpApi image results per candidate query",
    )
    parser.add_argument(
        "--serpapi-query-template",
        default="{candidate} {context}",
        help="SerpApi query template. Supported placeholders: {candidate}, {context}",
    )
    parser.add_argument(
        "--button",
        default="left",
        choices=["left", "right", "middle", "any"],
        help="Mouse button filter",
    )
    parser.add_argument(
        "--autolabel-script",
        default="tools/autolabel.py",
        help="Path to autolabel.py",
    )
    parser.add_argument(
        "--device",
        default="",
        choices=["", "cpu", "gpu"],
        help="Optional autolabel device override",
    )
    parser.add_argument(
        "--skip-autolabel",
        action="store_true",
        help="Only sample frames and emit manifest without running autolabel",
    )
    parser.add_argument(
        "--genai-model",
        default=genai_helper.DEFAULT_MODEL,
        help="Gemini model used by --label-policy genai-marked-direct",
    )
    parser.add_argument(
        "--enable-class-mapping",
        action="store_true",
        help="Enable class name unification using mapping reference file",
    )
    parser.add_argument(
        "--disable-class-mapping",
        action="store_true",
        help="Disable auto class name unification even if mapping reference file exists",
    )
    parser.add_argument(
        "--class-mapping-file",
        default="class_mapping_reference.md",
        help="Path to class name mapping reference file (default: class_mapping_reference.md)",
    )
    parser.add_argument(
        "--auto-update-mapping",
        action="store_true",
        default=True,
        help="Auto-update mapping reference file after labeling (default: True)",
    )
    parser.add_argument(
        "--similarity-threshold",
        type=float,
        default=0.9,
        help="Minimum ImageHash similarity ratio for grouping similar images",
    )
    return parser.parse_args()


def extract_name_timestamp(path: Path) -> Optional[datetime]:
    match = TIMESTAMP_PATTERN.search(path.name)
    if not match:
        return None
    return datetime.strptime(match.group(1), "%Y%m%d_%H%M%S")


def ensure_matching_session(events_json: Path, video_path: Path) -> datetime:
    events_ts = extract_name_timestamp(events_json)
    video_ts = extract_name_timestamp(video_path)
    if not events_ts or not video_ts:
        raise ValueError("Cannot parse timestamp from events or video filename.")
    if events_ts != video_ts:
        raise ValueError(
            f"Timestamp mismatch: events={events_ts.strftime('%Y%m%d_%H%M%S')} video={video_ts.strftime('%Y%m%d_%H%M%S')}"
        )
    return video_ts


def parse_event_timestamp(raw: Any) -> float:
    try:
        return float(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Invalid event timestamp float: {raw}") from exc


def load_mouse_events(
    events_json: Path,
    button_filter: str,
) -> List[MouseEvent]:
    events: List[MouseEvent] = []
    next_id = 1
    with events_json.open("r", encoding="utf-8") as fp:
        for line_no, line in enumerate(fp, start=1):
            raw = line.strip()
            if not raw:
                continue
            if line_no == 1 and raw.startswith("["):
                raise ValueError(
                    "Legacy JSON array events format is not supported. Please use recorder output in NDJSON format."
                )

            try:
                item = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid NDJSON event at line {line_no}: {exc.msg}") from exc

            if not isinstance(item, dict):
                raise ValueError(f"Invalid NDJSON event at line {line_no}: expected object")

            t = item.get("type", "")
            if t not in {"mouse_press", "mouse_release"}:
                continue

            button = str(item.get("button", "")).lower()
            if button_filter != "any" and button != button_filter:
                continue

            if "x" not in item or "y" not in item or "timestamp" not in item:
                continue

            rel_seconds = parse_event_timestamp(item["timestamp"])
            if rel_seconds < 0:
                continue

            events.append(
                MouseEvent(
                    event_id=next_id,
                    event_type=t,
                    x=int(item["x"]),
                    y=int(item["y"]),
                    timestamp_iso=str(item["timestamp"]),
                    rel_seconds=rel_seconds,
                )
            )
            next_id += 1

    return events


def even_sample(start: int, end: int, max_count: int) -> List[int]:
    if end < start:
        return []
    values = list(range(start, end + 1))
    if len(values) <= max_count:
        return values

    if max_count <= 1:
        return [values[len(values) // 2]]

    result: List[int] = []
    last = len(values) - 1
    for i in range(max_count):
        idx = round(i * last / (max_count - 1))
        result.append(values[idx])
    return sorted(set(result))


def build_frame_plan(
    events: Sequence[MouseEvent],
    fps: float,
    frame_count: int,
    before_ms: int,
    after_ms: int,
    max_frames_per_event: int,
    frame_timestamps: Optional[Sequence[float]] = None,
) -> List[Tuple[MouseEvent, int]]:
    plan: List[Tuple[MouseEvent, int]] = []
    before_frames = max(0, int(round(before_ms * fps / 1000.0)))
    after_frames = max(0, int(round(after_ms * fps / 1000.0)))

    use_timeline = bool(frame_timestamps) and len(frame_timestamps) == frame_count

    def nearest_frame_index(ts: float) -> int:
        assert frame_timestamps is not None
        idx = bisect.bisect_left(frame_timestamps, ts)
        if idx <= 0:
            return 0
        if idx >= len(frame_timestamps):
            return len(frame_timestamps) - 1
        prev_i = idx - 1
        if abs(frame_timestamps[idx] - ts) < abs(ts - frame_timestamps[prev_i]):
            return idx
        return prev_i

    for event in events:
        if use_timeline:
            center = nearest_frame_index(event.rel_seconds)
            start_ts = max(0.0, event.rel_seconds - (before_ms / 1000.0))
            end_ts = event.rel_seconds + (after_ms / 1000.0)
            start = nearest_frame_index(start_ts)
            end = nearest_frame_index(end_ts)
            if end < start:
                start, end = end, start
        else:
            center = int(round(event.rel_seconds * fps))
            start = max(0, center - before_frames)
            end = min(frame_count - 1, center + after_frames)

        sampled = even_sample(start, end, max_frames_per_event)
        for idx in sampled:
            plan.append((event, idx))

    unique: Dict[Tuple[int, int], Tuple[MouseEvent, int]] = {}
    for event, frame_idx in plan:
        unique[(event.event_id, frame_idx)] = (event, frame_idx)

    return sorted(unique.values(), key=lambda p: (p[0].event_id, p[1]))


def infer_frames_timeline_path(events_json: Path, video_path: Path) -> Optional[Path]:
    events_ts = extract_name_timestamp(events_json)
    video_ts = extract_name_timestamp(video_path)
    ts = events_ts or video_ts
    if not ts:
        return None

    timeline_name = f"frames_{ts.strftime('%Y%m%d_%H%M%S')}.jsonl"
    candidate1 = events_json.parent / timeline_name
    candidate2 = video_path.parent / timeline_name
    if candidate1.exists():
        return candidate1
    if candidate2.exists():
        return candidate2
    return None


def load_frame_timestamps(frames_timeline_path: Path, expected_frame_count: int) -> Optional[List[float]]:
    timestamps: List[float] = []
    expected_index = 0

    with frames_timeline_path.open("r", encoding="utf-8") as fp:
        for line_no, line in enumerate(fp, start=1):
            raw = line.strip()
            if not raw:
                continue

            try:
                item = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid frame timeline at line {line_no}: {exc.msg}") from exc

            if not isinstance(item, dict):
                raise ValueError(f"Invalid frame timeline at line {line_no}: expected object")

            if "frame_index" not in item or "timestamp" not in item:
                raise ValueError(f"Invalid frame timeline at line {line_no}: missing frame_index or timestamp")

            frame_index = int(item["frame_index"])
            if frame_index != expected_index:
                raise ValueError(
                    f"Invalid frame timeline at line {line_no}: frame_index {frame_index} is not contiguous (expected {expected_index})"
                )

            timestamps.append(parse_event_timestamp(item["timestamp"]))
            expected_index += 1

    if not timestamps:
        return None

    if expected_frame_count > 0 and len(timestamps) != expected_frame_count:
        print(
            f"[WARN] Frame timeline size mismatch. timeline={len(timestamps)} video_frames={expected_frame_count}. Fallback to FPS mapping."
        )
        return None

    return timestamps


def extract_sample_frames(
    video_path: Path,
    plan: Sequence[Tuple[MouseEvent, int]],
    images_dir: Path,
    anno_dir: Path,
) -> List[FrameSample]:
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise RuntimeError(f"Cannot open video: {video_path}")

    samples: List[FrameSample] = []
    sample_id = 1

    try:
        for event, frame_idx in plan:
            cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
            ok, frame = cap.read()
            if not ok or frame is None:
                continue

            file_stem = (
                f"event_{event.event_id:04d}_{event.event_type}_"
                f"f{frame_idx:06d}_x{event.x}_y{event.y}"
            )
            image_path = images_dir / f"{file_stem}.jpg"
            annotation_path = anno_dir / f"{file_stem}.json"
            cv2.imwrite(str(image_path), frame)

            samples.append(
                FrameSample(
                    sample_id=sample_id,
                    event_id=event.event_id,
                    event_type=event.event_type,
                    x=event.x,
                    y=event.y,
                    timestamp_iso=event.timestamp_iso,
                    frame_index=frame_idx,
                    image_path=image_path,
                    annotation_path=annotation_path,
                )
            )
            sample_id += 1
    finally:
        cap.release()

    return samples


def run_autolabel_for_sample(
    sample: FrameSample,
    args: argparse.Namespace,
    python_executable: str,
) -> Tuple[bool, str]:
    cmd = [
        python_executable,
        str(Path(args.autolabel_script)),
        "--image",
        str(sample.image_path),
        "--encoder",
        str(args.encoder),
        "--decoder",
        str(args.decoder),
        "--points",
        f"{sample.x},{sample.y}",
        "--output-mode",
        args.output_mode,
        "--label",
        "object",
        "--output",
        str(sample.annotation_path),
    ]

    if args.device:
        cmd.extend(["--device", args.device])

    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        msg = proc.stderr.strip() or proc.stdout.strip() or "autolabel failed"
        return False, msg

    if not sample.annotation_path.exists():
        return False, "autolabel produced no annotation file"

    return True, ""


def load_special_mode_intervals(events_json: Path) -> List[Tuple[float, float]]:
    intervals: List[Tuple[float, float]] = []
    enter_ts: Optional[float] = None
    last_ts: float = 0.0

    with events_json.open("r", encoding="utf-8") as fp:
        for line in fp:
            raw = line.strip()
            if not raw:
                continue
            try:
                item = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if not isinstance(item, dict):
                continue

            if "timestamp" in item:
                try:
                    last_ts = max(last_ts, parse_event_timestamp(item["timestamp"]))
                except ValueError:
                    pass

            t = str(item.get("type", ""))
            if t == "special_mode_enter" and "timestamp" in item:
                try:
                    enter_ts = parse_event_timestamp(item["timestamp"])
                except ValueError:
                    continue
            elif t == "special_mode_exit" and enter_ts is not None and "timestamp" in item:
                try:
                    exit_ts = parse_event_timestamp(item["timestamp"])
                except ValueError:
                    continue
                start = min(enter_ts, exit_ts)
                end = max(enter_ts, exit_ts)
                intervals.append((start, end))
                enter_ts = None

    if enter_ts is not None:
        intervals.append((enter_ts, max(enter_ts, last_ts)))

    return intervals


def is_in_special_mode(timestamp: float, intervals: Sequence[Tuple[float, float]]) -> bool:
    for start, end in intervals:
        if start <= timestamp <= end:
            return True
    return False


def build_press_release_pairs(events: Sequence[MouseEvent]) -> List[Tuple[MouseEvent, MouseEvent]]:
    pairs: List[Tuple[MouseEvent, MouseEvent]] = []
    pending_press: Optional[MouseEvent] = None

    for event in events:
        if event.event_type == "mouse_press":
            pending_press = event
            continue
        if event.event_type == "mouse_release" and pending_press is not None:
            pairs.append((pending_press, event))
            pending_press = None

    return pairs


def save_marked_full_image_local(image_rgb: np.ndarray, shapes: Sequence[Dict[str, Any]], output_path: Path) -> None:
    image_bgr = cv2.cvtColor(image_rgb, cv2.COLOR_RGB2BGR)
    image_h, image_w = image_bgr.shape[:2]

    for shape in shapes:
        points = shape.get("points") or []
        if not points:
            continue

        xs = [int(round(p[0])) for p in points if len(p) >= 2]
        ys = [int(round(p[1])) for p in points if len(p) >= 2]
        if not xs or not ys:
            continue

        x1 = max(0, min(xs))
        y1 = max(0, min(ys))
        x2 = min(image_w - 1, max(xs))
        y2 = min(image_h - 1, max(ys))
        if x2 <= x1 or y2 <= y1:
            continue

        cv2.rectangle(
            image_bgr,
            (x1, y1),
            (x2, y2),
            color=(0, 0, 255),
            thickness=2,
            lineType=cv2.LINE_8,
        )

    cv2.imwrite(str(output_path), image_bgr)


def write_special_mode_sample(
    sample: FrameSample,
    press_event: MouseEvent,
    release_event: MouseEvent,
    marked_dir: Path,
) -> Tuple[bool, str]:
    try:
        image_bgr = load_image_bgr(sample.image_path)
    except Exception as exc:
        return False, f"cannot read sample image: {exc}"

    image_h, image_w = image_bgr.shape[:2]
    x1 = max(0, min(image_w - 1, int(press_event.x)))
    y1 = max(0, min(image_h - 1, int(press_event.y)))
    x2 = max(0, min(image_w - 1, int(release_event.x)))
    y2 = max(0, min(image_h - 1, int(release_event.y)))

    if x1 == x2:
        x2 = min(image_w - 1, x1 + 1)
    if y1 == y2:
        y2 = min(image_h - 1, y1 + 1)

    x_min, x_max = sorted((x1, x2))
    y_min, y_max = sorted((y1, y2))
    if x_max <= x_min or y_max <= y_min:
        return False, "invalid rectangle from mouse press/release"

    shape = {
        "label": "object",
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

    payload = {
        "version": "5.0.0",
        "flags": {},
        "shapes": [shape],
        "imagePath": sample.image_path.name,
        "imageData": None,
        "imageHeight": int(image_h),
        "imageWidth": int(image_w),
    }

    with sample.annotation_path.open("w", encoding="utf-8") as fp:
        json.dump(payload, fp, indent=2, ensure_ascii=False)

    marked_path = marked_dir / f"{sample.annotation_path.stem}_marked.jpg"
    image_rgb = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2RGB)
    save_marked_full_image_local(image_rgb, [shape], marked_path)
    sample.marked_path = marked_path
    return True, ""


def move_marked_preview(sample: FrameSample, marked_dir: Path) -> None:
    marked_src = sample.annotation_path.with_name(f"{sample.annotation_path.stem}_marked.jpg")
    if not marked_src.exists():
        sample.marked_path = None
        return

    marked_dst = marked_dir / marked_src.name
    if marked_dst.exists():
        marked_dst.unlink()
    marked_src.replace(marked_dst)
    sample.marked_path = marked_dst


def load_candidates(class_file: Path) -> List[str]:
    if not class_file.exists():
        return []

    candidates: List[str] = []
    with class_file.open("r", encoding="utf-8") as fp:
        for line in fp:
            label = line.strip()
            if not label:
                continue
            if label.startswith("#"):
                continue
            candidates.append(label)
    return candidates


def load_image_bgr(image_path: Path) -> np.ndarray:
    raw = np.fromfile(str(image_path), dtype=np.uint8)
    image = cv2.imdecode(raw, cv2.IMREAD_COLOR)
    if image is None:
        raise FileNotFoundError(f"Cannot read image: {image_path}")
    return image


def load_image_for_hash(image_path: Path) -> Image.Image:
    if _IMAGEHASH_MODULE is None:
        raise RuntimeError(f"Failed to load imagehash: {_IMAGEHASH_LOAD_ERROR}")

    with Image.open(image_path) as image:
        return image.convert("RGB")


def compute_image_hash(image_path: Path) -> str:
    if _IMAGEHASH_MODULE is None:
        raise RuntimeError(f"Failed to load imagehash: {_IMAGEHASH_LOAD_ERROR}")

    image = load_image_for_hash(image_path)
    return str(_IMAGEHASH_MODULE.phash(image))


def image_hash_similarity(hash_a: str, hash_b: str) -> float:
    if _IMAGEHASH_MODULE is None:
        raise RuntimeError(f"Failed to load imagehash: {_IMAGEHASH_LOAD_ERROR}")

    parsed_a = _IMAGEHASH_MODULE.hex_to_hash(hash_a)
    parsed_b = _IMAGEHASH_MODULE.hex_to_hash(hash_b)
    bit_count = max(1, parsed_a.hash.size)
    distance = parsed_a - parsed_b
    return max(0.0, 1.0 - (distance / bit_count))


def read_annotation_labels(annotation_path: Path) -> List[str]:
    with annotation_path.open("r", encoding="utf-8") as fp:
        payload = json.load(fp)

    labels: List[str] = []
    for shape in payload.get("shapes", []):
        labels.append(str(shape.get("label", "object")))
    return labels


def shapes_overlap(shape1: Dict[str, Any], shape2: Dict[str, Any], iou_threshold: float = 0.1) -> bool:
    """Check if two shapes overlap spatially based on bounding box IoU.
    
    Args:
        shape1: First shape with 'points' field
        shape2: Second shape with 'points' field
        iou_threshold: Minimum IoU to consider as overlapping (default 0.1)
    
    Returns:
        True if shapes overlap above threshold, False otherwise
    """
    points1 = shape1.get("points", [])
    points2 = shape2.get("points", [])
    
    if not points1 or not points2:
        return False
    
    # Get bounding boxes
    xs1 = [float(p[0]) for p in points1]
    ys1 = [float(p[1]) for p in points1]
    xs2 = [float(p[0]) for p in points2]
    ys2 = [float(p[1]) for p in points2]
    
    x1_min, x1_max = min(xs1), max(xs1)
    y1_min, y1_max = min(ys1), max(ys1)
    x2_min, x2_max = min(xs2), max(xs2)
    y2_min, y2_max = min(ys2), max(ys2)
    
    # Calculate intersection
    x_left = max(x1_min, x2_min)
    y_top = max(y1_min, y2_min)
    x_right = min(x1_max, x2_max)
    y_bottom = min(y1_max, y2_max)
    
    if x_right < x_left or y_bottom < y_top:
        return False  # No intersection
    
    intersection_area = (x_right - x_left) * (y_bottom - y_top)
    
    # Calculate union
    box1_area = (x1_max - x1_min) * (y1_max - y1_min)
    box2_area = (x2_max - x2_min) * (y2_max - y2_min)
    union_area = box1_area + box2_area - intersection_area
    
    if union_area <= 0:
        return False
    
    iou = intersection_area / union_area
    return iou >= iou_threshold


def merge_annotation_labels(annotation_path: Path, label_templates: Dict[str, Dict[str, Any]]) -> Tuple[List[str], List[str], List[str], int]:
    """Merge labels from template shapes, avoiding spatial overlap with existing shapes.
    
    Args:
        annotation_path: Path to the annotation JSON file
        label_templates: Dict mapping label names to shape templates
    
    Returns:
        Tuple of (labels_before, labels_after, labels_added, added_count)
    """
    with annotation_path.open("r", encoding="utf-8") as fp:
        payload = json.load(fp)

    shapes = payload.get("shapes", [])
    before = [str(shape.get("label", "object")) for shape in shapes]
    if not shapes:
        return before, before, [], 0

    added_labels: List[str] = []
    added_shape_count = 0

    for label, template_shape in label_templates.items():
        normalized_label = str(label).strip()
        if not normalized_label:
            continue

        # Check if template shape overlaps with any existing shape
        overlaps_existing = False
        for existing_shape in shapes:
            if shapes_overlap(existing_shape, template_shape):
                overlaps_existing = True
                break
        
        if overlaps_existing:
            continue  # Skip this label if it overlaps with existing annotations

        # No spatial overlap, safe to add
        new_shape = copy.deepcopy(template_shape)
        new_shape["label"] = normalized_label
        shapes.append(new_shape)
        added_labels.append(normalized_label)
        added_shape_count += 1

    if added_shape_count > 0:
        with annotation_path.open("w", encoding="utf-8") as fp:
            json.dump(payload, fp, indent=2, ensure_ascii=False)

    after = [str(shape.get("label", "object")) for shape in shapes]
    return before, after, added_labels, added_shape_count


def build_similarity_clusters(
    samples: Sequence[FrameSample],
    threshold: float,
) -> List[Dict[str, Any]]:
    if _IMAGEHASH_MODULE is None:
        raise RuntimeError(f"Failed to load imagehash: {_IMAGEHASH_LOAD_ERROR}")

    hash_entries: List[Dict[str, Any]] = []
    for sample in samples:
        if not sample.image_path.exists():
            sample.similarity_status = "missing_image"
            continue
        try:
            image_hash = compute_image_hash(sample.image_path)
        except Exception as exc:
            sample.similarity_status = f"hash_failed: {exc}"
            continue

        sample.similarity_hash = image_hash
        sample.similarity_status = "hashed"
        hash_entries.append({"sample": sample, "hash": image_hash})

    if not hash_entries:
        return []

    parent = list(range(len(hash_entries)))

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def union(left: int, right: int) -> None:
        root_left = find(left)
        root_right = find(right)
        if root_left != root_right:
            parent[root_right] = root_left

    for left in range(len(hash_entries)):
        for right in range(left + 1, len(hash_entries)):
            similarity = image_hash_similarity(hash_entries[left]["hash"], hash_entries[right]["hash"])
            if similarity >= threshold:
                union(left, right)

    grouped: Dict[int, List[Dict[str, Any]]] = defaultdict(list)
    for index, entry in enumerate(hash_entries):
        grouped[find(index)].append(entry)

    clusters: List[Dict[str, Any]] = []
    sorted_groups = sorted(
        grouped.values(),
        key=lambda group: min(item["sample"].sample_id for item in group),
    )
    for group_id, group_entries in enumerate(sorted_groups, start=1):
        representative_entry = min(
            group_entries,
            key=lambda item: (item["sample"].status != "ok", item["sample"].sample_id),
        )
        representative_sample = representative_entry["sample"]

        cluster_label_templates: Dict[str, Dict[str, Any]] = {}
        canonical_labels: List[str] = []
        for entry in group_entries:
            sample = entry["sample"]
            if not sample.annotation_path.exists():
                continue
            try:
                with sample.annotation_path.open("r", encoding="utf-8") as fp:
                    payload = json.load(fp)
            except Exception:
                continue

            for shape in payload.get("shapes", []):
                label = str(shape.get("label", "object")).strip()
                if not label:
                    continue
                if label not in cluster_label_templates:
                    cluster_label_templates[label] = shape
                    canonical_labels.append(label)

        cluster_members: List[Dict[str, Any]] = []
        for entry in group_entries:
            sample = entry["sample"]
            similarity_to_rep = image_hash_similarity(representative_entry["hash"], entry["hash"])
            sample.similarity_group_id = group_id
            sample.similarity_group_size = len(group_entries)
            sample.similarity_representative = representative_sample.sample_id
            sample.similarity_status = sample.similarity_status or "clustered"
            cluster_members.append(
                {
                    "sample_id": sample.sample_id,
                    "event_id": sample.event_id,
                    "image_path": str(sample.image_path),
                    "annotation_path": str(sample.annotation_path),
                    "hash": entry["hash"],
                    "similarity_to_representative": round(similarity_to_rep, 6),
                    "labels_before": read_annotation_labels(sample.annotation_path) if sample.annotation_path.exists() else [],
                    "labels_after": [],
                    "labels_added": [],
                    "labels_added_count": 0,
                    "sync_applied": False,
                    "sync_source_sample_id": representative_sample.sample_id,
                }
            )

        if cluster_label_templates:
            for member in cluster_members:
                member_sample = next(sample for sample in samples if sample.sample_id == member["sample_id"])
                if member_sample.annotation_path.exists():
                    before_labels, after_labels, labels_added, added_count = merge_annotation_labels(
                        member_sample.annotation_path,
                        cluster_label_templates,
                    )
                    member["labels_before"] = before_labels
                    member["labels_after"] = after_labels
                    member["labels_added"] = labels_added
                    member["labels_added_count"] = added_count
                    member["sync_applied"] = added_count > 0
                    member_sample.similarity_sync_source = representative_sample.image_path.name
                else:
                    member["labels_after"] = []
                    member["labels_added"] = []
                    member["labels_added_count"] = 0
        else:
            for member in cluster_members:
                member["labels_after"] = member["labels_before"]
                member["labels_added"] = []
                member["labels_added_count"] = 0

        clusters.append(
            {
                "group_id": group_id,
                "group_size": len(group_entries),
                "representative_sample_id": representative_sample.sample_id,
                "representative_image": str(representative_sample.image_path),
                "representative_annotation": str(representative_sample.annotation_path),
                "representative_hash": representative_entry["hash"],
                "canonical_labels": canonical_labels,
                "members": cluster_members,
            }
        )

    return clusters


def write_similarity_report(clusters: Sequence[Dict[str, Any]], reports_dir: Path, threshold: float) -> Tuple[Path, Path, int]:
    json_path = reports_dir / "similarity_groups.json"
    csv_path = reports_dir / "similarity_groups.csv"

    summary = {
        "threshold": threshold,
        "hash_algorithm": "phash",
        "group_count": len(clusters),
        "synced_annotation_count": sum(
            1 for cluster in clusters for member in cluster["members"] if member.get("sync_applied")
        ),
        "clusters": clusters,
    }
    with json_path.open("w", encoding="utf-8") as fp:
        json.dump(summary, fp, indent=2, ensure_ascii=False)

    csv_fields = [
        "group_id",
        "group_size",
        "representative_sample_id",
        "sample_id",
        "event_id",
        "image_path",
        "annotation_path",
        "hash",
        "similarity_to_representative",
        "sync_applied",
        "sync_source_sample_id",
        "labels_before",
        "labels_after",
        "labels_added",
        "labels_added_count",
    ]
    with csv_path.open("w", encoding="utf-8", newline="") as fp:
        writer = csv.DictWriter(fp, fieldnames=csv_fields)
        writer.writeheader()
        for cluster in clusters:
            for member in cluster["members"]:
                writer.writerow(
                    {
                        "group_id": cluster["group_id"],
                        "group_size": cluster["group_size"],
                        "representative_sample_id": cluster["representative_sample_id"],
                        "sample_id": member["sample_id"],
                        "event_id": member["event_id"],
                        "image_path": member["image_path"],
                        "annotation_path": member["annotation_path"],
                        "hash": member["hash"],
                        "similarity_to_representative": member["similarity_to_representative"],
                        "sync_applied": member["sync_applied"],
                        "sync_source_sample_id": member["sync_source_sample_id"],
                        "labels_before": " | ".join(member["labels_before"]),
                        "labels_after": " | ".join(member["labels_after"]),
                        "labels_added": " | ".join(member.get("labels_added", [])),
                        "labels_added_count": member.get("labels_added_count", 0),
                    }
                )

    return json_path, csv_path, summary["synced_annotation_count"]


def read_first_shape_bbox(annotation_path: Path) -> Optional[Tuple[int, int, int, int]]:
    with annotation_path.open("r", encoding="utf-8") as fp:
        payload = json.load(fp)

    shapes = payload.get("shapes", [])
    if not shapes:
        return None

    points = shapes[0].get("points", [])
    if not points:
        return None

    xs = [float(point[0]) for point in points]
    ys = [float(point[1]) for point in points]
    x_min = int(max(0, min(xs)))
    y_min = int(max(0, min(ys)))
    x_max = int(max(xs))
    y_max = int(max(ys))
    if x_max <= x_min or y_max <= y_min:
        return None
    return x_min, y_min, x_max, y_max


def crop_image_from_annotation(sample: FrameSample) -> np.ndarray:
    bbox = read_first_shape_bbox(sample.annotation_path)
    if bbox is None:
        raise ValueError(f"No valid shape bbox found in annotation: {sample.annotation_path}")

    image = load_image_bgr(sample.image_path)
    height, width = image.shape[:2]
    x_min, y_min, x_max, y_max = bbox
    x_min = max(0, min(x_min, width - 1))
    y_min = max(0, min(y_min, height - 1))
    x_max = max(x_min + 1, min(x_max, width))
    y_max = max(y_min + 1, min(y_max, height))

    crop = image[y_min:y_max, x_min:x_max]
    if crop.size == 0:
        raise ValueError(f"Empty crop extracted from annotation: {sample.annotation_path}")
    return crop


def resize_image_to_fit(image: np.ndarray, max_width: int = 640, max_height: int = 480) -> np.ndarray:
    height, width = image.shape[:2]
    if width <= 0 or height <= 0:
        raise ValueError("Invalid crop dimensions")

    scale = min(max_width / width, max_height / height)
    if scale >= 1.0:
        return image

    resized_width = max(1, int(round(width * scale)))
    resized_height = max(1, int(round(height * scale)))
    return cv2.resize(image, (resized_width, resized_height), interpolation=cv2.INTER_LINEAR)


def write_image_bgr(image_path: Path, image: np.ndarray) -> None:
    cv2.imwrite(str(image_path), image)


def parse_class_mapping_reference(reference_file: Path) -> Dict[str, Dict]:
    """Parse existing class name mappings from reference file.
    
    Returns dict with structure:
    {
        "Confirm button": {
            "original_names": ["確定 button", "確定", ...],
            "semantic_analysis": "確認操作的按鈕",
            "variant_count": 5
        },
        ...
    }
    """
    if not reference_file.exists():
        return {}
    
    content = reference_file.read_text(encoding="utf-8")
    lines = content.split('\n')
    mappings = {}
    
    in_table = False
    for line in lines:
        stripped = line.strip()
        
        # Skip header and separator rows
        if '|' in stripped and (':---' in stripped or '原始類別名稱' in stripped):
            in_table = True
            continue
        
        if in_table and '|' in stripped and not stripped.startswith('---'):
            parts = [p.strip() for p in stripped.split('|')]
            if len(parts) >= 5:  # | original | semantic | unified | count |
                original_names_str = parts[1]
                semantic_analysis = parts[2]
                unified_name = parts[3]
                try:
                    variant_count = int(parts[4])
                except (ValueError, IndexError):
                    variant_count = 1
                
                if unified_name and unified_name != "建議統一名稱":
                    mappings[unified_name] = {
                        "original_names": [n.strip() for n in original_names_str.split(',')],
                        "semantic_analysis": semantic_analysis,
                        "variant_count": variant_count
                    }
    
    return mappings


def build_original_to_unified_mapping(mappings: Dict[str, Dict]) -> Dict[str, str]:
    """Build reverse index: original_name -> unified_name for fast lookup."""
    reverse_map = {}
    for unified_name, data in mappings.items():
        for original_name in data["original_names"]:
            # Case-insensitive mapping
            reverse_map[original_name.lower()] = unified_name
    return reverse_map


def apply_class_mapping(
    label: str,
    original_to_unified: Dict[str, str],
    fallback: Optional[str] = None,
) -> str:
    """Apply class name mapping to unify label names.
    
    Args:
        label: Original label name
        original_to_unified: Mapping dict from original name to unified name
        fallback: Fallback label if not found (default: return original label)
    
    Returns:
        Unified label name or fallback/original if not found
    """
    if not label or not original_to_unified:
        return label or (fallback or "")
    
    # Try exact case-insensitive match
    unified = original_to_unified.get(label.lower())
    if unified:
        return unified
    
    # Return original or fallback
    return fallback if fallback is not None else label


def sanitize_label_name(raw_label: str, fallback_label: str) -> str:
    label = re.sub(r"\s+", " ", (raw_label or "").strip())
    label = re.sub(r"[\r\n\t]", " ", label)
    label = label.strip(" .")
    return label or fallback_label


def infer_sample_label_from_crop(
    sample: FrameSample,
    crops_dir: Path,
    api_key: str,
    fallback_label: str,
) -> str:
    if _GOOGLE_SEARCH_RESULTS_MODULE is None:
        raise RuntimeError(
            f"Failed to load google-search-results.py: {_GOOGLE_SEARCH_RESULTS_LOAD_ERROR}"
        )

    crop = crop_image_from_annotation(sample)
    resized = resize_image_to_fit(crop)
    crop_path = crops_dir / f"{sample.image_path.stem}_crop.jpg"
    write_image_bgr(crop_path, resized)

    sample.crop_path = crop_path
    sample.crop_width = int(resized.shape[1])
    sample.crop_height = int(resized.shape[0])

    analysis = _GOOGLE_SEARCH_RESULTS_MODULE.analyze_local_image_with_google_lens(
        crop_path,
        api_key,
        validate_ocr=False,
    )
    top_repetition_result = analysis.get("top_repetition_result", {})
    search_label = sanitize_label_name(top_repetition_result.get("result", ""), fallback_label)

    sample.search_label = search_label
    sample.search_status = analysis.get("reason", "ok")
    return search_label


def infer_sample_label_from_marked_with_genai(
    sample: FrameSample,
    fallback_label: str,
    model: str,
    api_key: str,
) -> str:
    marked_path = sample.marked_path
    if marked_path is None or not marked_path.exists():
        raise FileNotFoundError("Marked image not found for genai analysis")

    raw_response = genai_helper.analyze_image_file(
        marked_path,
        prompt=GENAI_MARKED_PROMPT,
        model=model,
        api_key=api_key,
    )
    response = sanitize_label_name(raw_response, "")
    if not response or response.upper() == "NULL":
        sample.search_label = fallback_label
        sample.search_status = "genai_null"
        return fallback_label

    sample.search_label = response
    sample.search_status = "genai_marked_ok"
    return response


def pick_topk(scores: Dict[str, float], k: int) -> List[Tuple[str, float]]:
    return sorted(scores.items(), key=lambda x: (-x[1], x[0]))[: max(1, k)]


def vote_event_labels(
    samples: Sequence[FrameSample],
    provider: LocalClassProvider,
    candidates: Sequence[str],
    topk: int,
    fallback_label: str,
    video_name: str,
) -> Dict[int, str]:
    votes: Dict[int, Dict[str, float]] = defaultdict(lambda: defaultdict(float))

    for sample in samples:
        if sample.status != "ok":
            continue
        context = f"{video_name} {sample.event_type} x{sample.x} y{sample.y}"
        scores = provider.score_candidates(sample.image_path, candidates, context)
        ranked = pick_topk(scores, topk)
        for label, score in ranked:
            votes[sample.event_id][label] += score

    decided: Dict[int, str] = {}
    for event_id in sorted({s.event_id for s in samples}):
        event_votes = votes.get(event_id, {})
        if not event_votes:
            decided[event_id] = fallback_label
            continue
        label, score = sorted(event_votes.items(), key=lambda x: (-x[1], x[0]))[0]
        decided[event_id] = label if score > 0 else fallback_label

    return decided


def relabel_annotation(annotation_path: Path, label: str) -> int:
    with annotation_path.open("r", encoding="utf-8") as fp:
        payload = json.load(fp)

    shapes = payload.get("shapes", [])
    for shape in shapes:
        shape["label"] = label

    with annotation_path.open("w", encoding="utf-8") as fp:
        json.dump(payload, fp, indent=2, ensure_ascii=False)

    return len(shapes)


def normalize_box(
    x1: float,
    y1: float,
    x2: float,
    y2: float,
    w: float,
    h: float,
) -> Tuple[float, float, float, float]:
    x_min = max(0.0, min(x1, x2))
    y_min = max(0.0, min(y1, y2))
    x_max = min(w, max(x1, x2))
    y_max = min(h, max(y1, y2))

    cx = ((x_min + x_max) / 2.0) / w
    cy = ((y_min + y_max) / 2.0) / h
    bw = (x_max - x_min) / w
    bh = (y_max - y_min) / h

    return cx, cy, bw, bh


def export_yolo(
    samples: Sequence[FrameSample],
    labels_dir: Path,
    class_ids: Dict[str, int],
) -> int:
    exported = 0
    for sample in samples:
        txt_path = labels_dir / f"{sample.image_path.stem}.txt"

        if sample.status != "ok" or not sample.annotation_path.exists():
            txt_path.write_text("", encoding="utf-8")
            continue

        with sample.annotation_path.open("r", encoding="utf-8") as fp:
            payload = json.load(fp)

        w = float(payload.get("imageWidth", 0))
        h = float(payload.get("imageHeight", 0))
        if w <= 0 or h <= 0:
            txt_path.write_text("", encoding="utf-8")
            continue

        lines: List[str] = []
        for shape in payload.get("shapes", []):
            label = str(shape.get("label", "object"))
            class_id = class_ids.get(label)
            if class_id is None:
                continue

            points = shape.get("points", [])
            if not points:
                continue

            xs = [float(p[0]) for p in points]
            ys = [float(p[1]) for p in points]
            cx, cy, bw, bh = normalize_box(min(xs), min(ys), max(xs), max(ys), w, h)
            lines.append(f"{class_id} {cx:.6f} {cy:.6f} {bw:.6f} {bh:.6f}")

        txt_path.write_text("\n".join(lines), encoding="utf-8")
        if lines:
            exported += 1

    return exported


def write_manifest(samples: Sequence[FrameSample], path: Path) -> None:
    fieldnames = [
        "sample_id",
        "event_id",
        "event_type",
        "timestamp_iso",
        "frame_index",
        "x",
        "y",
        "image_path",
        "annotation_path",
        "marked_path",
        "crop_path",
        "crop_width",
        "crop_height",
        "search_label",
        "search_status",
        "inferred_label",
        "similarity_hash",
        "similarity_group_id",
        "similarity_group_size",
        "similarity_representative",
        "similarity_sync_source",
        "similarity_status",
        "status",
        "error",
    ]
    with path.open("w", encoding="utf-8", newline="") as fp:
        writer = csv.DictWriter(fp, fieldnames=fieldnames)
        writer.writeheader()
        for s in samples:
            writer.writerow(
                {
                    "sample_id": s.sample_id,
                    "event_id": s.event_id,
                    "event_type": s.event_type,
                    "timestamp_iso": s.timestamp_iso,
                    "frame_index": s.frame_index,
                    "x": s.x,
                    "y": s.y,
                    "image_path": str(s.image_path),
                    "annotation_path": str(s.annotation_path),
                    "marked_path": str(s.marked_path) if s.marked_path else "",
                    "crop_path": str(s.crop_path) if s.crop_path else "",
                    "crop_width": s.crop_width,
                    "crop_height": s.crop_height,
                    "search_label": s.search_label,
                    "search_status": s.search_status,
                    "inferred_label": s.inferred_label,
                    "similarity_hash": s.similarity_hash,
                    "similarity_group_id": s.similarity_group_id,
                    "similarity_group_size": s.similarity_group_size,
                    "similarity_representative": s.similarity_representative,
                    "similarity_sync_source": s.similarity_sync_source,
                    "similarity_status": s.similarity_status,
                    "status": s.status,
                    "error": s.error,
                }
            )


def main() -> int:
    args = parse_args()

    # Auto-enable class mapping if reference file exists (unless explicitly disabled)
    mapping_file = Path(args.class_mapping_file)
    if not args.enable_class_mapping and not args.disable_class_mapping and mapping_file.exists():
        print(f"[INFO] Auto-enabling class mapping (found {mapping_file})")
        args.enable_class_mapping = True
    elif args.disable_class_mapping:
        args.enable_class_mapping = False
        if mapping_file.exists():
            print(f"[INFO] Class mapping disabled by --disable-class-mapping flag")

    load_dotenv_file(Path(args.dotenv_path))

    video_path = Path(args.video)
    # Infer events_json if not provided
    if args.events_json is None:
        # Try to extract timestamp from video filename
        m = re.match(r"screen_(\d{8}_\d{6})\\.mp4$|screen_(\d{8}_\d{6})\.mp4$", video_path.name)
        timestamp = None
        if m:
            timestamp = m.group(1) or m.group(2)
        if timestamp:
            # Prefer events file in same dir as video, else try recordings/
            candidate1 = video_path.parent / f"events_{timestamp}.json"
            candidate2 = Path("recordings") / f"events_{timestamp}.json"
            if candidate1.exists():
                events_json = candidate1
            elif candidate2.exists():
                events_json = candidate2
            else:
                print(f"[ERROR] Could not find events JSON file for timestamp {timestamp}. Tried: {candidate1}, {candidate2}")
                return 1
            print(f"[auto] Using events JSON: {events_json}")
        else:
            print(f"[ERROR] Could not infer events JSON filename from video: {video_path.name}")
            return 1
    else:
        events_json = Path(args.events_json)

    if args.output_dir:
        output_dir = Path(args.output_dir)
    else:
        video_stem = video_path.stem.strip() or "video"
        output_dir = Path("recordings") / f"auto_labels_preview_{video_stem}"
    class_file = Path(args.class_file)

    if not events_json.exists():
        print(f"[ERROR] Events JSON not found: {events_json}")
        return 1
    if not video_path.exists():
        print(f"[ERROR] Video file not found: {video_path}")
        return 1

    try:
        ensure_matching_session(events_json, video_path)
    except Exception as exc:
        print(f"[ERROR] {exc}")
        return 1

    output_dir.mkdir(parents=True, exist_ok=True)
    images_dir = output_dir / "images"
    anno_dir = output_dir / "annotations_labelme"
    marked_dir = output_dir / "marked"
    crops_dir = output_dir / "crops"
    labels_dir = output_dir / "labels"
    reports_dir = output_dir / "reports"
    images_dir.mkdir(parents=True, exist_ok=True)
    anno_dir.mkdir(parents=True, exist_ok=True)
    marked_dir.mkdir(parents=True, exist_ok=True)
    crops_dir.mkdir(parents=True, exist_ok=True)
    labels_dir.mkdir(parents=True, exist_ok=True)
    reports_dir.mkdir(parents=True, exist_ok=True)

    events = load_mouse_events(events_json, args.button)
    if not events:
        print("[ERROR] No mouse events found after filtering.")
        return 1

    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        print(f"[ERROR] Cannot open video: {video_path}")
        return 1
    fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)
    frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    cap.release()

    if fps <= 0 or frame_count <= 0:
        print(f"[ERROR] Invalid video metadata. fps={fps} frame_count={frame_count}")
        return 1

    frame_timestamps: Optional[List[float]] = None
    frames_timeline_path = infer_frames_timeline_path(events_json, video_path)
    if frames_timeline_path is not None:
        try:
            frame_timestamps = load_frame_timestamps(frames_timeline_path, frame_count)
            if frame_timestamps:
                print(f"[info] Using frame timeline for precise alignment: {frames_timeline_path}")
        except Exception as exc:
            print(f"[WARN] Failed to load frame timeline: {exc}. Fallback to FPS mapping.")

    plan = build_frame_plan(
        events=events,
        fps=fps,
        frame_count=frame_count,
        before_ms=args.window_before_ms,
        after_ms=args.window_after_ms,
        max_frames_per_event=max(1, args.max_frames_per_event),
        frame_timestamps=frame_timestamps,
    )
    if not plan:
        print("[ERROR] No frame sampling plan generated.")
        return 1

    samples = extract_sample_frames(video_path, plan, images_dir, anno_dir)
    if not samples:
        print("[ERROR] No frames extracted from the video.")
        return 1

    special_mode_intervals = load_special_mode_intervals(events_json)
    press_release_pairs = build_press_release_pairs(events)
    pair_by_event_id: Dict[int, Tuple[MouseEvent, MouseEvent]] = {}
    for press_event, release_event in press_release_pairs:
        pair_by_event_id[press_event.event_id] = (press_event, release_event)
        pair_by_event_id[release_event.event_id] = (press_event, release_event)

    failures = 0
    if args.skip_autolabel:
        for sample in samples:
            sample.status = "skipped"
            sample.error = "autolabel skipped"
    else:
        if not Path(args.autolabel_script).exists():
            print(f"[ERROR] autolabel script not found: {args.autolabel_script}")
            return 1
        if not Path(args.encoder).exists() or not Path(args.decoder).exists():
            print("[ERROR] ONNX model files not found. Check --encoder / --decoder.")
            return 1

        for sample in samples:
            sample_ts = parse_event_timestamp(sample.timestamp_iso)
            if is_in_special_mode(sample_ts, special_mode_intervals):
                pair = pair_by_event_id.get(sample.event_id)
                if pair is None:
                    sample.status = "failed"
                    sample.error = "special_mode sample has no mouse press/release pair"
                    failures += 1
                    continue

                ok, err = write_special_mode_sample(
                    sample,
                    press_event=pair[0],
                    release_event=pair[1],
                    marked_dir=marked_dir,
                )
            else:
                ok, err = run_autolabel_for_sample(sample, args, sys.executable)

            if ok:
                sample.status = "ok"
                if not is_in_special_mode(sample_ts, special_mode_intervals):
                    move_marked_preview(sample, marked_dir)
            else:
                sample.status = "failed"
                sample.error = err
                failures += 1

    fallback_label = args.fixed_label or "object"
    serpapi_key = args.serpapi_api_key or os.getenv("SERPAPI_API_KEY", "")
    genai_api_key = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY", "")

    if args.label_policy == "fixed":
        event_labels = {event.event_id: fallback_label for event in events}
    elif args.label_policy == "crop-search-direct":
        event_labels = {}
        if not serpapi_key:
            print("[WARN] SERPAPI_API_KEY is missing; fallback to fixed label policy")
            for sample in samples:
                sample.search_status = "missing_api_key"
        else:
            for sample in samples:
                if sample.status != "ok":
                    continue
                try:
                    sample.search_label = infer_sample_label_from_crop(
                        sample,
                        crops_dir,
                        serpapi_key,
                        fallback_label,
                    )
                    sample.search_status = sample.search_status or "ok"
                except Exception as exc:
                    sample.search_status = "crop_search_failed"
                    sample.error = str(exc)
                    sample.search_label = fallback_label
    elif args.label_policy == "genai-marked-direct":
        event_labels = {}
        if not genai_api_key:
            print("[WARN] GOOGLE_API_KEY or GEMINI_API_KEY is missing; fallback to fixed label policy")
            for sample in samples:
                sample.search_status = "missing_genai_api_key"
        else:
            for sample in samples:
                if sample.status != "ok":
                    continue
                try:
                    sample.search_label = infer_sample_label_from_marked_with_genai(
                        sample,
                        fallback_label,
                        args.genai_model,
                        genai_api_key,
                    )
                    sample.search_status = sample.search_status or "genai_marked_ok"
                except FileNotFoundError as exc:
                    sample.search_status = "missing_marked_image"
                    sample.error = str(exc)
                    sample.search_label = fallback_label
                except Exception as exc:
                    sample.search_status = "genai_failed"
                    sample.error = str(exc)
                    sample.search_label = fallback_label
    else:
        candidates = load_candidates(class_file)
        if not candidates:
            candidates = [fallback_label]

        if not serpapi_key:
            print("[WARN] SERPAPI_API_KEY is missing; fallback to fixed label policy")
            event_labels = {event.event_id: fallback_label for event in events}
        else:
            provider = SerpApiClassProvider(
                api_key=serpapi_key,
                query_template=args.serpapi_query_template,
                num=args.serpapi_num,
            )
            event_labels = vote_event_labels(
                samples=samples,
                provider=provider,
                candidates=candidates,
                topk=max(1, args.topk),
                fallback_label=fallback_label,
                video_name=video_path.stem,
            )

    for sample in samples:
        if args.label_policy in {"crop-search-direct", "genai-marked-direct"}:
            label = sample.search_label or fallback_label
        else:
            label = event_labels.get(sample.event_id, fallback_label)
        sample.inferred_label = label
        if sample.status == "ok":
            try:
                relabel_annotation(sample.annotation_path, label)
            except Exception as exc:
                sample.status = "failed"
                sample.error = f"relabel failed: {exc}"
                failures += 1

    # Apply class name mapping if enabled
    mapping_applied = False
    if args.enable_class_mapping:
        mapping_file = Path(args.class_mapping_file)
        try:
            print(f"[INFO] Loading class name mappings from: {mapping_file}")
            mappings = parse_class_mapping_reference(mapping_file)
            if mappings:
                print(f"[INFO] Found {len(mappings)} unified class names in reference")
                original_to_unified = build_original_to_unified_mapping(mappings)
                print(f"[INFO] Built mapping index with {len(original_to_unified)} original name variants")
                
                # Apply mapping to all samples
                mapped_count = 0
                for sample in samples:
                    original_label = sample.inferred_label
                    if original_label:
                        unified_label = apply_class_mapping(
                            original_label,
                            original_to_unified,
                            fallback=None,
                        )
                        if unified_label != original_label:
                            sample.inferred_label = unified_label
                            mapped_count += 1
                            print(f"[MAP] '{original_label}' -> '{unified_label}'")
                            
                            # Re-label the annotation file with unified name
                            if sample.status == "ok":
                                try:
                                    relabel_annotation(sample.annotation_path, unified_label)
                                except Exception as exc:
                                    print(f"[WARN] Failed to re-label {sample.annotation_path}: {exc}")
                
                print(f"[INFO] Applied mapping to {mapped_count} samples")
                mapping_applied = True
            else:
                print(f"[INFO] No mappings found in {mapping_file}, skipping mapping")
        except Exception as exc:
            print(f"[WARN] Failed to load class mapping: {exc}. Continuing without mapping.")

    similarity_clusters: List[Dict[str, Any]] = []
    similarity_report_json: Optional[Path] = None
    similarity_report_csv: Optional[Path] = None
    similarity_synced_annotations = 0
    if args.similarity_threshold > 0:
        try:
            similarity_clusters = build_similarity_clusters(samples, args.similarity_threshold)
            if similarity_clusters:
                similarity_report_json, similarity_report_csv, similarity_synced_annotations = write_similarity_report(
                    similarity_clusters,
                    reports_dir,
                    args.similarity_threshold,
                )
                print(
                    f"[INFO] Image similarity clustering completed: {len(similarity_clusters)} groups, "
                    f"{similarity_synced_annotations} annotations synced"
                )
        except Exception as exc:
            print(f"[WARN] Image similarity clustering failed: {exc}")

    class_order: List[str] = []
    if args.label_policy != "crop-search-direct":
        candidates = load_candidates(class_file)
        for c in candidates:
            if c not in class_order:
                class_order.append(c)
    for s in samples:
        if s.inferred_label and s.inferred_label not in class_order:
            class_order.append(s.inferred_label)
    if not class_order:
        class_order = [args.fixed_label or "object"]

    class_ids = {name: idx for idx, name in enumerate(class_order)}
    yolo_exported = export_yolo(samples, labels_dir, class_ids)

    classes_out = output_dir / "classes_preview.txt"
    classes_out.write_text("\n".join(class_order), encoding="utf-8")

    # Auto-update mapping reference file if enabled
    if args.enable_class_mapping and args.auto_update_mapping:
        mapping_file = Path(args.class_mapping_file)
        if _ANALYZE_CLASSES_MODULE is None:
            print(f"[WARN] analyze_classes.py not loaded: {_ANALYZE_CLASSES_LOAD_ERROR}. Skipping mapping update.")
        else:
            try:
                print(f"[INFO] Auto-updating class mapping reference: {mapping_file}")
                result = _ANALYZE_CLASSES_MODULE.analyze_class_names(
                    classes_file=classes_out,
                    reference_file=mapping_file,
                )
                
                # Extract and merge mappings
                table_content = _ANALYZE_CLASSES_MODULE.extract_table_from_result(result)
                if table_content:
                    new_mappings = _ANALYZE_CLASSES_MODULE.parse_table_to_mappings(table_content)
                    existing_mappings = _ANALYZE_CLASSES_MODULE.parse_existing_mappings(mapping_file)
                    merged_mappings = _ANALYZE_CLASSES_MODULE.merge_mappings(existing_mappings, new_mappings)
                    
                    # Save updated reference
                    final_table = _ANALYZE_CLASSES_MODULE.format_mappings_as_table(merged_mappings)
                    reference_content = f"""# Class Name Mapping Reference

**Last Updated**: {time.strftime("%Y-%m-%d %H:%M:%S")}  
**Source**: `{classes_out.relative_to(Path.cwd()) if classes_out.is_relative_to(Path.cwd()) else classes_out}`  
**Model**: {_ANALYZE_CLASSES_MODULE.DEFAULT_MODEL}

## Standardization Rules
- **Language**: English names only
- **Capitalization**: Sentence case
- **Conflict Resolution**: Pick the most frequent variant
- **Protection**: Existing unified names are preserved

## Unified Class Name Mapping

{final_table}

---
*This file is auto-generated and incrementally updated. Existing unified names are preserved.*
"""
                    mapping_file.write_text(reference_content, encoding="utf-8")
                    print(f"[INFO] Updated mapping reference with {len(merged_mappings)} unified classes")
                else:
                    print(f"[WARN] No table found in analysis result. Skipping mapping update.")
            except Exception as exc:
                print(f"[WARN] Failed to update class mapping reference: {exc}")

    manifest_path = reports_dir / "manifest.csv"
    write_manifest(samples, manifest_path)

    summary = {
        "events_total": len(events),
        "samples_total": len(samples),
        "autolabel_failures": failures,
        "yolo_non_empty_files": yolo_exported,
        "fps": fps,
        "frame_count": frame_count,
        "output_dir": str(output_dir),
        "images_dir": str(images_dir),
        "marked_dir": str(marked_dir),
        "annotations_dir": str(anno_dir),
        "crops_dir": str(crops_dir),
        "labels_dir": str(labels_dir),
        "classes_file": str(classes_out),
        "manifest": str(manifest_path),
        "similarity_threshold": args.similarity_threshold,
        "similarity_group_count": len(similarity_clusters),
        "similarity_synced_annotations": similarity_synced_annotations,
        "similarity_report_json": str(similarity_report_json) if similarity_report_json else "",
        "similarity_report_csv": str(similarity_report_csv) if similarity_report_csv else "",
    }

    report_path = reports_dir / "run_report.json"
    with report_path.open("w", encoding="utf-8") as fp:
        json.dump(summary, fp, indent=2, ensure_ascii=False)

    print("[INFO] Completed auto-label preview pipeline")
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
