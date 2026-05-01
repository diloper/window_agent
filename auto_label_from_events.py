import argparse
import csv
import json
import os
import re
import subprocess
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import cv2
from serpapi_image_search_example import search_images


TIMESTAMP_PATTERN = re.compile(r"(\d{8}_\d{6})")


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
    status: str = "pending"
    error: str = ""
    inferred_label: str = ""


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
        required=True,
        help="Path to events_*.json recorded by screen_event_recorder.py",
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
        default=150,
        help="Sampling window before event in milliseconds",
    )
    parser.add_argument(
        "--window-after-ms",
        type=int,
        default=150,
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
        default=r"R:/SAM/model/sam2_hiera_tiny_encoder.onnx",
        help="Encoder ONNX path for tools/autolabel.py",
    )
    parser.add_argument(
        "--decoder",
        default=r"R:/SAM/model/sam2_hiera_tiny_decoder.onnx",
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
        default="serpapi-topk",
        choices=["serpapi-topk", "fixed"],
        help="Class assignment strategy",
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


def parse_iso_timestamp(raw: str) -> datetime:
    try:
        return datetime.fromisoformat(raw)
    except ValueError as exc:
        raise ValueError(f"Invalid event timestamp: {raw}") from exc


def load_mouse_events(
    events_json: Path,
    video_start_dt: datetime,
    button_filter: str,
) -> List[MouseEvent]:
    with events_json.open("r", encoding="utf-8") as fp:
        payload = json.load(fp)

    events: List[MouseEvent] = []
    next_id = 1
    for item in payload:
        t = item.get("type", "")
        if t not in {"mouse_press", "mouse_release"}:
            continue

        button = str(item.get("button", "")).lower()
        if button_filter != "any" and button != button_filter:
            continue

        if "x" not in item or "y" not in item or "timestamp" not in item:
            continue

        dt = parse_iso_timestamp(item["timestamp"])
        rel_seconds = (dt - video_start_dt).total_seconds()
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
) -> List[Tuple[MouseEvent, int]]:
    plan: List[Tuple[MouseEvent, int]] = []
    before_frames = max(0, int(round(before_ms * fps / 1000.0)))
    after_frames = max(0, int(round(after_ms * fps / 1000.0)))

    for event in events:
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
        "inferred_label",
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
                    "inferred_label": s.inferred_label,
                    "status": s.status,
                    "error": s.error,
                }
            )


def main() -> int:
    args = parse_args()

    load_dotenv_file(Path(args.dotenv_path))

    events_json = Path(args.events_json)
    video_path = Path(args.video)
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
        video_start_dt = ensure_matching_session(events_json, video_path)
    except Exception as exc:
        print(f"[ERROR] {exc}")
        return 1

    output_dir.mkdir(parents=True, exist_ok=True)
    images_dir = output_dir / "images"
    anno_dir = output_dir / "annotations_labelme"
    labels_dir = output_dir / "labels"
    reports_dir = output_dir / "reports"
    images_dir.mkdir(parents=True, exist_ok=True)
    anno_dir.mkdir(parents=True, exist_ok=True)
    labels_dir.mkdir(parents=True, exist_ok=True)
    reports_dir.mkdir(parents=True, exist_ok=True)

    events = load_mouse_events(events_json, video_start_dt, args.button)
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

    plan = build_frame_plan(
        events=events,
        fps=fps,
        frame_count=frame_count,
        before_ms=args.window_before_ms,
        after_ms=args.window_after_ms,
        max_frames_per_event=max(1, args.max_frames_per_event),
    )
    if not plan:
        print("[ERROR] No frame sampling plan generated.")
        return 1

    samples = extract_sample_frames(video_path, plan, images_dir, anno_dir)
    if not samples:
        print("[ERROR] No frames extracted from the video.")
        return 1

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
            ok, err = run_autolabel_for_sample(sample, args, sys.executable)
            if ok:
                sample.status = "ok"
            else:
                sample.status = "failed"
                sample.error = err
                failures += 1

    candidates = load_candidates(class_file)
    fallback_label = args.fixed_label or "object"
    if args.label_policy == "fixed":
        event_labels = {event.event_id: fallback_label for event in events}
    else:
        if not candidates:
            candidates = [fallback_label]

        serpapi_key = args.serpapi_api_key or os.getenv("SERPAPI_API_KEY", "")
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
        label = event_labels.get(sample.event_id, fallback_label)
        sample.inferred_label = label
        if sample.status == "ok":
            try:
                relabel_annotation(sample.annotation_path, label)
            except Exception as exc:
                sample.status = "failed"
                sample.error = f"relabel failed: {exc}"
                failures += 1

    class_order: List[str] = []
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
        "annotations_dir": str(anno_dir),
        "labels_dir": str(labels_dir),
        "classes_file": str(classes_out),
        "manifest": str(manifest_path),
    }

    report_path = reports_dir / "run_report.json"
    with report_path.open("w", encoding="utf-8") as fp:
        json.dump(summary, fp, indent=2, ensure_ascii=False)

    print("[INFO] Completed auto-label preview pipeline")
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
