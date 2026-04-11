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
