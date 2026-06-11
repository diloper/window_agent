"""
Resolve label conflicts in similar image groups.

Detects images with similarity ≥0.9 and ROI overlap (IoU ≥0.7) but different labels,
enables batch selection of master labels, and updates all group members accordingly.

Usage:
    python resolve_label_conflicts.py --folder auto_labels_preview_screen_20260515_161232
    python resolve_label_conflicts.py --folder auto_labels_preview_screen_20260515_161232 --auto
"""

import argparse
import json
import sys
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Any, Tuple, Optional, Set
from dataclasses import dataclass, asdict
from collections import defaultdict


@dataclass
class ShapeInfo:
    """Information about a bounding box shape."""
    label: str
    points: List[List[float]]  # [[x1, y1], [x2, y1], [x2, y2], [x1, y2]]
    
    def get_bounds(self) -> Tuple[float, float, float, float]:
        """Return (x_min, y_min, x_max, y_max)."""
        xs = [p[0] for p in self.points]
        ys = [p[1] for p in self.points]
        return min(xs), min(ys), max(xs), max(ys)


@dataclass
class ConflictInfo:
    """Information about a label conflict between two samples."""
    cluster_id: int
    member_id_1: int
    member_id_2: int
    image_1: str
    image_2: str
    annotation_1: str
    annotation_2: str
    similarity: float
    roi_iou: float
    label_from_1: str
    label_from_2: str
    shape_bounds: Tuple[float, float, float, float]


