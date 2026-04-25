# Tools

## autolabel.py — Headless Auto-Labeling CLI

Headless CLI for X-AnyLabeling auto-labeling without GUI or PyQt6 dependency.
Uses SAM / SAM2 ONNX backends directly via `onnxruntime` + `opencv`.

### Dependencies

```bash
pip install onnxruntime opencv-python numpy
```

### Usage

```bash
python tools/autolabel.py \
    --image  <image_path> \
    --encoder <encoder.onnx> \
    --decoder <decoder.onnx> \
    --points  <x,y> \
    [--output-mode rectangle|polygon|rotation] \
    [--output  <output.json>]
```

### Output Shape Modes

| `--output-mode` | 說明 | `shape_type` |
|---|---|---|
| `rectangle` | 軸對齊外接矩形（**預設**） | `"rectangle"` |
| `polygon` | 多邊形輪廓頂點 | `"polygon"` |
| `rotation` | 最小旋轉外接矩形 | `"rotation"` |

---

#### Rectangle（軸對齊外接矩形，預設）

```bash
python tools/autolabel.py \
    --image    R:/X-AnyLabeling/tools/frame_00000.jpg \
    --encoder  C:/Users/User/xanylabeling_data/models/sam2_hiera_large-r20240801/sam2.1_hiera_large.encoder.onnx \
    --decoder  C:/Users/User/xanylabeling_data/models/sam2_hiera_large-r20240801/sam2.1_hiera_large.decoder.onnx \
    --points   640,698 \
    --output-mode rectangle
```

#### Polygon（多邊形輪廓）

```bash
python tools/autolabel.py \
    --image    R:/X-AnyLabeling/tools/frame_00000.jpg \
    --encoder  C:/Users/User/xanylabeling_data/models/sam2_hiera_large-r20240801/sam2.1_hiera_large.encoder.onnx \
    --decoder  C:/Users/User/xanylabeling_data/models/sam2_hiera_large-r20240801/sam2.1_hiera_large.decoder.onnx \
    --points   640,698 \
    --output-mode polygon
```

#### Rotation（最小旋轉外接矩形）

```bash
python tools/autolabel.py \
    --image    R:/X-AnyLabeling/tools/frame_00000.jpg \
    --encoder  C:/Users/User/xanylabeling_data/models/sam2_hiera_large-r20240801/sam2.1_hiera_large.encoder.onnx \
    --decoder  C:/Users/User/xanylabeling_data/models/sam2_hiera_large-r20240801/sam2.1_hiera_large.decoder.onnx \
    --points   640,698 \
    --output-mode rotation
```

---

### All Arguments

| 參數 | 說明 | 預設值 |
|---|---|---|
| `--image` | 輸入圖片路徑（必填） | — |
| `--encoder` | Encoder ONNX 路徑（必填） | — |
| `--decoder` | Decoder ONNX 路徑（必填） | — |
| `--points` | 點提示 `x,y[,label]`，可重複；label=1 ADD / 0 REMOVE | — |
| `--rect` | 矩形提示 `x1,y1,x2,y2` | — |
| `--output` | 輸出 JSON 路徑 | `<image_stem>.json` |
| `--output-mode` | 輸出形狀類型 | `rectangle` |
| `--model-type` | 推論 backend（auto / segment_anything / segment_anything_2） | `auto` |
| `--device` | 裝置（cpu / gpu） | 自動偵測 |
| `--label` | 輸出標籤名稱 | `object` |
| `--epsilon` | 輪廓近似 epsilon 倍數 | `0.001` |

### Output Format

輸出為 **LabelMe JSON** 格式，可直接用 X-AnyLabeling GUI **File → Open Dir** 載入驗證。

```json
{
  "version": "5.0.0",
  "shapes": [
    {
      "label": "object",
      "shape_type": "rectangle",
      "points": [[x1, y1], [x2, y1], [x2, y2], [x1, y2]]
    }
  ],
  "imagePath": "frame_00000.jpg",
  "imageHeight": 720,
  "imageWidth": 1280
}
```

### Model Auto-Detection

`--model-type auto`（預設）會根據 encoder/decoder 檔名自動判斷：

- 檔名含 `sam2` 或 `hiera` → `segment_anything_2`
- 其他 → `segment_anything`

---

### 在 X-AnyLabeling GUI 中載入標注結果

#### 前置條件

執行完 `autolabel.py` 後，確認圖片與 JSON 同名且在同一目錄：

```
R:\X-AnyLabeling\tools\
├── frame_00000.jpg   ← 圖片
└── frame_00000.json  ← autolabel.py 輸出的標注（需與圖片同名）
```

> **注意**：若使用 `--output result.json` 自訂輸出路徑，需手動重新命名為 `frame_00000.json` 並放到圖片同目錄，GUI 才能自動載入。
> 建議直接省略 `--output`，腳本預設會輸出為 `<image_stem>.json`（即 `frame_00000.json`）放在圖片旁邊。

#### 步驟

1. 啟動 X-AnyLabeling GUI
2. 選單 **File → Open Dir**（快捷鍵 `Ctrl+U`）
3. 選擇圖片所在資料夾：`R:\X-AnyLabeling\tools\`
4. GUI 左側檔案列表點選 `frame_00000.jpg`
5. 標注形狀自動載入顯示在畫面上

#### 快速驗證（建議步驟）

| 步驟 | 預期結果 |
|---|---|
| Open Dir → 選 `tools\` | 左側出現 `frame_00000.jpg` |
| 點選圖片 | 畫面顯示圖片，右側 label list 出現 `object` |
| 縮放到標注區域 | 可見 rectangle / polygon / rotation 形狀標注 |
