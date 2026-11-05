"""Extract Korean wording only from artwork PDFs.

Native text gives an anchor and bounding box; Tesseract reads the rendered
appearance to recover malformed digits/spaces. OCR is never treated as verified.
"""
import csv
import io
import json
import re
import zipfile

import fitz
from PIL import Image, ImageOps
import pytesseract

KOREAN = re.compile(r"[가-힣]")
BROKEN = re.compile(r"[\ufffd\u57d1-\u57ff]")
KOREAN_PREFIX = re.compile(r"^\s*(?:KO|KR)\s*[-:]\s*", re.I)


def _ocr(page, bbox, dpi=350):
    rect = fitz.Rect(bbox)
    # Expand around text, while avoiding large neighboring columns.
    pad_x = max(2, min(8, rect.height * .25))
    pad_y = max(2, min(5, rect.height * .25))
    rect = (rect + (-pad_x, -pad_y, pad_x, pad_y)) & page.rect
    if rect.is_empty:
        return "", None, None
    pix = page.get_pixmap(matrix=fitz.Matrix(dpi / 72, dpi / 72),
                          clip=rect, alpha=False)
    image = Image.open(io.BytesIO(pix.tobytes("png"))).convert("RGB")
    # Large and rotated text are common on package dielines.
    candidates = []
    for angle in (0, 180):
        rotated = image.rotate(angle, expand=True) if angle else image
        gray = ImageOps.autocontrast(ImageOps.grayscale(rotated))
        for psm in (6, 7):
            try:
                result = pytesseract.image_to_data(
                    gray, lang="kor+eng",
                    config=f"--oem 3 --psm {psm}",
                    output_type=pytesseract.Output.DICT,
                )
            except pytesseract.TesseractNotFoundError as e:
                raise RuntimeError("서버에 Tesseract 프로그램이 없습니다. packages.txt 설치 여부를 확인하세요.") from e
            except pytesseract.TesseractError as e:
                raise RuntimeError("한국어 kor 언어팩을 포함한 Tesseract 설치 상태를 확인하세요.") from e
            words = []
            confidences = []
            for token, confidence in zip(result["text"], result["conf"]):
                token = token.strip()
                try:
                    confidence = float(confidence)
                except (ValueError, TypeError):
                    continue
                if token and confidence >= 0:
                    words.append(token)
                    confidences.append(confidence)
            text = " ".join(words).strip()
            korean_count = len(KOREAN.findall(text))
            # Prefer coherent Korean output over high-confidence English hallucination.
            score = (
                (sum(confidences) / len(confidences) if confidences else 0)
                + min(korean_count, 20) * 1.6
                - (25 if not korean_count else 0)
            )
            candidates.append((score, text, angle, psm))
    best = max(candidates, key=lambda x: x[0])
    return best[1], best[2], best[3]


def _native_lines(page):
    for block in page.get_text("dict", flags=0)["blocks"]:
        for line in block.get("lines", []):
            spans = [s for s in line["spans"] if s.get("text", "").strip()]
            if not spans:
                continue
            native = "".join(s["text"] for s in spans).strip()
            if not native:
                continue
            bbox = fitz.Rect(
                min(s["bbox"][0] for s in spans),
                min(s["bbox"][1] for s in spans),
                max(s["bbox"][2] for s in spans),
                max(s["bbox"][3] for s in spans),
            )
            yield native, bbox


def extract_pdf(pdf_bytes, filename, dpi=350, mode="korean", max_pages=20):
    """Return *Korean-containing lines only* and page summaries."""
    rows, summaries = [], []
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    try:
        if doc.page_count > max_pages:
            raise ValueError(f"페이지 수가 설정된 최대치({max_pages})를 넘습니다.")
        for page_i, page in enumerate(doc):
            lines = list(_native_lines(page))
            korean_lines = 0
            for native, rect in lines:
                # Keep Korean text and adjacent corrupted glyphs/digits in same line;
                # exclude unrelated English, French, Polish, etc.
                if not KOREAN.search(native):
                    continue
                korean_lines += 1
                ocr, rotation, psm = _ocr(page, rect, dpi=dpi)
                # A Korean string can be present in source while OCR misreads it.
                # Expose both so reviewers don't accidentally accept hallucinated OCR.
                cleaned_native = KOREAN_PREFIX.sub("", native)
                cleaned_ocr = KOREAN_PREFIX.sub("", ocr)
                needs_review = bool(BROKEN.search(native)) or not bool(KOREAN.search(ocr))
                rows.append({
                    "file": filename,
                    "page": page_i + 1,
                    "korean_ocr": cleaned_ocr if KOREAN.search(cleaned_ocr) else "",
                    "pdf_original": cleaned_native,
                    "needs_review": needs_review,
                    "ocr_rotation": rotation,
                    "ocr_psm": psm,
                    "x0": round(rect.x0, 1),
                    "y0": round(rect.y0, 1),
                    "x1": round(rect.x1, 1),
                    "y1": round(rect.y1, 1),
                })
            summaries.append({
                "file": filename, "page": page_i + 1,
                "native_lines": len(lines),
                "korean_lines": korean_lines, "ocr_lines": korean_lines,
            })
    finally:
        doc.close()
    return rows, summaries


def export_zip(rows, summaries):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        contents = io.StringIO(newline="")
        if rows:
            writer = csv.DictWriter(contents, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
        archive.writestr("korean_only.csv", "\ufeff" + contents.getvalue())
        archive.writestr("korean_only.json", json.dumps(rows, ensure_ascii=False, indent=2))
        comparison = "\n\n".join(
            f"[{r['file']} / p.{r['page']}]\nOCR: {r['korean_ocr']}\nPDF: {r['pdf_original']}"
            for r in rows
        )
        archive.writestr("korean_only.txt", comparison)
        archive.writestr("summary.json", json.dumps(summaries, ensure_ascii=False, indent=2))
    return buffer.getvalue()
