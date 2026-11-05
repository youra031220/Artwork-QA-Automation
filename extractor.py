"""Korean-only PDF extraction for packaging artwork.

Use the PDF's native text when clean. If character mapping is broken,
read a tight render of that *one* printed line using Korean Tesseract.
Output uncertain OCR as a review candidate, not as verified text.
"""
import csv
import io
import json
import re
import zipfile
from difflib import SequenceMatcher

import fitz
from PIL import Image, ImageOps
import pytesseract

HANGUL = re.compile(r"[가-힣]")
BROKEN = "\ufffd"
KO_PREFIX = re.compile(r"^\s*(?:KO|KR)\s*[-:]\s*", re.I)


def _keep_korean_part(text):
    """Strip non-Korean neighbor languages on bilingual artwork lines."""
    text = KO_PREFIX.sub("", text).strip()
    match = HANGUL.search(text)
    if not match:
        return ""
    start = match.start()
    # Permit preceding damaged numeric character, e.g. '�배'.
    if start and text[start - 1] == BROKEN:
        start -= 1
    text = text[start:]
    # End when we reach a long non-Korean alphabetic section.
    text = re.split(r"\s+[A-Za-zÀ-ÿА-Яа-я]{3,}", text, maxsplit=1)[0]
    return " ".join(text.split()).strip(" /|•")


def _ocr_line(page, line, dpi):
    """Crop to physical glyph ink, not PDF font bbox (which overlaps other lines).

    NotoSansKR has an unusually tall font bbox; taking line['bbox'] rendered
    2-3 adjacent multilingual lines and caused OCR garbage.
    The span baseline and writing direction give a much tighter crop.
    """
    spans = line["spans"]
    native = "".join("".join(c["c"] for c in span["chars"]) for span in spans)
    direction = line.get("dir", (1, 0))
    x0, _, x1, _ = line["bbox"]
    # Native Korean spans are our positional anchor.
    kr_chars = [
        c for span in spans for c in span["chars"]
        if HANGUL.search(c["c"]) or c["c"] == BROKEN
    ]
    if kr_chars:
        # Clip horizontally to Korean segment if line contains other languages.
        xs = [c["bbox"] for c in kr_chars]
        x0 = max(x0, min(b[0] for b in xs) - 3)
        x1 = min(x1, max(b[2] for b in xs) + 3)
    baseline = sum(span["origin"][1] for span in spans) / len(spans)
    size = max(span["size"] for span in spans)
    backwards = direction[0] < -0.5
    if backwards:
        # Upside-down baseline: ink is BELOW the baseline.
        top, bottom = baseline - size * .2, baseline + size * .95
    else:
        # Upright baseline: ink is ABOVE the baseline.
        top, bottom = baseline - size * 1.0, baseline + size * .15
    rect = fitz.Rect(x0 - 2, top, x1 + 2, bottom) & page.rect
    if rect.is_empty:
        return "", None
    pix = page.get_pixmap(clip=rect, matrix=fitz.Matrix(dpi / 72, dpi / 72), alpha=False)
    im = Image.open(io.BytesIO(pix.tobytes("png"))).convert("RGB")
    if backwards:
        im = im.rotate(180, expand=True)
    im = ImageOps.autocontrast(ImageOps.grayscale(im))

    # Single-line recognition; never OCR an entire multilingual paragraph.
    try:
        ocr = pytesseract.image_to_string(im, lang="kor+eng", config="--oem 3 --psm 7")
    except pytesseract.TesseractNotFoundError as e:
        raise RuntimeError("Tesseract 프로그램이 설치되지 않았습니다. packages.txt를 확인하세요.") from e
    except pytesseract.TesseractError as e:
        raise RuntimeError("Tesseract 한국어(kor) 언어팩 설치를 확인하세요.") from e
    return _keep_korean_part(ocr), (180 if backwards else 0)


def extract_pdf(pdf_bytes, filename, dpi=350, mode="korean", max_pages=20):
    rows, summaries = [], []
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    try:
        if doc.page_count > max_pages:
            raise ValueError(f"파일이 최대 페이지 수({max_pages})를 초과했습니다.")
        for page_no, page in enumerate(doc, 1):
            line_total, korean_count, ocr_count = 0, 0, 0
            for block in page.get_text("rawdict", flags=0)["blocks"]:
                for line in block.get("lines", []):
                    native_full = "".join(
                        "".join(ch["c"] for ch in span["chars"])
                        for span in line["spans"]
                    )
                    if not HANGUL.search(native_full):
                        continue
                    korean_count += 1
                    line_total += 1
                    native = _keep_korean_part(native_full)
                    broken = BROKEN in native
                    # Avoid OCR if Korean already extracts correctly.
                    if broken or mode == "all":
                        candidate, orientation = _ocr_line(page, line, dpi)
                        ocr_count += 1
                    else:
                        candidate, orientation = "", None
                    # Never replace a clean native sentence with OCR errors.
                    if broken:
                        anchor = "".join(HANGUL.findall(native))
                        recognized = "".join(HANGUL.findall(candidate))
                        similarity = SequenceMatcher(None, anchor, recognized).ratio() if anchor and recognized else 0
                        # Only accept candidate automatically when it remains
                        # close to the readable Hangul context of the PDF.
                        reliable = bool(candidate) and similarity >= 0.75 and BROKEN not in candidate
                        best = candidate if reliable else native
                        status = "OCR 확인 필요" if reliable else "판독 불확실 - 원본 확인"
                    else:
                        best = native
                        status = "원본 텍스트 정상"
                    rect = line["bbox"]
                    rows.append({
                        "file": filename,
                        "page": page_no,
                        "korean_text": best,
                        "status": status,
                        "pdf_original": native,
                        "ocr_candidate": candidate,
                        "orientation": orientation,
                        "x0": round(rect[0], 1),
                        "y0": round(rect[1], 1),
                        "x1": round(rect[2], 1),
                        "y1": round(rect[3], 1),
                    })
            summaries.append({
                "file": filename, "page": page_no,
                "korean_lines": korean_count, "ocr_lines": ocr_count,
            })
    finally:
        doc.close()
    return rows, summaries


def export_zip(rows, summaries):
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        content = io.StringIO(newline="")
        if rows:
            writer = csv.DictWriter(content, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
        z.writestr("korean_only.csv", "\ufeff" + content.getvalue())
        z.writestr("korean_only.json", json.dumps(rows, ensure_ascii=False, indent=2))
        z.writestr("korean_only.txt", "\n".join(
            f"[{r['file']} / p{r['page']}] {r['korean_text']}  ({r['status']})"
            for r in rows))
        z.writestr("summary.json", json.dumps(summaries, ensure_ascii=False, indent=2))
    return out.getvalue()