def load_json(path: Path) -> Dict[str, Any]:
    """Load JSON file safely."""
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_json(data: Any, path: Path, indent: int = 2) -> None:
    """Save JSON file safely."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=indent, ensure_ascii=False)


def calculate_iou(box1: Tuple[float, float, float, float],
                  box2: Tuple[float, float, float, float]) -> float:
    """Calculate Intersection over Union (IoU) between two bounding boxes.
    
    Args:
        box1: (x_min, y_min, x_max, y_max)
        box2: (x_min, y_min, x_max, y_max)
    
    Returns:
        IoU value between 0 and 1
    """
    x1_min, y1_min, x1_max, y1_max = box1
    x2_min, y2_min, x2_max, y2_max = box2
    
    # Calculate intersection
    x_left = max(x1_min, x2_min)
    y_top = max(y1_min, y2_min)
    x_right = min(x1_max, x2_max)
    y_bottom = min(y1_max, y2_max)
    
    if x_right < x_left or y_bottom < y_top:
        return 0.0  # No intersection
    
    intersection_area = (x_right - x_left) * (y_bottom - y_top)
    
    # Calculate union
    box1_area = (x1_max - x1_min) * (y1_max - y1_min)
    box2_area = (x2_max - x2_min) * (y2_max - y2_min)
    union_area = box1_area + box2_area - intersection_area
    
    if union_area <= 0:
        return 0.0
    
    return intersection_area / union_area


def read_annotation_shapes(annotation_path: Path) -> List[ShapeInfo]:
    """Read shapes from LabelMe JSON annotation."""
    if not annotation_path.exists():
        return []
    
    try:
        data = load_json(annotation_path)
        shapes = []
        for shape in data.get("shapes", []):
            label = str(shape.get("label", "object")).strip()
            points = shape.get("points", [])
            if label and points:
                shapes.append(ShapeInfo(label=label, points=points))
        return shapes
    except Exception as e:
        print(f"[WARN] Cannot read annotation {annotation_path}: {e}")
        return []


def find_overlapping_shapes(shapes1: List[ShapeInfo],
                           shapes2: List[ShapeInfo],
                           iou_threshold: float = 0.7) -> List[Tuple[ShapeInfo, ShapeInfo, float]]:
    """Find overlapping shapes between two annotations.
    
    Returns:
        List of (shape1, shape2, iou) tuples where iou >= iou_threshold
    """
    overlaps = []
    for s1 in shapes1:
        box1 = s1.get_bounds()
        for s2 in shapes2:
            box2 = s2.get_bounds()
            iou = calculate_iou(box1, box2)
            if iou >= iou_threshold:
                overlaps.append((s1, s2, iou))
    return overlaps


def detect_conflicts(similarity_groups: Dict[str, Any],
                     recordings_dir: Path,
                     folder_name: str,
                     iou_threshold: float = 0.7,
                     similarity_threshold: float = 0.9) -> List[ConflictInfo]:
    """Detect label conflicts in similarity groups.
    
    Args:
        similarity_groups: Loaded similarity_groups.json data
        recordings_dir: Path to recordings directory
        folder_name: Name of the auto_labels_preview folder
        iou_threshold: Minimum IoU to consider ROIs overlapping
        similarity_threshold: Minimum similarity to consider
    
    Returns:
        List of detected conflicts
    """
    conflicts = []
    
    for cluster in similarity_groups.get("clusters", []):
        cluster_id = cluster.get("group_id")
        members = cluster.get("members", [])
        
        if len(members) < 2:
            continue
        
        # Pairwise comparison of members
        for i, member1 in enumerate(members):
            for member2 in members[i+1:]:
                # Check similarity threshold
                similarity = member1.get("similarity_to_representative", 0.0)
                if similarity < similarity_threshold:
                    continue
                
                # Load annotations (paths are already absolute from JSON)
                anno1_path = Path(member1.get("annotation_path", "").replace("\\", "/"))
                anno2_path = Path(member2.get("annotation_path", "").replace("\\", "/"))
                
                shapes1 = read_annotation_shapes(anno1_path)
                shapes2 = read_annotation_shapes(anno2_path)
                
                if not shapes1 or not shapes2:
                    continue
                
                # Find overlapping shapes
                overlaps = find_overlapping_shapes(shapes1, shapes2, iou_threshold)
                
                # Check for label differences in overlaps
                for shape1, shape2, iou in overlaps:
                    if shape1.label != shape2.label:
                        conflict = ConflictInfo(
                            cluster_id=cluster_id,
                            member_id_1=member1.get("sample_id"),
                            member_id_2=member2.get("sample_id"),
                            image_1=member1.get("image_path", ""),
                            image_2=member2.get("image_path", ""),
                            annotation_1=member1.get("annotation_path", ""),
                            annotation_2=member2.get("annotation_path", ""),
                            similarity=similarity,
                            roi_iou=iou,
                            label_from_1=shape1.label,
                            label_from_2=shape2.label,
                            shape_bounds=shape1.get_bounds()
                        )
                        conflicts.append(conflict)
    
    return conflicts


def format_conflict_display(idx: int, conflict: ConflictInfo, folder_path: Path) -> str:
    """Format a conflict for user display."""
    lines = [
        f"\n{'='*80}",
        f"Conflict #{idx}",
        f"  Cluster: {conflict.cluster_id} | Similarity: {conflict.similarity:.4f} | IoU: {conflict.roi_iou:.4f}",
        f"  Sample 1 (ID={conflict.member_id_1}): {Path(conflict.image_1).name}",
        f"    Label: {conflict.label_from_1}",
        f"  Sample 2 (ID={conflict.member_id_2}): {Path(conflict.image_2).name}",
        f"    Label: {conflict.label_from_2}",
        f"  ROI bounds: ({conflict.shape_bounds[0]:.1f}, {conflict.shape_bounds[1]:.1f}) "
        f"→ ({conflict.shape_bounds[2]:.1f}, {conflict.shape_bounds[3]:.1f})",
        f"  Options: [{conflict.label_from_1}] or [{conflict.label_from_2}]",
    ]
    return "\n".join(lines)


def interactive_resolution(conflicts: List[ConflictInfo]) -> Dict[int, str]:
    """Get user selections for conflict resolution.
    
    Returns:
        Dict mapping conflict index to chosen label
    """
    if not conflicts:
        print("No conflicts detected.")
        return {}
    
    print(f"\n{'='*80}")
    print(f"Found {len(conflicts)} conflict(s) to resolve")
    print(f"{'='*80}\n")
    
    # Display all conflicts
    for idx, conflict in enumerate(conflicts):
        print(format_conflict_display(idx, conflict, Path(".")))
    
    # Get user selections
    print(f"\n{'='*80}")
    print("Enter your selections (format: conflict_idx:label)")
    print("Example: 0:CHT帳號  1:Login button  2:CHT帳號")
    print("Or press Enter to auto-use first label for each conflict")
    print(f"{'='*80}\n")
    
    selections = {}
    try:
        user_input = input("Selections: ").strip()
        if not user_input:
            # Auto-select: use label_from_1 for all conflicts
            for idx in range(len(conflicts)):
                selections[idx] = conflicts[idx].label_from_1
        else:
            parts = user_input.split()
            for part in parts:
                if ":" in part:
                    idx_str, label = part.split(":", 1)
                    try:
                        idx = int(idx_str)
                        if 0 <= idx < len(conflicts):
                            selections[idx] = label
                    except ValueError:
                        print(f"[WARN] Skipping invalid format: {part}")
    except KeyboardInterrupt:
        print("\n[INFO] Cancelled by user")
        return {}
    
    # Validate selections
    validated = {}
    for idx, label in selections.items():
        conflict = conflicts[idx]
        if label in [conflict.label_from_1, conflict.label_from_2]:
            validated[idx] = label
        else:
            print(f"[WARN] Invalid label for conflict {idx}: {label}")
    
    return validated


def backup_annotation(annotation_path: Path, backup_dir: Path) -> Path:
    """Backup an annotation file."""
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup_path = backup_dir / annotation_path.name
    if annotation_path.exists():
        import shutil
        shutil.copy2(annotation_path, backup_path)
    return backup_path


def update_annotation_label(annotation_path: Path,
                           old_bounds: Tuple[float, float, float, float],
                           new_label: str,
                           iou_threshold: float = 0.5) -> bool:
    """Update shape label in annotation file if it overlaps with given bounds.
    
    Args:
        annotation_path: Path to LabelMe JSON
        old_bounds: (x_min, y_min, x_max, y_max) of shape to match
        new_label: New label to assign
        iou_threshold: IoU threshold for matching (lowered to 0.5 for more flexibility)
    
    Returns:
        True if any shape was updated, False otherwise
    """
    if not annotation_path.exists():
        return False
    
    try:
        data = load_json(annotation_path)
        updated = False
        
        for shape in data.get("shapes", []):
            shape_info = ShapeInfo(label=shape.get("label", ""), points=shape.get("points", []))
            if not shape_info.points:
                continue
            
            shape_bounds = shape_info.get_bounds()
            iou = calculate_iou(old_bounds, shape_bounds)
            
            # Only update if IoU exceeds threshold AND label is actually different
            if iou >= iou_threshold and shape["label"] != new_label:
                shape["label"] = new_label
                updated = True
        
        if updated:
            save_json(data, annotation_path)
        
        return updated
    except Exception as e:
        print(f"[ERROR] Failed to update {annotation_path}: {e}")
        return False


def apply_resolutions(conflicts: List[ConflictInfo],
                      selections: Dict[int, str],
                      recordings_dir: Path,
                      folder_name: str,
                      backup_dir: Optional[Path] = None) -> Dict[str, Any]:
    """Apply selected resolutions to annotations.
    
    Returns:
        Resolution log with update details
    """
    folder_path = recordings_dir / folder_name
    log = {
        "timestamp": datetime.now().isoformat(),
        "conflicts_resolved": 0,
        "files_updated": [],
        "failed_updates": []
    }
    
    if not backup_dir:
        backup_dir = folder_path / "_backup" / datetime.now().strftime("%Y%m%d_%H%M%S")
    
    for idx, selected_label in selections.items():
        conflict = conflicts[idx]
        
        # Determine which file needs to be updated based on selection
        # If we selected label_from_1, we update member 2 to match member 1
        # If we selected label_from_2, we update member 1 to match member 2
        if selected_label == conflict.label_from_1:
            # Update member 2's annotation with master label from member 1
            update_path = Path(conflict.annotation_2.replace("\\", "/"))
            master_label = conflict.label_from_1
            direction = "member2_to_member1"
        else:
            # Update member 1's annotation with master label from member 2
            update_path = Path(conflict.annotation_1.replace("\\", "/"))
            master_label = conflict.label_from_2
            direction = "member1_to_member2"
        
        # Backup before update
        if update_path.exists():
            backup_annotation(update_path, backup_dir)
        
        # Apply update
        if update_annotation_label(update_path, conflict.shape_bounds, master_label):
            log["files_updated"].append({
                "file": str(update_path),
                "conflict_idx": idx,
                "new_label": master_label,
                "cluster_id": conflict.cluster_id,
                "direction": direction
            })
            log["conflicts_resolved"] += 1
        else:
            log["failed_updates"].append({
                "file": str(update_path),
                "conflict_idx": idx,
                "new_label": master_label,
                "reason": "Update failed or no matching shape found"
            })
    
    return log


def generate_conflict_report(conflicts: List[ConflictInfo],
                            folder_name: str,
                            recordings_dir: Path) -> Dict[str, Any]:
    """Generate a detailed conflict report."""
    report = {
        "timestamp": datetime.now().isoformat(),
        "folder": folder_name,
        "threshold_similarity": 0.9,
        "threshold_iou": 0.7,
        "total_conflicts": len(conflicts),
        "conflicts_by_cluster": defaultdict(list),
        "unique_labels_in_conflict": set(),
        "details": []
    }
    
    for idx, conflict in enumerate(conflicts):
        cluster_id = conflict.cluster_id
        report["conflicts_by_cluster"][cluster_id].append(idx)
        report["unique_labels_in_conflict"].add(conflict.label_from_1)
        report["unique_labels_in_conflict"].add(conflict.label_from_2)
        
        report["details"].append({
            "conflict_idx": idx,
            "cluster_id": cluster_id,
            "member_id_1": conflict.member_id_1,
            "member_id_2": conflict.member_id_2,
            "image_1": conflict.image_1,
            "image_2": conflict.image_2,
            "similarity": conflict.similarity,
            "roi_iou": conflict.roi_iou,
            "label_from_1": conflict.label_from_1,
            "label_from_2": conflict.label_from_2,
            "roi_bounds": {
                "x_min": conflict.shape_bounds[0],
                "y_min": conflict.shape_bounds[1],
                "x_max": conflict.shape_bounds[2],
                "y_max": conflict.shape_bounds[3]
            }
        })
    
    # Convert sets to lists for JSON serialization
    report["conflicts_by_cluster"] = dict(report["conflicts_by_cluster"])
    report["unique_labels_in_conflict"] = list(report["unique_labels_in_conflict"])
    
    return report


def generate_text_summary(conflicts: List[ConflictInfo],
                         selections: Dict[int, str],
                         log: Dict[str, Any],
                         folder_name: str) -> str:
    """Generate a human-readable summary."""
    lines = [
        "=" * 80,
        f"Label Conflict Resolution Summary",
        "=" * 80,
        f"Folder: {folder_name}",
        f"Timestamp: {log['timestamp']}",
        f"",
        f"Detection Results:",
        f"  Total conflicts found: {len(conflicts)}",
        f"  Thresholds: similarity >= 0.9, IoU >= 0.7",
        f"",
        f"Resolution Results:",
        f"  Conflicts resolved: {log['conflicts_resolved']}/{len(selections)}",
        f"  Files updated: {len(log['files_updated'])}",
        f"  Failed updates: {len(log['failed_updates'])}",
        f"",
        f"Updated Files:",
    ]
    
    if log['files_updated']:
        for update in log['files_updated']:
            lines.append(f"  • {Path(update['file']).name}")
            lines.append(f"    New label: {update['new_label']} (conflict #{update['conflict_idx']})")
    else:
        lines.append("  (none)")
    
    if log['failed_updates']:
        lines.extend([
            f"",
            f"Failed Updates:",
        ])
        for failed in log['failed_updates']:
            lines.append(f"  • {Path(failed['file']).name}: {failed['reason']}")
    
    lines.extend([
        f"",
        f"Backup Location:",
        f"  {folder_name}/_backup/<timestamp>/",
        f"",
        "=" * 80,
    ])
    
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(
        description="Resolve label conflicts in similar image groups"
    )
    parser.add_argument(
        "--folder",
        required=True,
        help="Name of auto_labels_preview folder (e.g., auto_labels_preview_screen_20260515_161232)"
    )
    parser.add_argument(
        "--recordings-dir",
        default="recordings",
        help="Path to recordings directory (default: recordings)"
    )
    parser.add_argument(
        "--iou-threshold",
        type=float,
        default=0.7,
        help="Minimum IoU for ROI overlap (default: 0.7)"
    )
    parser.add_argument(
        "--similarity-threshold",
        type=float,
        default=0.9,
        help="Minimum similarity for consideration (default: 0.9)"
    )
    parser.add_argument(
        "--auto",
        action="store_true",
        help="Auto-select first label for all conflicts (non-interactive)"
    )
    
    args = parser.parse_args()
    
    recordings_dir = Path(args.recordings_dir)
    folder_path = recordings_dir / args.folder
    similarity_groups_path = folder_path / "reports" / "similarity_groups.json"
    
    # Force unbuffered output
    sys.stdout.reconfigure(encoding='utf-8', line_buffering=True)
    sys.stderr.reconfigure(encoding='utf-8', line_buffering=True)
    
    # Validate inputs
    if not folder_path.exists():
        print(f"[ERROR] Folder not found: {folder_path}", file=sys.stderr, flush=True)
        sys.exit(1)
    
    if not similarity_groups_path.exists():
        print(f"[ERROR] similarity_groups.json not found: {similarity_groups_path}", file=sys.stderr, flush=True)
        sys.exit(1)
    
    print(f"[INFO] Loading similarity groups from {similarity_groups_path}")
    similarity_groups = load_json(similarity_groups_path)
    
    # Phase 2: Detect conflicts
    print(f"[INFO] Detecting conflicts (similarity >= {args.similarity_threshold}, IoU >= {args.iou_threshold})...")
    conflicts = detect_conflicts(
        similarity_groups,
        recordings_dir,
        args.folder,
        iou_threshold=args.iou_threshold,
        similarity_threshold=args.similarity_threshold
    )
    
    print(f"[INFO] Found {len(conflicts)} conflict(s)")
    
    if not conflicts:
        print("[INFO] No conflicts to resolve")
        
        # Still generate report
        report = generate_conflict_report(conflicts, args.folder, recordings_dir)
        report_path = recordings_dir / f"{args.folder}_conflict_report.json"
        save_json(report, report_path)
        print(f"[INFO] Report saved to {report_path}")
        return 0
    
    # Phase 3: Interactive selection or auto mode
    if args.auto:
        print("[INFO] Using auto mode: selecting first label for all conflicts")
        selections = {idx: conflicts[idx].label_from_1 for idx in range(len(conflicts))}
    else:
        selections = interactive_resolution(conflicts)
    
    if not selections:
        print("[INFO] No selections made, exiting")
        return 0
    
    # Phase 4: Apply updates
    print(f"[INFO] Applying {len(selections)} resolution(s)...")
    backup_dir = folder_path / "_backup" / datetime.now().strftime("%Y%m%d_%H%M%S")
    log = apply_resolutions(conflicts, selections, recordings_dir, args.folder, backup_dir)
    
    print(f"[INFO] Resolution complete: {log['conflicts_resolved']} conflict(s) resolved")
    print(f"[INFO] Backup stored in: {backup_dir}")
    
    # Phase 5: Generate reports
    print("[INFO] Generating reports...")
    
    # Conflict report
    report = generate_conflict_report(conflicts, args.folder, recordings_dir)
    report_path = recordings_dir / f"{args.folder}_conflict_report.json"
    save_json(report, report_path)
    print(f"[INFO] Conflict report: {report_path}")
    
    # Resolution log
    log_path = recordings_dir / f"{args.folder}_resolution_log.json"
    save_json(log, log_path)
    print(f"[INFO] Resolution log: {log_path}")
    
    # Text summary
    summary = generate_text_summary(conflicts, selections, log, args.folder)
    summary_path = recordings_dir / f"{args.folder}_resolution_summary.txt"
    with summary_path.open("w", encoding="utf-8") as f:
        f.write(summary)
    print(f"[INFO] Summary: {summary_path}")
    
    print(f"\n{summary}")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
