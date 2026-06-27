# YouTube Skip-Ad YOLO — Agent Brief (design + status)

> READ ORDER for any agent: §1 Status → §2 Ground-truth facts → §4 Active task.
> Rule: describe ONLY what the repo actually contains. If unsure, open the file
> and check. Do NOT invent flags, files, or behaviors.
> Python interpreter (always): `R:\SAM\.venv\Scripts\python.exe`
> User-facing run manual: `ad_skipper/PHASES_GUIDE.md`. This file = design/decision source.

## 0. Goal
When YouTube shows an ad, use a self-trained YOLO model to detect the "Skip Ad" button
on the user's real desktop and click it automatically. Data flow: auto-collect frames +
auto-label → train on Google Colab → local inference + click.

## 1. Status (read first)

### BUILT — already implemented and merged to `main`
- Five-phase pipeline scripts all exist under `ad_skipper/`:
  `_capture.py`, `collect_ad_frames.py`, `auto_label_skip_button.py`,
  `prepare_ad_dataset.py`, `export_for_colab.py`, `train_skip_model.py`,
  `youtube_ad_skipper.py`, `Train_Skip_Ad_Colab.ipynb`, `PHASES_GUIDE.md`.
- Single class today: `ad_classes.txt` = one line `skip_ad_button` (class 0); `data.yaml` nc=1.

### IN PROGRESS — the ONLY task on the current branch
- Branch: `feature/20260627-collect-popup-class`.
- Add class 1 `popup_dismiss_button`: also collect YouTube blocking-popup dismiss
  buttons as YOLO samples. Full spec in §4. (Not yet started in code.)

## 2. Ground-truth facts (verify before relying on them)
- Class source of truth: `ad_classes.txt`. `prepare_ad_dataset.py` and
  `export_for_colab.py` both `_load_classes()` from it and auto-write `nc` / `names`
  into `data.yaml`. Adding a 2nd line ⇒ nc=2 automatically; those two scripts need NO change.
- `collect_ad_frames.py` REAL CLI flags (do not invent others):
  `--urls`/`--query` (mutually exclusive, required), `--url-limit`, `--profile`,
  `--profile-directory`, `--monitor`, `--poll-interval`, `--max-frames`,
  `--frames-per-ad`, `--neg-ratio`, `--per-video-seconds`, `--vary-layout`,
  `--headless`, `--draw`, `--quiet`, `--session-id`.
- `collect_ad_frames.py` internals that matter for §4:
  - `_save_frame()` currently HARD-CODES class `0` in the label line → must be parametrized.
  - `_PLAYER_STATE_JS` returns the player's skip-button rect ONLY (player-scoped).
    A new page-level popup JS is needed (popups live outside `#movie_player`).
  - `harvest()` watch loop polls player state per video; consent/cookie walls usually
    appear at the FIRST navigation (inside `_resolve_video_urls`).
  - Verbose is ON by default via `_log()`; `--quiet` silences it.
- Coordinate mapping helper: `_capture.py::viewport_rect_to_image_bbox(rect, window_rect,
  toolbar_height, device_pixel_ratio, monitor_left, monitor_top)` and `BBox.to_yolo()`.
  Reusable for popup rects too — `_capture.py` does NOT need changes.
- Dataset layout: `ad_skipper/dataset/{images,labels,raw_boxes}/` (+ `debug/` when `--draw`);
  Phase 3 emits `dataset/yolo/{train,val}/{images,labels}` + `data.yaml`.

## 3. Existing pipeline (reference — already coded)
Concise, factual summary. For run commands see `PHASES_GUIDE.md`.

- Phase 1 `collect_ad_frames.py` (Selenium-driven harvester):
  headed Chrome (selenium 4 + webdriver-manager); detects ad via
  `#movie_player` class `ad-showing`/`ad-interrupting` or `getAdState()===1`;
  confirms skip button via `SKIP_BUTTON_SELECTORS`; grabs real desktop with `mss`;
  writes YOLO label directly from the skip button's `element.rect`; collects
  negatives/hard-negatives (`--neg-ratio`); group key `<session>_<adIdx>` to prevent
  split leakage; below-normal priority + phash dedup for low CPU / non-intrusive.
- Phase 2 `auto_label_skip_button.py` (OPTIONAL): regenerate/QA labels from `raw_boxes/`.
- Phase 3 `prepare_ad_dataset.py`: GROUP-AWARE train/val split (whole `<session>_<adIdx>`
  groups assigned to one split, never both) → `dataset/yolo/...` + `data.yaml`.
- Phase 4 `export_for_colab.py` + `Train_Skip_Ad_Colab.ipynb`: zip dataset with a
  Colab-relative `data.yaml`; train YOLO11n on Colab GPU; bring back `best.pt` as
  `models/skip_ad_yolo.pt`. Local fallback: `train_skip_model.py`.
