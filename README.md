# YOLO Dataset Auto Preparation / YOLO 資料集自動整理

## Purpose / 用途
This project provides `auto_prepare_dataset.py` to quickly convert raw images and YOLO label files into a training-ready folder layout for YOLO.

本專案提供 `auto_prepare_dataset.py`，可將原始圖片與 YOLO 標註快速整理成可直接訓練的資料夾結構。

## What The Script Does / 腳本會做什麼
- Reads images from `./A` (supports `.jpg`, `.png`, `.jpeg`).
- Reads label files from `./labels` (`.txt`, same basename as image).
- Reads class names from `./classes.txt`.
- Splits images into train/val with ratio `0.8 / 0.2`.
- Creates `./my_dataset/train|val/images|labels`.
- Generates `./my_dataset/data.yaml` using class count and class names.

- 從 `./A` 讀取圖片（支援 `.jpg`、`.png`、`.jpeg`）。
- 從 `./labels` 讀取標註檔（`.txt`，檔名需和圖片同名）。
- 從 `./classes.txt` 讀取類別名稱。
- 依 `0.8 / 0.2` 拆分 train/val。
- 建立 `./my_dataset/train|val/images|labels`。
- 依類別資訊自動產生 `./my_dataset/data.yaml`。

## Quick Run / 快速執行
From workspace root:

在專案根目錄執行：

```bat
python auto_prepare_dataset.py
```

If your environment uses a fixed Python path:

若你使用固定 Python 路徑：

```bat
C:\Users\User\miniconda3\python.exe auto_prepare_dataset.py
```

## Input & Output / 輸入與輸出
Input (required):

必要輸入：
- `A/` image files
- `labels/` YOLO txt labels
- `classes.txt` class list (one class per line)

Output:

輸出結果：
- `my_dataset/train/images`
- `my_dataset/train/labels`
- `my_dataset/val/images`
- `my_dataset/val/labels`
- `my_dataset/data.yaml`

## Notes / 注意事項
- `classes.txt` is required. If missing, the script exits immediately.
- The split uses random shuffle without a fixed seed, so train/val sets may differ each run.
- The script copies files instead of moving them.
- If an image has no matching label file, only the image is copied.

- `classes.txt` 為必要檔案，缺少時腳本會直接結束。
- 使用隨機打散且未固定 seed，因此每次 train/val 可能不同。
- 腳本是「複製」檔案，不會移動原始資料。
- 若圖片沒有對應標註，該圖片仍會被複製，但不會有 label。

## Event + MP4 Auto Label Preview / 事件 + 影片自動標註預覽

新增 `auto_label_from_events.py`，可將 `recordings/events_*.json` 與 `recordings/screen_*.mp4` 對齊後，抽取事件附近影格，呼叫 `tools/autolabel.py` 產生 LabelMe，並輸出 YOLO 標註到預覽資料夾。

### Quick Run / 快速執行

```bat
C:\Users\User\miniconda3\python.exe auto_label_from_events.py ^
	--events-json recordings/events_20260430_214417.json ^
	--video recordings/screen_20260430_214417.mp4 ^
	--output-dir recordings/auto_labels_preview
```

### Output / 輸出

- `recordings/auto_labels_preview/images`：抽出的事件附近影格
- `recordings/auto_labels_preview/annotations_labelme`：LabelMe JSON
- `recordings/auto_labels_preview/labels`：YOLO TXT
- `recordings/auto_labels_preview/reports/manifest.csv`：逐樣本清單
- `recordings/auto_labels_preview/reports/run_report.json`：執行摘要

### Useful Options / 常用參數

- `--window-before-ms`、`--window-after-ms`：事件前後抽幀時間窗
- `--max-frames-per-event`：每個事件最多抽樣幀數
- `--label-policy local-topk|fixed`：類別策略（本地 Top-k 投票或固定類別）
- `--skip-autolabel`：只抽幀與產生報表，不跑 ONNX 推論

## SerpApi Image Search Example / SerpApi 圖片搜尋範例

新增 `serpapi_image_search_example.py`，可用 SerpApi 的 Google Images 端點進行圖片搜尋。

