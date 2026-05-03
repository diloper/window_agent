import os
import re
from pathlib import Path
from typing import Literal

DEFAULT_OCR_MIN_CONFIDENCE = 0.6
PADDLE_OCR_VERSION = "PP-OCRv5"
PADDLE_TEXT_DET_MODEL = "PP-OCRv5_mobile_det"
PADDLE_TEXT_REC_MODEL = "PP-OCRv5_mobile_rec"

_ZH_PATTERN = re.compile(r"[\u4e00-\u9fff]")
_EN_PATTERN = re.compile(r"[A-Za-z]")
_DIGIT_PATTERN = re.compile(r"\d")


def _classify_text_pairs(
    pairs: list[tuple[str, float]],
    min_confidence: float,
) -> dict:
    """共用分類邏輯：輸入 [(text, confidence), ...] 回傳標準摘要字典。"""
    matched_types: set[str] = set()
    sample_text: list[dict] = []
    accepted_count = 0
    rejected_details: list[dict] = []

    for text, confidence in pairs:
        text = text.strip()
        # 拒絕條件 1：文字為空
        if not text:
            continue
        # 拒絕條件 2：信心分數低於門檻（預設 0.6），避免雜訊/模糊字被誤判為有效文字
        if confidence < min_confidence:
            rejected_details.append({"text": text, "confidence": round(confidence, 4)})
            continue

        accepted_count += 1
        sample_text.append({"text": text, "confidence": round(confidence, 4)})
        if _ZH_PATTERN.search(text):
            matched_types.add("zh")
        if _EN_PATTERN.search(text):
            matched_types.add("en")
        if _DIGIT_PATTERN.search(text):
            matched_types.add("digit")

    total = accepted_count + len(rejected_details)
    return {
        "has_target_text": bool(matched_types),
        "matched_types": sorted(matched_types),
        "sample_text": sample_text[:5],
        "ocr_count": total,
        "accepted_ocr_count": accepted_count,
        "rejected_ocr_count": len(rejected_details),
        "rejected_details": rejected_details,
        "min_confidence": min_confidence,
    }


def _run_easyocr(image_path: Path) -> list[tuple[str, float]]:
    """使用 EasyOCR 讀圖，回傳 [(text, confidence), ...]。"""
    try:
        import easyocr
    except ImportError as exc:
        raise RuntimeError(
            "EasyOCR is not installed. Install it with: pip install easyocr"
        ) from exc

    try:
        reader = easyocr.Reader(["ch_sim", "en"], gpu=False)
        results = reader.readtext(str(image_path), detail=1)
    except Exception as exc:
        raise RuntimeError(f"EasyOCR failed to process image: {exc}") from exc

    pairs = []
    for result in results:
        if len(result) < 2:
            continue
        text = str(result[1])
        confidence = float(result[2]) if len(result) >= 3 else 0.0
        pairs.append((text, confidence))
    return pairs


def _run_paddleocr(image_path: Path) -> list[tuple[str, float]]:
    """使用 PP-OCRv5 輕量化（mobile）模型讀圖，回傳 [(text, confidence), ...]。"""
    # 停用 MKLDNN，避免部分 Windows 環境下 oneDNN/PIR 相容性問題。
    os.environ["FLAGS_use_mkldnn"] = "0"

    try:
        from paddleocr import PaddleOCR
    except ImportError as exc:
        raise RuntimeError(
            "PaddleOCR is not installed. Install it with: pip install paddleocr"
        ) from exc

    try:
        # 指定 PP-OCRv5 mobile det/rec，使用輕量化模型以降低資源消耗。
        ocr = PaddleOCR(
            lang="ch",
            ocr_version=PADDLE_OCR_VERSION,
            text_detection_model_name=PADDLE_TEXT_DET_MODEL,
            text_recognition_model_name=PADDLE_TEXT_REC_MODEL,
        )
        pages = ocr.ocr(str(image_path))
    except Exception as exc:
        raise RuntimeError(f"PaddleOCR failed to process image: {exc}") from exc

    pairs = []
    # paddleocr >= 3.4 回傳 list[dict]，每個 dict 含 rec_texts / rec_scores。
    # 舊版（< 3.4）回傳 list[list[line]]，每 line 為 [bbox, (text, score)]。
    for page in (pages or []):
        if not page:
            continue
        if isinstance(page, dict):
            texts = page.get("rec_texts") or []
            scores = page.get("rec_scores") or []
            for text, score in zip(texts, scores):
                pairs.append((str(text), float(score)))
        else:
            for line in page:
                if not line or len(line) < 2:
                    continue
                text_score = line[1]
                if not text_score or len(text_score) < 2:
                    continue
                pairs.append((str(text_score[0]), float(text_score[1])))
    return pairs


def detect_target_text_types(
    image_path: Path,
    min_confidence: float = DEFAULT_OCR_MIN_CONFIDENCE,
    engine: Literal["easyocr", "paddleocr"] = "paddleocr",
) -> dict:
    """判斷圖片是否含有中文、英文或數字。

    Args:
        image_path: 圖片路徑。
        min_confidence: OCR 結果最低信心分數門檻，0.0–1.0，預設 0.6。
        engine: 使用的 OCR 引擎，'paddleocr'（預設）或 'easyocr'。
    """
    if not image_path.exists() or not image_path.is_file():
        raise FileNotFoundError(f"Image file not found: {image_path}")

    if not 0.0 <= min_confidence <= 1.0:
        raise ValueError("min_confidence must be between 0.0 and 1.0")

    if engine == "paddleocr":
        pairs = _run_paddleocr(image_path)
    elif engine == "easyocr":
        pairs = _run_easyocr(image_path)
    else:
        raise ValueError(f"Unsupported engine: {engine!r}. Choose 'easyocr' or 'paddleocr'.")

    result = _classify_text_pairs(pairs, min_confidence)
    result["engine"] = engine
    return result


def detect_target_text_types_with_easyocr(
    image_path: Path,
    min_confidence: float = DEFAULT_OCR_MIN_CONFIDENCE,
) -> dict:
    """向後相容的 EasyOCR 入口，等同於 detect_target_text_types(..., engine='easyocr')。"""
    return detect_target_text_types(image_path, min_confidence=min_confidence, engine="easyocr")
