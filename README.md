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
