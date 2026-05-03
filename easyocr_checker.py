import re
from pathlib import Path

DEFAULT_OCR_MIN_CONFIDENCE = 0.6


def detect_target_text_types_with_easyocr(
    image_path: Path,
    min_confidence: float = DEFAULT_OCR_MIN_CONFIDENCE,
) -> dict:
    """使用 EasyOCR 判斷是否有中文、英文或數字。"""
    if not image_path.exists() or not image_path.is_file():
        raise FileNotFoundError(f"Image file not found: {image_path}")

    if not 0.0 <= min_confidence <= 1.0:
        raise ValueError("min_confidence must be between 0.0 and 1.0")

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

    zh_pattern = re.compile(r"[\u4e00-\u9fff]")
    en_pattern = re.compile(r"[A-Za-z]")
    digit_pattern = re.compile(r"\d")

    matched_types: set[str] = set()
    sample_text = []
    accepted_count = 0
    rejected_details: list[dict] = []

    for result in results:
        if len(result) < 2:
            continue

        text = str(result[1]).strip()
        confidence = float(result[2]) if len(result) >= 3 else 0.0
        # 拒絕條件 1：文字為空
        if not text:
            continue
        # 拒絕條件 2：信心分數低於門檻（預設 0.6），避免雜訊/模糊字被誤判為有效文字
        if confidence < min_confidence:
            rejected_details.append({"text": text, "confidence": round(confidence, 4)})
            continue

        accepted_count += 1
        sample_text.append({"text": text, "confidence": round(confidence, 4)})
        if zh_pattern.search(text):
            matched_types.add("zh")
        if en_pattern.search(text):
            matched_types.add("en")
        if digit_pattern.search(text):
            matched_types.add("digit")

    return {
        "has_target_text": bool(matched_types),
        "matched_types": sorted(matched_types),
        "sample_text": sample_text[:5],
        "ocr_count": len(results),
        "accepted_ocr_count": accepted_count,
        "rejected_ocr_count": len(results) - accepted_count,
        "rejected_details": rejected_details,
        "min_confidence": min_confidence,
    }
