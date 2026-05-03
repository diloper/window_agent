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

- `--events-json`：事件 JSON
- `--video`：對應 MP4
- `--output-dir`：輸出資料夾，可省略
- `--label-policy`：類別策略，支援 `crop-search-direct`、`serpapi-topk` 或 `fixed`
- `--class-file`：候選類別檔，預設 `classes.txt`
- `--serpapi-api-key`：SerpApi 金鑰，也可從環境變數或 `.env` 讀取
- `--encoder` / `--decoder`：SAM/SAM2 ONNX 模型

### 2. 載入環境變數

`load_dotenv_file()` 會讀 `.env`，把尚未存在於環境中的變數寫入 `os.environ`。

目前主要用來補 `SERPAPI_API_KEY`。

### 3. 檢查事件檔與影片是否屬於同一場錄製

`ensure_matching_session()` 會從檔名抓時間戳，例如：

- `events_20260501_165101.json`
- `screen_20260501_165101.mp4`

若時間戳不同，程式直接報錯並停止。

### 4. 載入滑鼠事件

`load_mouse_events()` 只保留：

- `mouse_press`
- `mouse_release`

也會依 `--button` 過濾滑鼠按鍵，並把事件時間換算成相對於影片起點的秒數。

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
- 輸出到 `images/`
- 預先決定對應的 LabelMe JSON 路徑

輸出檔名格式類似：

`event_0001_mouse_press_f000112_x636_y700.jpg`

### 7. 執行自動標註

`run_autolabel_for_sample()` 會呼叫：

- `tools/autolabel.py`

並傳入：

- 圖片路徑
- encoder / decoder ONNX
- 滑鼠座標點
- 輸出模式
- 輸出 JSON 路徑

如果成功：

- `sample.status = "ok"`

如果失敗：

- `sample.status = "failed"`
- `sample.error` 會記錄錯誤訊息

## 類別命名流程

### 1. crop-search-direct

這是目前新增的主要命名流程。

當 `run_autolabel_for_sample()` 成功產生 LabelMe JSON 後，程式會：

- 讀取第一個 shape 的 points
- 轉成外接框 bbox
- 從原始 frame 裁出目標區域
- 依比例縮放，限制在 `640x480` 內，不補黑邊
- 將裁切圖輸出到 `crops/`
- 把裁切圖交給 `google-search-results.py` 做 Google Lens 分析
- 取 `top_repetition_result["result"]` 作為最終 label

若搜尋結果為空、API 不可用或裁切失敗，則退回 `--fixed-label`。

### 2. serpapi-topk

這是舊版策略。若有 SerpApi 金鑰，程式會使用 `SerpApiClassProvider`，把 `classes.txt` 當作候選類別清單，依搜尋結果中的 token overlap 做分數比對與事件投票。

### 3. fixed

所有事件都直接套用 `--fixed-label`。

### 4. `search_images()` 來源

目前 `auto_label_from_events.py` 不再引用舊的 `serpapi_image_search_example.py`。

現在是靜態載入：

- `google-search-results.py`

程式在匯入階段就透過 `importlib.util.spec_from_file_location()` 載入這支檔案，並重用其中的 Google Lens 分析 helper。

## 標註後處理

### 1. 回寫 LabelMe 類別

`relabel_annotation()` 會把 LabelMe JSON 內每個 shape 的 `label` 改成推論出的事件類別。

### 2. 匯出 YOLO

`export_yolo()` 會：

- 讀取 LabelMe JSON
- 取出 shape points
- 算出外接框
- 正規化成 YOLO `cx cy w h`
- 寫入 `labels/*.txt`

### 3. 輸出報表

程式最後會輸出：

- `classes_preview.txt`
- `reports/manifest.csv`
- `reports/run_report.json`

`manifest.csv` 會額外記錄：

- `crop_path`
- `crop_width`
- `crop_height`
- `search_label`
- `search_status`

## 輸出目錄結構

預設輸出目錄：

`recordings/auto_labels_preview_<video_stem>`

裡面包含：

- `images/`：抽出的影格
- `annotations_labelme/`：LabelMe JSON
- `crops/`：依第一個 shape 裁出的搜尋用圖片
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

### 5. `classes.txt` 沒內容或不存在

若候選類別為空，舊的 `serpapi-topk` 會退回只使用 fallback label。

### 6. 標註框無效或裁切失敗

若 LabelMe JSON 沒有 shape、第一個 shape 無法轉成有效 bbox，或裁切區域為空，樣本會退回 fallback label。

## 範例指令

```bat
R:\Users\User\miniconda3\python.exe auto_label_from_events.py ^
  --events-json recordings\events_20260501_165101.json ^
  --video recordings\screen_20260501_165101.mp4 ^
  --label-policy crop-search-direct
```

## 目前適用版本說明

依目前專案狀態，這支程式的關鍵依賴關係如下：

- 使用 `google-search-results.py` 提供 Google Lens 圖片分析與可重用 helper
- 使用 `tools/autolabel.py` 執行 ONNX 自動標註
- 若要用 PaddleOCR 相關流程，則是由 `google-search-results.py` 間接使用 `easyocr_checker.py`

## 範例指令

```bat
R:\Users\User\miniconda3\python.exe auto_label_from_events.py ^
  --events-json recordings\events_20260501_165101.json ^
  --video recordings\screen_20260501_165101.mp4 ^
  --label-policy serpapi-topk
```
  --label-policy crop-search-direct
## 目前適用版本說明

依目前專案狀態，這支程式的關鍵依賴關係如下：

- 使用 `google-search-results.py` 提供 Google Lens 圖片分析與可重用 helper
- 使用 `tools/autolabel.py` 執行 ONNX 自動標註
- 若要用 PaddleOCR 相關流程，則是由 `google-search-results.py` 間接使用 `easyocr_checker.py`
