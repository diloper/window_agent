# YouTube Skip-Ad YOLO — Phase 1 / 4 / 5 執行手冊

> 適用分支：`feature/20260626-yolo-ad-skipper`
> Python 一律使用專案虛擬環境直譯器：`R:\SAM\.venv\Scripts\python.exe`
> （直接打 `python` 會落到 WindowsApps stub，回傳 exit 9009）

本文件只涵蓋三個「需真實資源、需手動執行」的階段：

| 階段 | 目的 | 腳本 |
|---|---|---|
| Phase 1 | 自動收集廣告影格 + 自動產生 YOLO 標註 | `collect_ad_frames.py` |
| Phase 4 | 在 Google Colab（GPU）訓練 skip 按鈕模型 | `export_for_colab.py` + `Train_Skip_Ad_Colab.ipynb` |
| Phase 5 | 載入訓練好的模型，即時偵測並自動點擊「略過廣告」 | `youtube_ad_skipper.py` |

> Phase 2（標註複查）與 Phase 3（分組切分 train/val）為自動化中介步驟，已驗證可用；
> 流程：Phase 1 → (Phase 2 選用) → Phase 3 → Phase 4 → Phase 5。

---

## Phase 1 — 自動收集廣告影格

### 執行方式

**建議做法（不必關閉你平常的 Chrome）**：用一個**專供自動化的獨立 profile 資料夾**，
就不會跟正在執行的 Chrome 搶同一份設定檔（避免 profile lock）：

```powershell
Set-Location R:\SAM
R:\SAM\.venv\Scripts\python.exe ad_skipper\collect_ad_frames.py `
  --query "popular music video 2024" `
  --url-limit 15 `
  --profile "R:\SAM\ad_skipper\chrome_profile" `
  --max-frames 300 `
  --frames-per-ad 4 `
  --neg-ratio 0.4 `
  --vary-layout `
  --draw
```

> 首次執行會自動建立 `R:\SAM\ad_skipper\chrome_profile`（全新、未登入）。
> YouTube 在未登入狀態仍會播放廣告，足以收集 skip 按鈕影像。

**若一定要用你已登入的真實帳號**（如 `Profile 16`），必須**先完全關閉所有 Chrome 視窗**
（含背景程序），否則該設定檔被佔用會啟動失敗，再執行：

```powershell
Set-Location R:\SAM
R:\SAM\.venv\Scripts\python.exe ad_skipper\collect_ad_frames.py `
  --query "popular music video 2024" `
  --url-limit 15 `
  --profile "C:\Users\User\AppData\Local\Google\Chrome\User Data" `
  --profile-directory "Profile 16" `
  --max-frames 300 `
  --neg-ratio 0.4 `
  --vary-layout `
  --draw
```

> **多組帳號如何指定？** `--profile` 指向最外層的 `User Data` 父資料夾；
> `--profile-directory` 才是選哪個帳號，值要填**資料夾名稱**（如 `Profile 16`、`Default`），
> 不是 Chrome 內顯示的暱稱。不指定時預設用 `Default`。
>
> **常見錯誤** `SessionNotCreatedException: ... Chrome instance exited`：
> 代表目標設定檔正被另一個執行中的 Chrome 佔用（profile lock）。
> 解法：改用上面的獨立 `--profile` 資料夾，或先關閉所有 Chrome 再用真實帳號。

或指定明確影片網址：

```powershell
R:\SAM\.venv\Scripts\python.exe ad_skipper\collect_ad_frames.py `
  --urls "https://www.youtube.com/watch?v=XXXX" "https://www.youtube.com/watch?v=YYYY" `
  --max-frames 200
```

### 主要參數

