# auto_label_from_events.py 說明

## 用途

`auto_label_from_events.py` 會把錄製事件檔與螢幕錄影對齊，抽出滑鼠事件對應的影格，呼叫 `tools/autolabel.py` 產生 LabelMe 標註，再依標註框從原圖裁切目標區域、做等比縮放，最後透過 `google-search-results.py` 的 Google Lens 分析結果直接命名，並轉成 YOLO 格式。

適合用在：

- 已經有 `recordings/events_*.json`
- 已經有 `recordings/screen_*.mp4`
- 想快速得到一份可檢查的預覽標註資料夾

## 主要流程

### 1. 讀取參數

程式先從命令列讀取：

- `--video`：對應 MP4（必填）
- `--events-json`：事件檔（NDJSON，一行一筆事件；可省略，預設自動推導與 `--video` 同場錄製的檔名）
- `--output-dir`：輸出資料夾，可省略
- `--label-policy`：類別策略，支援 `crop-search-direct`、`genai-marked-direct`、`serpapi-topk` 或 `fixed`（預設為 `genai-marked-direct`）
- `--class-file`：候選類別檔，預設 `classes.txt`
- `--serpapi-api-key`：SerpApi 金鑰，也可從環境變數或 `.env` 讀取
- `--encoder` / `--decoder`：SAM/SAM2 ONNX 模型
- `--enable-class-mapping`：明確啟用類別名稱統一（當 `class_mapping_reference.md` 存在時會自動啟用）
- `--disable-class-mapping`：明確禁用類別名稱統一（即使映射文件存在）
- `--class-mapping-file`：指定映射參考文件路徑（默認 `class_mapping_reference.md`）
- `--auto-update-mapping`：自動更新映射參考文件（默認 True）

### 2. 載入環境變數

`load_dotenv_file()` 會讀 `.env`，把尚未存在於環境中的變數寫入 `os.environ`。

目前主要用來補 `SERPAPI_API_KEY`、`GOOGLE_API_KEY` 或 `GEMINI_API_KEY`。

### 3. 檢查事件檔與影片是否屬於同一場錄製

`ensure_matching_session()` 會從檔名抓時間戳，例如：

- `events_20260501_165101.json`
- `screen_20260501_165101.mp4`

若時間戳不同，程式直接報錯並停止。

### 4. 載入滑鼠事件

`load_mouse_events()` 只保留：

- `mouse_press`
- `mouse_release`

也會依 `--button` 過濾滑鼠按鍵。事件中的 `timestamp` 需為「相對錄影起點秒數（float）」；程式會直接用此秒數對齊影片。

若同場錄製存在 `frames_YYYYMMDD_HHMMSS.jsonl`（每幀時間軸 sidecar），程式會優先用它做「事件時間 → 最近幀」對齊；找不到或格式不符時才 fallback 到 `fps` 推算。

事件檔格式為 NDJSON（每行一個 JSON 物件），例如：

```json
{"type":"mouse_press","button":"left","x":482,"y":250,"timestamp":2.064162}
{"type":"mouse_release","button":"left","x":482,"y":250,"timestamp":2.158208}
```

錄影開始時還會包含 `sync_marker_start` / `sync_marker_end` 事件，供校準使用；`auto_label_from_events.py` 會自動忽略非滑鼠事件。

> 注意：舊版「JSON 陣列 + ISO 時間字串」格式已不支援。

### 5. 建立抽幀計畫

`build_frame_plan()` 依據：

- 影片 FPS
- 影片總幀數
- `--window-before-ms`
- `--window-after-ms`
- `--max-frames-per-event`

決定每個事件要抽哪些 frame。

預設情況下，事件前後視窗都是 0，所以每個事件通常只抽事件當下那一幀。

### 6. 抽出圖片

`extract_sample_frames()` 會：

- 從影片讀取指定 frame
- 輸出原始未標記圖片到 `images/`
- 預先決定對應的 LabelMe JSON 路徑

輸出檔名格式類似：

`event_0001_mouse_press_f000112_x636_y700.jpg`

### 7. 依 special_mode 分流標註

程式會先解析 `events_*.json` 的：

- `special_mode_enter`
- `special_mode_exit`

