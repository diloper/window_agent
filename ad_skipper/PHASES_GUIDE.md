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
| Phase 6 | 登入自動啟動 + 僅在 YouTube 影片(非 Shorts)時偵測 | `install_autostart.ps1`、`_active_url.py` |

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
  --query "popular music video " `
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
| `--collect-popups` | on | 同時收集 YouTube 阻擋彈窗的「關閉鍵」作為 class 1（`--no-collect-popups` 關閉） |
| `--frames-per-popup` | 3 | 每個彈窗實例擷取的影格數 |
| `--dismiss-popups` | on | 擷取後點擊關閉鍵以解除阻擋（`--no-dismiss-popups` 只收集不點擊） |
| `--quiet` | off | 關閉狀態輸出（**預設為 verbose**，會持續印出 `[collect]` 目前狀態） |
| `--session-id` | 時間戳 | 分組鍵（group key），避免 train/val 洩漏 |

### 產出

- `ad_skipper/dataset/images/*.png` — 影格
- `ad_skipper/dataset/labels/*.txt` — YOLO 格式標註（class 0 = `skip_ad_button`；class 1 = `popup_dismiss_button`）
- `ad_skipper/dataset/raw_boxes/*.json` — 含 `group`、`class_id` 鍵的原始框資訊
- `--draw` 時另存疊圖除錯影像
- 彈窗樣本檔名前綴為 `<session>-popup-<hash>`，標註行為 `1 cx cy w h`

### 驗收標準

- [ ] 指令正常結束（Ctrl+C 中止回傳 130 並保留已收資料，屬正常）。
- [ ] `dataset/images/` 與 `dataset/labels/` 影格與標註**數量一一對應**。
- [ ] 正樣本標註檔內含一行 `0 cx cy w h`，數值皆正規化在 `[0,1]`。
- [ ] 負樣本（無廣告）對應的 `.txt` 為**空檔**，且整體負樣本比例接近 `--neg-ratio`。
- [ ] 隨機抽查 `--draw` 疊圖，紅框準確框住「略過廣告」按鈕。
- [ ] 不同影片/廣告的檔名前綴帶有不同 `group` 鍵（`<session>_<adIdx>`）。
- [ ] 收集期間未明顯卡住使用者操作（低優先權執行，CPU 未長期飽和）。
- [ ] 若觸發 YouTube 阻擋彈窗，產生 `<session>-popup-*` 影格，標註行為 `1 cx cy w h`（class 1）。
- [ ] Phase 3 之後 `data.yaml` 顯示 `nc: 2`，且 `names` 同時含 `skip_ad_button` 與 `popup_dismiss_button`。

### 人工抽查（肉眼確認紅框）

`--draw` 疊圖會輸出到 `ad_skipper/dataset/debug/<group>_<seq>.png`（與影格同名），
**只有正樣本**（有 bbox）才會產生疊圖。抽查方式由簡到進階：

1. **直接看**：開檔案總管切「大圖示」一次掃過縮圖。
   ```powershell
   Set-Location R:\SAM
   explorer ad_skipper\dataset\debug
   ```
2. **隨機抽幾張**集中檢視（符合「隨機抽查」）：
   ```powershell
   Set-Location R:\SAM
   $dst = "ad_skipper\dataset\_spotcheck"
   New-Item -ItemType Directory -Force $dst | Out-Null
   Get-ChildItem ad_skipper\dataset\debug -Filter *.png | Get-Random -Count 8 |
     Copy-Item -Destination $dst
   explorer $dst   # 看完可刪除 _spotcheck
   ```

檢查重點：紅框**完整包住**「略過廣告」按鈕、未偏移、未框到廣告其他區域；
不同 `group`（不同影片/廣告）都有抽到。

### 不良樣本處理

每個影格共用同一檔名於四個資料夾（`images/.png`、`labels/.txt`、`raw_boxes/.json`、`debug/.png`），
**處理時要一起動**，否則 Phase 3 切分會因影像/標註數量不對應而出錯。

| 狀況 | 建議處理 |
|---|---|
| 框完全錯位 / 框到非按鈕 | **整筆刪除**（重收較划算） |
| 畫面無效（全黑、轉場模糊、被彈窗遮住） | **整筆刪除** |
| 沒有 skip 按鈕卻被當正樣本 | **整筆刪除** |
| 重複度過高（同段廣告幾乎一樣） | 留 1～2 張，其餘刪除 |
| 框略偏但仍大致包住按鈕 | 可**修標註**或直接刪 |

> 原則：**錯標比少資料更傷**，寧可刪掉也不要留錯框。

**整筆刪除**（依檔名連帶刪四個檔；debug 圖建議一起刪）：

```powershell
Set-Location R:\SAM\ad_skipper\dataset
$bad = @(
  "20260627-153000_00_0002",
  "20260627-153000_01_0000"
)
foreach ($n in $bad) {
  Remove-Item "images\$n.png","labels\$n.txt","raw_boxes\$n.json","debug\$n.png" -ErrorAction SilentlyContinue
}
```

**只修標註**（框略偏時）：`labels/<name>.txt` 為一行正規化 YOLO 格式 `0 cx cy w h`（皆 0..1）。
手算易錯，建議用標註工具重畫一格：

```powershell
Set-Location R:\SAM
R:\SAM\.venv\Scripts\python.exe -m pip install labelImg
R:\SAM\.venv\Scripts\python.exe -m labelImg ad_skipper\dataset\images ad_skipper\ad_classes.txt ad_skipper\dataset\labels
```

**處理後一致性檢查**（跑 Phase 3 前必做，確認無孤兒檔）：

```powershell
Set-Location R:\SAM\ad_skipper\dataset
$imgs = (Get-ChildItem images\*.png | ForEach-Object BaseName)
$lbls = (Get-ChildItem labels\*.txt | ForEach-Object BaseName)
"images: $($imgs.Count)  labels: $($lbls.Count)"
Compare-Object $imgs $lbls   # 無輸出 = 完全對應；有輸出 = 有缺漏需補
```

> 若整體不良率偏高，別逐張修——回 Phase 1 重收並先固定視窗大小（暫不用 `--vary-layout`）
> 收一小批驗證座標換算（`--monitor`、DPR）是否正確。

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

## Phase 6 — 登入自動啟動 + 僅在 YouTube 影片(非 Shorts)時偵測

> 需先有 `ad_skipper/models/skip_ad_yolo.pt`（Phase 4 產出）。
> 目標：Windows **登入成功後自動檢查 skipper 是否已啟動，若無則背景隱藏啟動**，
> 並且**只有在前景瀏覽器分頁是 YouTube 影片（`youtube.com/watch`，不含 Shorts）時**才截圖與辨識。

### 觀念：watch vs Shorts 閘門（四層、可退化）

因為本專案是擷取**真實桌面**（非 Selenium 控制的瀏覽器），「取得目前分頁網址」本身是難點，
故閘門設計成多層、任何一層失效都會往下退，不會整個崩潰：

| 層級 | 判定 | 全螢幕 | 說明 |
|---|---|---|---|
| 1 標題前置 | 前景行程為瀏覽器且視窗標題含 `YouTube` | ✅ | 否則直接 `NONE`（停用） |
| 2 UIA 讀網址 | 用 UI Automation 讀網址列 → `WATCH`/`SHORTS`/`OTHER`，並**快取到該視窗** | ❌（網址列消失） | windowed 時最準 |
| 3 每視窗快取 | 全螢幕沿用該視窗最後已知分類（標題仍相符） | ✅ | 補第 2 層在全螢幕的盲區 |
| 4 標題輕量備援 | UIA 讀不到且無快取時：含 `shorts`→`SHORTS`；有真實標題前綴→`WATCH`；裸 `YouTube`→`NONE` | ✅ | best-effort，可用 `--fallback` 覆寫 |

**閘門只在最終分類為 `WATCH` 時開啟**（執行 grab + 偵測）。支援 Chrome / Edge / Firefox
（Edge 與 Chrome 同為 Chromium；Firefox 若未啟用無障礙(a11y)可能讀不到網址，會自動退第 4 層）。

### 安裝（註冊登入自動啟動）

於一般（免系統管理員）PowerShell 執行一次：

```powershell
Set-Location R:\SAM
powershell -ExecutionPolicy Bypass -File ad_skipper\install_autostart.ps1
```

> 會建立「At log on」工作排程器任務 `SAM YouTube Ad Skipper`，以 `.venv\Scripts\pythonw.exe`
> （無主控台視窗）背景執行：
> `youtube_ad_skipper.py --model ...\skip_ad_yolo.pt --monitor 1 --conf 0.9 --only-youtube-watch --single-instance --fallback title --log-file ...\logs\skipper.log`

**不必登出即可測試**：

```powershell
Start-ScheduledTask -TaskName 'SAM YouTube Ad Skipper'
Get-Content R:\SAM\ad_skipper\logs\skipper.log -Tail 20 -Wait
```

**手動啟動（不透過排程，供測試）**：

```powershell
Set-Location R:\SAM
powershell -ExecutionPolicy Bypass -File ad_skipper\autostart_skipper.ps1
```

**解除安裝**：

```powershell
Set-Location R:\SAM
powershell -ExecutionPolicy Bypass -File ad_skipper\uninstall_autostart.ps1
```

### 新增的 runtime 參數（`youtube_ad_skipper.py`）

| 參數 | 預設 | 說明 |
|---|---|---|
| `--only-youtube-watch` | off | 啟用四層閘門：僅 YouTube watch 頁才截圖+辨識 |
| `--url-poll` | 1.0 | 兩次網址閘門檢查的間隔秒數 |
| `--fallback` | `title` | UIA 讀不到且無快取時的決策：`title`/`none`/`watch` |
| `--log-file` | 無 | 將 log 寫入檔案（背景隱藏執行必備） |
| `--single-instance` | off | 偵測到已有實例執行時乾淨退出（exit 0），即「已啟動就不重複啟動」 |

> 單一實例採 Windows 具名互斥量（`Global\SAM_youtube_ad_skipper`）；
> 登入時排程觸發若已有實例在跑，新觸發會立即 exit 0，不會開出第二份。

### 行為說明

- 閘門每 `--url-poll` 秒檢查一次；非 watch 頁時**完全略過截圖與模型推論**（省 CPU），切回 watch 才恢復。
- 全螢幕播放時網址列消失，改用「每視窗快取」沿用先前 windowed 模式判定的 watch/shorts；
  若連快取都沒有，再退「標題輕量備援」。
- 其餘點擊行為與 Phase 5 相同（穩定幀數門檻、保留游標、`--cooldown`）。

### 驗收標準

- [ ] `install_autostart.ps1` 成功註冊任務；`Get-ScheduledTask 'SAM YouTube Ad Skipper'` 可見。
- [ ] `Start-ScheduledTask`（或重新登入）後，工作管理員可見一個**隱藏的 `pythonw.exe`**，且 `logs/skipper.log` 出現啟動紀錄。
- [ ] 連續觸發/手動再啟一次時，第二份因單一實例守門**立即結束**，不出現兩個 skipper。
- [ ] 在 YouTube **watch 頁**時 log 顯示 `URL gate OPEN`，並可偵測/略過廣告。
- [ ] 切到 **Shorts** 或非 YouTube 分頁時 log 顯示 `URL gate CLOSED`，不截圖、不誤點。
- [ ] watch 頁切**全螢幕**後仍維持 `OPEN`（靠每視窗快取）。
- [ ] `uninstall_autostart.ps1` 可移除任務。
- [ ] 單獨執行 `python ad_skipper\_active_url.py` 時，三瀏覽器在 watch/shorts/一般頁分別輸出 `WATCH`/`SHORTS`/`OTHER`。

### 單獨驗證閘門（不啟動模型）

```powershell
Set-Location R:\SAM
R:\SAM\.venv\Scripts\python.exe ad_skipper\_active_url.py
```

> 會每秒印出目前前景視窗的行程、網址與分類；切換 Chrome/Edge/Firefox 的 watch / shorts /
> 一般頁與全螢幕，確認分類正確。`Ctrl+C` 結束。

---

## 附錄：環境前置

```powershell
Set-Location R:\SAM
R:\SAM\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

所需套件（已列於 `requirements.txt` / `pyproject.toml`）：
`ultralytics`、`selenium`、`webdriver-manager`、`mss`、`imagehash`、`psutil`、`pydirectinput`、`uiautomation`（Phase 6 網址閘門）、`opencv-python`、`easyocr`（選用備援）。
