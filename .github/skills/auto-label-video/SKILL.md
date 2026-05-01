---
name: auto-label-video
description: "Standardized video auto-labeling workflow. Triggered by '自動標註 XXX.mp4' to streamline video frame extraction and SerpAPI-based class inference."
argument-hint: "Video filename (e.g., screen_20260430_214417.mp4 or autolabel screen_20260430_214417.mp4)"
user-invocable: true
---

# Auto-Label Video Skill

## Purpose
Provide a one-command interface to execute the full video auto-labeling pipeline without repeating parameter setup. Automatically infers matching events JSON and derives output directories.

## When To Use
- User inputs "自動標註 XXX.mp4" (Chinese: auto-label video)
- User inputs "autolabel XXX.mp4" (English variant)
- User requests quick video labeling with SerpAPI-based class inference
- Reduces repetitive parameter entry for common labeling workflows

## Trigger Patterns
- "自動標註 screen_*.mp4"
- "自動標註 XXX.mp4"
- "autolabel screen_*.mp4"
- "autolabel XXX.mp4"
- "label video XXX.mp4"
- Similar command patterns in English or Chinese

## Default Procedure

1. **Parse video filename from user input**
   - Extract just the filename (e.g., "screen_20260430_214417.mp4") if full path provided
   - Verify file exists in recordings/ directory

2. **Infer matching events JSON**
   - From video_stem (e.g., "20260430_214417"), find events_[timestamp].json in recordings/
   - Abort with clear message if not found

3. **Execute auto_label_from_events.py with standardized parameters**
   ```bash
   C:\Users\User\miniconda3\python.exe auto_label_from_events.py \
     --events-json <inferred_events_json> \
     --video <video_path> \
     --label-policy serpapi-topk \
     [other params use defaults: output-dir auto-derived, window-before-ms=0, window-after-ms=0, topk=3, etc.]
   ```

4. **Report results**
   - Display output directory path
   - Show samples extracted, autolabel success/failure counts
   - Point user to manifest.csv and report.json for detailed results

## Expected Behavior
- Without explicit parameters: full SerpAPI-based labeling (not skipped)
- Output directory: auto-computed as `recordings/auto_labels_preview_<video_stem>`
- Sampling: only at event time (window-before-ms=0, window-after-ms=0)
- Class inference: top-3 SerpAPI ranking with voting

## Example Invocation
User: "自動標註 screen_20260430_214417.mp4"

→ Skill detects video in recordings/, infers events_20260430_214417.json, runs full pipeline
→ Reports: images extracted, autolabel results, output saved to recordings/auto_labels_preview_screen_20260430_214417