建立 special_mode 時間區間，之後每個 sample 依事件 timestamp 分流：

1. 在 special_mode 區間內：

- 跳過 `tools/autolabel.py` 推理
- 直接用同一組 `mouse_press + mouse_release` 座標產生 rectangle 標註
- 同步產生整張標記圖 `<annotation_stem>_marked.jpg`（紅色實線框）

2. 離開 special_mode 區間後：

- 恢復原本 `run_autolabel_for_sample()` 流程
- 呼叫 `tools/autolabel.py` 產生標註與 marked 圖

共同結果（兩種路徑都一致）：

- 成功時 `sample.status = "ok"`
- 失敗時 `sample.status = "failed"`，並將原因寫入 `sample.error`
- 標記圖會輸出到 `marked/`，與 `images/` 原圖分開存放

## 類別命名流程

### 1. crop-search-direct

這是目前新增的主要命名流程。

當 sample 成功產生 LabelMe JSON（不論來源是 autolabel 或 special_mode 直出）後，程式會：

- 讀取第一個 shape 的 points
- 轉成外接框 bbox
- 從原始 frame 裁出目標區域
- 依比例縮放，限制在 `640x480` 內，不補黑邊
- 將裁切圖輸出到 `crops/`
- 把裁切圖交給 `google-search-results.py` 做 Google Lens 分析
- 取 `top_repetition_result["result"]` 作為最終 label

若搜尋結果為空、API 不可用或裁切失敗，則退回 `--fixed-label`。

### 2. serpapi-topk

### 2. genai-marked-direct

這是新的 marked image 命名流程。

當 sample 成功產生 `marked/<annotation_stem>_marked.jpg`（不論來源是 autolabel 或 special_mode 直出）後，程式會：

- 直接讀取整張 marked image
- 呼叫 `genai.py` 內的 Gemini 多模態分析函式
- 要求模型觀察紅色框出的 UI 元件並回傳簡短名稱
- 若模型回傳有效文字，直接作為最終 label

若缺少 `GOOGLE_API_KEY` / `GEMINI_API_KEY`、marked image 不存在、模型回傳 `NULL` 或分析失敗，則退回 `--fixed-label`。

### 3. serpapi-topk

這是舊版策略。若有 SerpApi 金鑰，程式會使用 `SerpApiClassProvider`，把 `classes.txt` 當作候選類別清單，依搜尋結果中的 token overlap 做分數比對與事件投票。

### 4. fixed

所有事件都直接套用 `--fixed-label`。

### 5. ImageHash 相似圖分群與標註同步

當每個 sample 完成初始標註與類別名稱統一後，程式會再執行一個後處理步驟：

- 讀取 `images/` 下的每張圖片
- 使用 `ImageHash` 的 `phash` 計算圖片雜湊值
- 以 `--similarity-threshold`（預設 `0.9`）把相似圖片分成同一群
- 蒐集群組內所有 annotation 的 labels 及其座標作為模板
- 將群組內「其他圖片的 labels」互相抄寫（抄寫前會先檢查目標座標，避免重複覆蓋已存在的標記）
- 匯出群組報告到 `reports/similarity_groups.json` 與 `reports/similarity_groups.csv`

這個步驟的目標是讓重複或近似畫面維持一致標註，避免同一組 UI 片段出現不同 label。

### 5. `search_images()` 來源

目前 `auto_label_from_events.py` 不再引用舊的 `serpapi_image_search_example.py`。

現在是靜態載入：

- `google-search-results.py`

程式在匯入階段就透過 `importlib.util.spec_from_file_location()` 載入這支檔案，並重用其中的 Google Lens 分析 helper。

## 標註後處理

### 1. 類別名稱統一（自動啟用）

**自 2026-05-27 起新增功能**

**重要提示**：當工作區存在 `class_mapping_reference.md` 時，程式會**自動啟用**類別名稱統一功能。如需明確禁用，可使用 `--disable-class-mapping` 參數。

程式會在標註完成後自動統一類別名稱，避免語意相同但寫法不同的類別重複出現。

#### 啟用方式