| 參數 | 預設 | 說明 |
|---|---|---|
| `--urls` / `--query` | 二擇一（必填） | 影片來源：明確網址清單，或搜尋字串 |
| `--url-limit` | 15 | 由 `--query` 解析的最大影片數 |
| `--profile` | 無 | Chrome user-data-dir；用真實設定檔才有真實廣告 |
| `--profile-directory` | `Default` | 多帳號時選用的 profile 資料夾名稱（如 `Profile 16`） |
| `--monitor` | 1 | mss 螢幕索引（1 = 主螢幕） |
| `--poll-interval` | 0.4 | 播放器輪詢秒數 |
| `--max-frames` | 300 | 收集到此影格數即停止 |
| `--frames-per-ad` | 4 | 每段廣告擷取的影格數 |
| `--neg-ratio` | 0.4 | 目標負樣本（無廣告）比例 0..1 |
| `--per-video-seconds` | 120 | 單支影片最長觀看秒數 |
| `--vary-layout` | off | 隨機視窗大小/位置，增加資料多樣性 |
| `--headless` | off | 無頭模式（廣告較少，**不建議用於收集**） |
| `--draw` | off | 另存 bbox 疊圖供人工檢視 |
| `--session-id` | 時間戳 | 分組鍵（group key），避免 train/val 洩漏 |

### 產出

- `ad_skipper/dataset/images/*.png` — 影格
- `ad_skipper/dataset/labels/*.txt` — YOLO 格式標註（class 0 = `skip_ad_button`）
- `ad_skipper/dataset/raw_boxes/*.json` — 含 `group` 鍵的原始框資訊
- `--draw` 時另存疊圖除錯影像

### 驗收標準

- [ ] 指令正常結束（Ctrl+C 中止回傳 130 並保留已收資料，屬正常）。
- [ ] `dataset/images/` 與 `dataset/labels/` 影格與標註**數量一一對應**。
- [ ] 正樣本標註檔內含一行 `0 cx cy w h`，數值皆正規化在 `[0,1]`。
- [ ] 負樣本（無廣告）對應的 `.txt` 為**空檔**，且整體負樣本比例接近 `--neg-ratio`。
- [ ] 隨機抽查 `--draw` 疊圖，紅框準確框住「略過廣告」按鈕。
- [ ] 不同影片/廣告的檔名前綴帶有不同 `group` 鍵（`<session>_<adIdx>`）。
- [ ] 收集期間未明顯卡住使用者操作（低優先權執行，CPU 未長期飽和）。

> 收集完成後接 Phase 3 切分資料：
> `R:\SAM\.venv\Scripts\python.exe ad_skipper\prepare_ad_dataset.py --train-ratio 0.8`
> 產出 `ad_skipper/dataset/yolo/{train,val}` 與 `data.yaml`，且**同一 group 不跨 train/val**。

---

## Phase 4 — 在 Google Colab 訓練模型

> 訓練在 Colab（GPU）非本地執行。本地僅負責打包資料集。

### 步驟 1：本地打包資料集（先完成 Phase 3）

```powershell
Set-Location R:\SAM
R:\SAM\.venv\Scripts\python.exe ad_skipper\export_for_colab.py
```

| 參數 | 預設 | 說明 |
|---|---|---|
| `--colab-dir` | `/content/ad_skipper_dataset` | 解壓後在 Colab 的路徑（寫入 data.yaml 的 `path`） |
| `--output` | `ad_skipper/ad_skipper_dataset.zip` | 輸出 zip 路徑 |

產出 `ad_skipper/ad_skipper_dataset.zip`，內含 `train/`、`val/` 與 Colab 版 `data.yaml`（`path: /content/ad_skipper_dataset`）。

### 步驟 2：在 Colab 訓練

