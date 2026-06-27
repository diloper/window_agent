# Plan: YouTube Skip-Ad — YOLO self-trained pipeline

Task: 當 YouTube 進入廣告時自動點擊略過, via 自行訓練的 YOLO model.
自動收集影像數據 + 自動標註 + 本地訓練 + 推論點擊.

## Decisions (from user)
- Approach: C. Train own YOLO model (pivot from OCR-only)
- Runtime detector: YOLO IS REQUIRED at runtime. Inference runs on the user's NORMAL browser/desktop (NOT a Selenium-controlled session), so on-screen visual detection is needed. Selenium is used ONLY for data harvesting/labeling in Phase 1, NOT at runtime.
- Dataset isolation: SEPARATE new folders, keep existing ./A, ./labels, classes.txt clean
- Auto-collect: Selenium DOM as primary ad trigger + exact auto-label (OCR demoted to optional fallback)
- Image capture: mss real-desktop capture (so training frames match runtime inference)
- Browser: headed Chrome with user profile
- Capture diversity: vary window size, fullscreen/windowed/theater, light/dark theme, resolution/DPR across sessions so the model generalizes (capture-time variety > augmentation)
- Negatives: dataset must include ~30-50% negative + HARD-negative frames (other player buttons, pre-skip ad, end-cards) for low false-click rate
- Labeling: Phase 1 writes YOLO labels DIRECTLY (knows dims+bbox at capture); Phase 2 is OPTIONAL manual review/refine only
- Runtime click: cursor-preserving (save/restore mouse pos; no warp) + require box stable across >=2 frames before clicking
- Shared capture/coord helper reused by collect + skipper (DRY, identical train/inference capture)
- Train/val split: GROUP-AWARE by capture session / ad instance (NOT random per-frame) to avoid leakage of near-duplicate frames
- Training: GOOGLE COLAB (non-local) via Train_Skip_Ad_Colab.ipynb + export_for_colab.py packaging; local train_skip_model.py kept as optional fallback
- Click lib: pyautogui (new dep)
- Constraint: auto-collect must NOT interfere with user input and must NOT overload CPU
- Packaging: ALL generated files under a new folder `ad_skipper/`

## Pipeline (5 phases)

### Phase 1 — Auto collect (ad_skipper/collect_ad_frames.py, NEW) — SELENIUM-DRIVEN
Decisions: Selenium DOM = primary ad trigger + exact auto-label; mss real-desktop capture for training images; headed Chrome with user profile.
CONSTRAINT: must NOT interfere with user input and must NOT overload CPU.