1. **自動啟用**（推薦）：確保工作區根目錄存在 `class_mapping_reference.md`，程式會自動偵測並啟用
2. **明確啟用**：使用 `--enable-class-mapping` 參數
3. **明確禁用**：使用 `--disable-class-mapping` 參數（優先級最高）

#### 工作原理

1. **加載映射參考**：從 `--class-mapping-file`（預設 `class_mapping_reference.md`）讀取已建立的類別映射表
2. **應用映射**：將所有樣本的 `inferred_label` 統一為標準名稱
3. **重新標註**：更新 LabelMe JSON 和 YOLO 標籤文件
4. **自動更新參考**：調用 `analyze_classes.py` 分析新類別並增量更新映射表

#### 映射規則

- **語言**：優先使用英文名稱（避免中文或雙語混用）
- **大小寫**：採用 sentence case（如 "Dropdown menu"）
- **保護已有映射**：現有統一名稱不會被更改
- **增量合併**：新變體自動歸類到對應的現有映射

#### 輸出效果

**未啟用映射時**：
```
classes_preview.txt:
- 確定 button
- OK button
- 確定 (OK) button
- Cancel
- 取消
```

**啟用映射後**：
```
classes_preview.txt:
- OK button
- Cancel button
```

#### 日誌輸出範例

```
[INFO] Loading class name mappings from: class_mapping_reference.md
[INFO] Found 20 unified class names in reference
[INFO] Built mapping index with 65 original name variants
[MAP] '確定 button' -> 'OK button'
[MAP] 'OK button' -> 'OK button'
[MAP] '確定 (OK) button' -> 'OK button'
[MAP] '取消' -> 'Cancel button'
[INFO] Applied mapping to 15 samples
[INFO] Auto-updating class mapping reference: class_mapping_reference.md
[INFO] Updated mapping reference with 22 unified classes
```

#### 相關文件

- `class_mapping_reference.md`：映射參考文件，增量更新
- `analyze_classes.py`：類別分析工具，自動調用
- `analyze_classes.md`：詳細說明映射機制

### 2. 回寫 LabelMe 類別

`relabel_annotation()` 會把 LabelMe JSON 內每個 shape 的 `label` 改成推論出的事件類別。

### 3. 匯出 YOLO

`export_yolo()` 會：

- 讀取 LabelMe JSON
- 取出 shape points
- 算出外接框
- 正規化成 YOLO `cx cy w h`
- 寫入 `labels/*.txt`

### 4. 輸出報表

程式最後會輸出：

- `classes_preview.txt`
- `reports/manifest.csv`
- `reports/similarity_groups.json`
- `reports/similarity_groups.csv`
- `reports/run_report.json`

`manifest.csv` 會額外記錄：

- `crop_path`
- `crop_width`
- `crop_height`
- `search_label`
- `search_status`

其中當 `--label-policy genai-marked-direct` 時，`search_status` 可能出現：

- `genai_marked_ok`
- `missing_genai_api_key`
- `missing_marked_image`
- `genai_null`
- `genai_failed`

## 輸出目錄結構

預設輸出目錄：

`recordings/auto_labels_preview_<video_stem>`

裡面包含：

- `images/`：抽出的原始影格（未標記）
- `marked/`：整張圖紅色實線框預覽
- `annotations_labelme/`：LabelMe JSON
- `crops/`：依第一個 shape 裁出的搜尋用圖片（`crop-search-direct` 使用）
- `labels/`：YOLO TXT
- `reports/manifest.csv`：逐樣本清單
- `reports/run_report.json`：執行摘要
- `classes_preview.txt`：本次輸出的類別清單

## 常見失敗點

### 1. 事件檔與影片檔時間戳不一致

會在 `ensure_matching_session()` 直接報錯。

### 2. 缺少 ONNX 模型

若 `--encoder` 或 `--decoder` 不存在，程式會停止。

### 3. 缺少 `onnxruntime`

`tools/autolabel.py` 啟動時需要 `onnxruntime`。

### 4. 沒有 `SERPAPI_API_KEY`

若選 `crop-search-direct` 或 `serpapi-topk` 但沒提供金鑰，程式會退回固定類別策略。

### 5. 沒有 `GOOGLE_API_KEY` / `GEMINI_API_KEY`