1. 開啟 [Google Colab](https://colab.research.google.com/)，上傳並開啟 `ad_skipper/Train_Skip_Ad_Colab.ipynb`。
2. 執行階段 → 變更執行階段類型 → **GPU**。
3. 依 notebook 區段依序執行：
   - `nvidia-smi`（確認 GPU）
   - `pip install ultralytics`
   - 上傳 `ad_skipper_dataset.zip` 並解壓到 `/content/ad_skipper_dataset`
   - （選用）掛載 Google Drive
   - 訓練 YOLO11n（`epochs=100, imgsz=640, batch=16`）
   - 驗證（mAP）
   - 下載 `best.pt` 並另存為 `skip_ad_yolo.pt`
4. 將下載的 `skip_ad_yolo.pt` 放到 `R:\SAM\ad_skipper\models\skip_ad_yolo.pt`。

> 本地備援（若有本機 GPU）：
> `R:\SAM\.venv\Scripts\python.exe ad_skipper\train_skip_model.py --epochs 100 --imgsz 640 --batch 16`
> 訓練後會自動把 `best.pt` 複製成 `ad_skipper/models/skip_ad_yolo.pt`。

### 驗收標準

- [ ] `ad_skipper_dataset.zip` 根目錄含 `train/`、`val/`、`data.yaml`，且 `data.yaml` 的 `path` 為 Colab 路徑。
- [ ] Colab 確實取得 GPU（`nvidia-smi` 有輸出）。
- [ ] 訓練完成且 `runs/.../weights/best.pt` 存在。
- [ ] 驗證 mAP 達可用門檻（建議 `mAP50 ≥ 0.8`，依資料量調整）。
- [ ] 取得 `skip_ad_yolo.pt` 並放入 `ad_skipper/models/`。

---

## Phase 5 — 即時偵測並自動點擊「略過廣告」

> 需先有 `ad_skipper/models/skip_ad_yolo.pt`（Phase 4 產出）。

### 執行方式

先用 `--dry-run` 觀察（只記錄、不點擊）：

```powershell
Set-Location R:\SAM
R:\SAM\.venv\Scripts\python.exe ad_skipper\youtube_ad_skipper.py --dry-run
```

確認偵測穩定後，正式啟用自動點擊：

```powershell
R:\SAM\.venv\Scripts\python.exe ad_skipper\youtube_ad_skipper.py `
  --model ad_skipper\models\skip_ad_yolo.pt `
  --monitor 1 `
  --conf 0.5
```

### 主要參數

| 參數 | 預設 | 說明 |
|---|---|---|
| `--model` | `models/skip_ad_yolo.pt` | 訓練好的權重路徑 |
| `--monitor` | 1 | mss 螢幕索引（1 = 主螢幕） |
| `--interval` | 0.5 | 兩次偵測間隔秒數 |
| `--conf` | 0.5 | 偵測信心門檻 |
| `--stable-frames` | 2 | 連續穩定偵測幾次才點擊 |
| `--stable-px` | 25 | 中心點最大漂移（超過視為不穩定） |
| `--cooldown` | 2.0 | 兩次點擊最小間隔秒數 |
| `--dry-run` | off | 只記錄偵測，不實際點擊 |

### 行為說明

- 偵測需連續 `--stable-frames` 次且中心漂移在 `--stable-px` 內才觸發點擊（避免誤點）。
- 點擊採「保留游標」方式：點擊後還原滑鼠原位置，盡量不干擾使用者。
- `Ctrl+C` 可安全結束。

### 驗收標準

- [ ] 模型不存在時，乾淨回傳 exit code 2 並提示路徑。
- [ ] `--dry-run` 在廣告出現時於 log 顯示偵測到 skip 按鈕，且座標落在按鈕範圍。
- [ ] 正式模式下，廣告可略過時於 `--cooldown` 內**自動點擊一次**並成功略過。
- [ ] 點擊後滑鼠游標回到原本位置，未明顯干擾使用者操作。
- [ ] 無廣告 / 不可略過時不誤點。
- [ ] `Ctrl+C` 可正常中止，無未處理例外。

---

## 附錄：環境前置

```powershell
Set-Location R:\SAM
R:\SAM\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

所需套件（已列於 `requirements.txt` / `pyproject.toml`）：
`ultralytics`、`selenium`、`webdriver-manager`、`mss`、`imagehash`、`psutil`、`pydirectinput`、`opencv-python`、`easyocr`（選用備援）。