Mechanism:
- Launch headed Chrome via Selenium (selenium 4 + webdriver-manager) with user-data-dir = user's Chrome profile (--profile arg). Real ads, fewer bot blocks. NO YouTube Premium account.
- CAPTURE DIVERSITY (#2, key for generalization): across/within sessions randomize browser window size, windowed vs fullscreen vs theater mode, light/dark theme, and run on different resolutions/DPR when possible. The skip button's position/scale/background must vary or the model overfits one layout. argparse --vary-layout to toggle automated variation.
- Auto-watch loop: iterate a URL list / search results / playlist (--urls or --query); driver.get(video); ensure playing.
- Ad detection (deterministic, polled ~every 0.3-0.5s via execute_script):
  * player = document.querySelector('#movie_player'); ad active when player.classList contains 'ad-showing' (or 'ad-interrupting'), OR player.getAdState()===1.
  * confirm a skip button exists: querySelector('.ytp-ad-skip-button-modern, .ytp-ad-skip-button, .ytp-skip-ad-button').
- When ad-showing AND skip button present/visible:
  1. Get button bbox via Selenium element.rect (CSS px, viewport-relative).
  2. Capture the REAL desktop with mss (so frames match runtime inference look incl. OS/browser chrome).
  3. Map element.rect -> screen device px:
       toolbarH = window.outerHeight - window.innerHeight; winRect = driver.get_window_rect(); dpr = window.devicePixelRatio.
       screen_x = (winRect.x + rect.x) * dpr; screen_y = (winRect.y + toolbarH + rect.y) * dpr; w = rect.width*dpr; h = rect.height*dpr.
       (Fallback for exactness: CDP Page.getLayoutMetrics / Page.captureScreenshot if mapping drifts.)
  4. Save PNG -> ad_skipper/dataset/images/<session>_<adIdx>_<seq>.png. WRITE YOLO LABEL DIRECTLY (#5): normalize bbox by image w/h -> ad_skipper/dataset/labels/<frame>.txt (`0 cx cy w h`). Also dump raw bbox + group metadata -> ad_skipper/dataset/raw_boxes/<frame>.json for traceability/review.
     - GROUP KEY for split-leakage prevention: session_id (one run/launch) + ad_instance index (each distinct ad encounter). ALL frames of one ad instance share the same group key, embedded in BOTH the filename prefix and the json ("group": "<session>_<adIdx>").
  5. Capture multiple frames across the ad (skip btn appears after ~5s countdown) before optionally clicking skip to move on. These multi-frames are near-duplicates -> MUST stay together in one split (see Phase 3).
- NEGATIVE / HARD-NEGATIVE frames (#6): target ~30-50% of dataset as negatives with EMPTY label files:
  * easy negatives: normal video playback (ad-showing False).
  * hard negatives: ad showing but BEFORE skip button appears (countdown), and frames containing OTHER player buttons (mute/settings/fullscreen/next), end-cards/cards. Forces the model to learn the skip button specifically, not "any button" -> fewer false clicks at runtime.
- VERIFY mapping: overlay saved bbox on saved frame (debug --draw) to confirm alignment before mass harvest.

Non-intrusive + low CPU:
- Selenium drives ITS OWN browser window; does not hijack user's foreground input. Run headed but user can leave it; no global hotkeys, no input simulation on user's apps.
- Below-normal process priority (psutil). mss grab only fires on ad-showing events, not every frame -> low CPU. Polling uses lightweight execute_script, sleeps between polls (--poll-interval).
- dedupe via imagehash (already in auto_label_from_events.py).
- Uses SHARED capture/coord helper (#12) ad_skipper/_capture.py for mss grab + element.rect->screen-px mapping; same helper used by Phase 5 so train and inference capture are IDENTICAL.
- argparse: --urls/--query --profile --monitor --poll-interval --max-frames --frames-per-ad --neg-ratio --vary-layout --out-dir --draw --priority
- NEW dep: selenium (+ webdriver-manager). easyocr now only OPTIONAL fallback labeler.

### Phase 2 — Pseudo-label REVIEW (ad_skipper/auto_label_skip_button.py, NEW — OPTIONAL)
- Labels are ALREADY written by Phase 1 (#5). This script is an OPTIONAL review/refine pass:
  * regenerate/repair YOLO txt from raw_boxes json (e.g. re-pad bbox, fix class id) if needed.
  * draw bbox overlays for visual QA; export to X-AnyLabeling for manual correction of mislabeled frames.
- ad_skipper/ad_classes.txt = single line: skip_ad_button.

### Phase 3 — Dataset prep (ad_skipper/prepare_ad_dataset.py, NEW)
- Parametrized copy of auto_prepare_dataset.py logic (avoid touching existing-behavior script), pointed at ad_skipper/dataset.
- GROUP-AWARE split (KEY FIX): do NOT random-shuffle individual frames (auto_prepare_dataset.py default) — that leaks near-duplicate ad frames into both train AND val, inflating mAP.
  * Derive group key per image from filename prefix / raw_ocr json "group" (= <session>_<adIdx>).
  * Shuffle the LIST OF GROUPS, then assign whole groups to train/val by ratio (train ~0.8). Every frame of an ad instance lands entirely in one split.
  * Negative/background frames grouped too (e.g. by session+segment) so they don't leak either.
  * Optional: target split ratio by group count, with a tolerance so frame counts stay roughly 80/20.
- Output ad_skipper/dataset/yolo/{train,val}/{images,labels} + data.yaml (nc=1, names=[skip_ad_button]).
- Log group/frame counts per split; assert no group_id appears in both train and val.

### Phase 4 — Train on GOOGLE COLAB (non-local)
Packaging (local): ad_skipper/export_for_colab.py zips dataset/yolo/{train,val} + a Colab-relative data.yaml (path: /content/ad_skipper_dataset) -> ad_skipper/ad_skipper_dataset.zip.
Colab: ad_skipper/Train_Skip_Ad_Colab.ipynb (Runtime=GPU):
  1. !nvidia-smi (verify GPU)
  2. pip install ultralytics; ultralytics.checks()
  3. upload ad_skipper_dataset.zip (files.upload) OR mount Drive; unzip to /content/ad_skipper_dataset
  4. YOLO('yolo11n.pt').train(data='/content/ad_skipper_dataset/data.yaml', epochs=100, imgsz=640, batch=16)
  5. model.val() -> report mAP50 / mAP50-95
  6. download best.pt as skip_ad_yolo.pt -> place in ad_skipper/models/ locally for Phase 5
Fallback: ad_skipper/train_skip_model.py for local GPU runs (same hyperparams).

### Phase 5 — Inference + click (ad_skipper/youtube_ad_skipper.py, NEW)
- load YOLO("ad_skipper/models/skip_ad_yolo.pt"); mss capture loop via SHARED helper (#12) so it matches training capture.
- results = model.predict(frame, conf=...); map detected box (image device-px) -> screen click point (center, account for monitor offset + DPR via shared helper).
- CURSOR-PRESERVING CLICK (#3): do NOT warp the user's mouse. Save current cursor pos, click target via Win32 SendInput / pydirectinput, then restore cursor. Honors the non-interference constraint at RUNTIME too.
- STABILITY GATE: only click when a skip_ad_button box is detected on >=2 consecutive frames at a consistent location (avoid single-frame false positives).
- cooldown ~2s debounce; verify ad-gone before re-arming; clean Ctrl+C guard.
- argparse: --model --monitor --interval --conf --dry-run.

## Files (ALL new generated files under ad_skipper/ — keep repo root clean)
Container: ad_skipper/
- ad_skipper/_capture.py  (#12 SHARED helper: mss grab + element.rect->screen-px mapping + cursor-preserving click; used by collect & skipper)
- ad_skipper/collect_ad_frames.py
- ad_skipper/auto_label_skip_button.py  (OPTIONAL review/refine — labels already written by Phase 1)
- ad_skipper/prepare_ad_dataset.py
- ad_skipper/export_for_colab.py  (zip dataset + Colab data.yaml for non-local training)
- ad_skipper/Train_Skip_Ad_Colab.ipynb  (Colab GPU training notebook — primary Phase 4)
- ad_skipper/train_skip_model.py  (optional LOCAL fallback trainer)
- ad_skipper/youtube_ad_skipper.py
- ad_skipper/ad_classes.txt (skip_ad_button)
- ad_skipper/dataset/ (images/, labels/, raw_boxes/, yolo/{train,val}/{images,labels} + data.yaml)
- ad_skipper/models/skip_ad_yolo.pt (trained best.pt copied here)
- ad_skipper/runs/ (ultralytics training output, gitignore)
- MODIFY (repo root) requirements.txt + pyproject.toml: add ultralytics, pyautogui (or pydirectinput for cursor-preserving click), selenium, webdriver-manager (easyocr, mss, opencv, imagehash, playwright already present; easyocr now optional)
- Add ad_skipper/runs/ and large artifacts to .gitignore
- REUSE: screen_event_recorder.py (mss pattern), easyocr_checker.py (reader config), auto_prepare_dataset.py (split logic), Train_YOLO_Models.ipynb (ultralytics ref)
- All scripts use paths relative to ad_skipper/ (Path(__file__).parent) so they run from anywhere.

## Verification
- py_compile each new script
- Phase1 smoke: run collect on a live ad, confirm frames + YOLO label .txt written directly & deduped; --draw overlay aligns; confirm neg-ratio of empty-label frames; layout variation observed when --vary-layout
- Phase2 (optional): review overlays; spot-fix mislabels
- Phase3: confirm data.yaml nc=1, train/val split populated; assert ZERO group overlap between train and val (no <session>_<adIdx> in both)
- Phase4 (Colab): export_for_colab.py produces zip with images+labels+Colab data.yaml; notebook trains on GPU, model.val() reports mAP, best.pt downloaded as skip_ad_yolo.pt
- Phase5: --dry-run logs detections + coords; live test skips an ad once w/ cooldown

## Branching
- feature/20260626-yolo-ad-skipper (Git Bash) before edits.

## Open considerations
- Runtime scope (RESOLVED): YOLO required at runtime — detection runs on the user's normal browser/desktop, not via Selenium. Selenium is harvest-only. This justifies Phases 2-5 and the on-screen detect+click loop. Domain-match (#2) and identical shared-capture (#12) between harvest and runtime are therefore critical.
- Split leakage (ADDRESSED): near-duplicate multi-frames per ad must not span train+val; solved via group-aware split keyed by <session>_<adIdx>. Without this, validation mAP is overstated and unreliable.
- Skip-button selector drift: YouTube renames classes periodically; use a configurable selector list with current candidates as defaults, validated on first run.
- Coordinate mapping risk: display scaling / multi-monitor can offset bbox; mitigate with --draw verify step + CDP fallback.
- Class circularity / precision: need NEGATIVE (non-ad) frames in dataset for false-positive control; optional manual review pass.
- Unskippable / no-ad sessions: only frames with a real skip button get positive labels; harvesting loops videos until --max-frames target reached.