若選 `genai-marked-direct` 但沒提供 Gemini API 金鑰，程式會退回固定類別策略。

### 6. `classes.txt` 沒內容或不存在

若候選類別為空，舊的 `serpapi-topk` 會退回只使用 fallback label。

### 7. 標註框無效或裁切失敗

若 LabelMe JSON 沒有 shape、第一個 shape 無法轉成有效 bbox，或裁切區域為空，樣本會退回 fallback label。

### 8. 映射參考文件無效

若啟用 `--enable-class-mapping` 但 `--class-mapping-file` 不存在或格式錯誤，程式會記錄警告並繼續使用原始類別名稱。

## 範例指令

### 基本用法（自動啟用類別統一）

```bat
python auto_label_from_events.py ^
  --video recordings\screen_20260501_165101.mp4
```

**注意**：如果工作區存在 `class_mapping_reference.md`，類別名稱統一功能會自動啟用。

### 使用 crop-search-direct 策略

```bat
python auto_label_from_events.py ^
  --video recordings\screen_20260501_165101.mp4 ^
  --label-policy crop-search-direct
```

如未指定 `--events-json`，程式會自動推導 `recordings/events_YYYYMMDD_HHMMSS.json`（與 `--video` 檔名時間戳一致）。
若有特殊需求仍可手動指定 `--events-json`。

### 使用 Gemini 分析 marked image

```bat
python auto_label_from_events.py ^
  --video recordings\screen_20260501_165101.mp4 ^
  --label-policy genai-marked-direct
```

此模式需先提供 `GOOGLE_API_KEY` 或 `GEMINI_API_KEY`。

### 明確啟用類別名稱統一

```bat
python auto_label_from_events.py ^
  --video recordings\screen_20260501_165101.mp4 ^
  --label-policy genai-marked-direct ^
  --enable-class-mapping
```

此模式會：
- 在標註完成後統一類別名稱
- 自動更新 `class_mapping_reference.md`
- 移除重複的類別變體

**註**：當映射文件存在時，此參數可省略（會自動啟用）。

### 禁用類別名稱統一

```bat
python auto_label_from_events.py ^
  --video recordings\screen_20260501_165101.mp4 ^
  --disable-class-mapping
```

使用此參數可明確禁用類別統一功能，即使 `class_mapping_reference.md` 存在。

### 自定義映射文件路徑

```bat
python auto_label_from_events.py ^
  --video recordings\screen_20260501_165101.mp4 ^
  --class-mapping-file custom_mapping.md
```

**註**：如果指定的映射文件存在，會自動啟用類別統一功能。

### 禁用自動更新映射參考

```bat
python auto_label_from_events.py ^
  --video recordings\screen_20260501_165101.mp4 ^
  --enable-class-mapping ^
  --no-auto-update-mapping
```

### 完整參數範例

```bat
python auto_label_from_events.py ^
  --video recordings\screen_20260501_165101.mp4 ^
  --events-json recordings\events_20260501_165101.json ^
  --output-dir my_output ^
  --label-policy genai-marked-direct ^
  --class-mapping-file class_mapping_reference.md ^
  --encoder model\sam2_hiera_tiny_encoder.onnx ^
  --decoder model\sam2_hiera_tiny_decoder.onnx ^
  --output-mode rectangle
```

**註**：因為指定了 `--class-mapping-file` 且該文件存在，類別統一功能會自動啟用，無需明確指定 `--enable-class-mapping`。

## 目前適用版本說明

依目前專案狀態，這支程式的關鍵依賴關係如下：

- 使用 `google-search-results.py` 提供 Google Lens 圖片分析與可重用 helper
- 使用 `tools/autolabel.py` 執行 ONNX 自動標註
- 使用 `analyze_classes.py` 進行類別名稱統一分析（當 `--enable-class-mapping` 啟用時）
- 若要用 PaddleOCR 相關流程，則是由 `google-search-results.py` 間接使用 `easyocr_checker.py`

## 相關文件

- `README.md`：專案整體說明
- `analyze_classes.md`：類別名稱分析工具說明
- `class_mapping_reference.md`：類別映射參考文件
- `screen_event_recorder.py`：錄製事件與螢幕的工具