- Phase 5 `youtube_ad_skipper.py`: load model; `mss` loop (same capture as training);
  cursor-preserving click; stability gate (≥2 consistent frames) + cooldown; `--dry-run`.

## 4. ACTIVE TASK — collect blocking popups as class 1 (`popup_dismiss_button`)

Goal: besides the skip button (class 0), also collect the DISMISS button of YouTube
blocking popups as YOLO samples under NEW class 1 (with bbox). Scope: YouTube Music
promo + Cookie/consent + login/Premium modals.

### Locked decisions (from user)
- Collect popups as data samples (not merely dismiss them).
- New class 1 `popup_dismiss_button`, with bbox; class 0 behavior unchanged.
- Defaults: `--collect-popups` ON, `--dismiss-popups` ON, `--frames-per-popup` = 3.
- Do NOT also save popups as skip-class negatives (keep it to class 1 only).

### Implementation steps
1. `ad_classes.txt`: append 2nd line `popup_dismiss_button` (⇒ nc=2 auto; prep/export unchanged).
2. `collect_ad_frames.py`:
   a. Add `POPUP_DISMISS_SELECTORS` (e.g. `yt-mealbar-promo-renderer #dismiss-button`,
      `tp-yt-paper-dialog` buttons, `ytd-popup-container #dismiss-button`, consent-form
      buttons) + `POPUP_DISMISS_TEXTS` (不用了 / No thanks / 拒絕全部 / Reject all).
   b. Add `_POPUP_STATE_JS`: scan document for the first VISIBLE dismiss button by selector
      OR button innerText; return `{present, rect, kind, toolbar, dpr}`. Add `_POPUP_CLICK_JS`
      to click that same button.
   c. `_save_frame()`: add `class_id: int = 0`; write `{class_id} cx cy w h`; record
      `class_id` in `raw_boxes` json. (Reuse `viewport_rect_to_image_bbox`; `_capture.py` unchanged.)
   d. Add `_maybe_collect_popup()`: grab frame → map rect→bbox → phash dedup → save class 1
      (group `<session>-popup-<hash>`, capped by `--frames-per-popup`) → if `--dismiss-popups`,
      click to unblock via `_dismiss_popup()` (`_POPUP_CLICK_JS`).
   e. Call `_maybe_collect_popup()` once after search navigation in `_resolve_video_urls`,
      and every iteration of the per-video watch loop. Count into `saved`; track `saved_popup`
      and include it in the final "Done" line.
   f. CLI: `--collect-popups` (default ON, `BooleanOptionalAction`),
      `--frames-per-popup` (default 3), `--dismiss-popups` (default ON).
   g. Add `[collect]` / `[popup]` verbose status logs.
3. `PHASES_GUIDE.md`: document class 1, the 3 new flags, outputs, acceptance (Phase 4+ = 2 classes).

### Verification
- `py_compile` `collect_ad_frames.py` AND `screen_event_recorder.py` (workspace baseline).
- `collect_ad_frames.py -h` shows `--collect-popups` / `--frames-per-popup` / `--dismiss-popups`.
- Headed live test (a profile that triggers the YouTube Music promo): produces
  `<session>-popup-*` image + label `1 cx cy w h` (all 0..1); `--draw` overlay boxes the
  dismiss button; clean exit, no lingering chrome.
- After `prepare_ad_dataset.py`: `data.yaml` shows `nc: 2` and both names.

### Risks / mitigations (popup-specific)
- Selector drift: dual match (selector + visible text) to survive YouTube renames.
- Mapping: popup rect is page-level (not player); use the same window_rect+toolbar+dpr
  mapping; verify with `--draw`.
- Dedup: popups are mostly static → phash dedup + per-popup cap avoid near-duplicate floods.

## 5. Conventions & constraints
- Branch policy: never edit on `main`; work on a `feature/YYYYMMDD-...` branch; no auto-merge.
- Dataset isolation: keep root `./A`, `./labels`, `classes.txt` clean; all new artifacts under `ad_skipper/`.
- Group-aware split is mandatory (near-duplicate frames must not span train+val).
- Harvest must stay non-intrusive (own Chrome window, below-normal priority, no global input).
- Train/inference must share the SAME capture path (`_capture.py`) so domains match.

## 6. Open risks (whole project)
- Skip-button selector drift → configurable selector list, validated on first run.
- Coordinate mapping under display scaling / multi-monitor → `--draw` verify + CDP fallback.
- False clicks → require negatives/hard-negatives + runtime stability gate.
- No-ad sessions yield no positives → loop videos until `--max-frames` reached.