### Set API Key On Windows / Windows 設定 API Key

Temporary for current PowerShell session (effective until terminal closes):

目前 PowerShell 視窗暫時生效（關閉終端後失效）：

```powershell
$env:SERPAPI_API_KEY="your_key"
```

Persist for current user:

設定為目前使用者永久生效：

```bat
setx SERPAPI_API_KEY "your_key"
```

Persist for machine (Administrator required):

設定為整台電腦永久生效（需系統管理員權限）：

```bat
setx SERPAPI_API_KEY "your_key" /M
```

Verify:

驗證是否設定成功：

```powershell
echo $env:SERPAPI_API_KEY
```

```bat
echo %SERPAPI_API_KEY%
```

> Note: `setx` writes to registry. Open a new terminal window to read updated values.
>
> 注意：`setx` 會寫入登錄，需開啟新的終端機視窗才會讀到新值。

### Quick Run / 快速執行

```bat
C:\Users\User\miniconda3\python.exe serpapi_image_search_example.py "cat meme" --num 5
```

Optional JSON output:

可選擇輸出完整 JSON：

```bat
C:\Users\User\miniconda3\python.exe serpapi_image_search_example.py "cat meme" --num 5 --save-json serpapi_result.json
```

## Pending Test Items / 待測試項目

- `https://postimg.cc`
- `https://serpapi.com/google-reverse-image`

可用於後續驗證圖片上傳與反向搜圖流程。

## Postimages Playwright Upload / Postimages 瀏覽器自動上傳

`upload_to_postimg.py` 透過 Playwright 操作 Postimages 網頁流程來上傳圖片。

### Setup / 安裝

```bat
C:\Users\User\miniconda3\python.exe -m pip install -r requirements.txt
C:\Users\User\miniconda3\python.exe -m playwright install chromium
```

### Quick Run / 快速執行

```bat
C:\Users\User\miniconda3\python.exe upload_to_postimg.py path\to\image.png
```

若要看到瀏覽器畫面：

```bat
C:\Users\User\miniconda3\python.exe upload_to_postimg.py path\to\image.png --show-browser
```

## Google Reverse Image Search / Google 反向圖片搜尋 (google-search-results.py)

`google-search-results.py` 自動上傳本地圖片到 Postimages，並透過 SerpApi 進行 Google Lens 反向搜尋，最後分析搜尋結果中最常見的標題或關鍵詞。

### Setup / 安裝

首先設定 SerpApi API Key（見上方 SerpApi 章節）：

```powershell
$env:SERPAPI_API_KEY="your_serpapi_key"
```

或永久設定：

```bat
setx SERPAPI_API_KEY "your_serpapi_key"
```

### Quick Run / 快速執行

預設使用 `A/frame_00000.jpg`：

```bat
C:\Users\User\miniconda3\python.exe google-search-results.py
```

指定不同的本地圖片：

```bat
set LOCAL_IMAGE_PATH=path\to\your\image.png
C:\Users\User\miniconda3\python.exe google-search-results.py
```

或使用環境變數一行執行：

```powershell
$env:LOCAL_IMAGE_PATH="A/frame_00001.jpg"; & 'C:\Users\User\miniconda3\python.exe' google-search-results.py
```

### 流程說明

1. **上傳本地圖片** — 使用 Playwright 自動化流程上傳到 Postimages
2. **Google Lens 搜尋** — 透過 SerpApi 取得視覺相似的搜尋結果
3. **分析結果標題** — 提取最常見的標題或關鍵詞（超過 3 個字元）
4. **自動清理** — 搜尋完成後自動刪除 Postimages 上傳的圖片

### Output / 輸出

```json
{
  "result": "top_keyword_or_title",
  "count": 3,
  "mode": "keyword",
  "sample_titles": ["Title 1", "Title 2", "Title 3"]
}
```

- `result`: 最常重複出現的標題或關鍵詞
- `count`: 出現次數
- `mode`: 分析模式 (`exact_title`, `keyword`, `no_titles`, `fallback_title`)
- `sample_titles`: 包含該關鍵詞的示例標題
