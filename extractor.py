"""Korean-only text extraction from artwork PDFs.

Direct PDF text where valid; tight-region OCR only for corrupted Unicode.
The OCR result is labeled as a candidate, never certified as correct.
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

KOR = re.compile("[가-힣]")
FOREIGN = re.compile(r"[A-Za-zÀ-ÿА-Яа-я]{3,}")


def korean_segment(line):
    chars = [c for span in line["spans"] for c in span["chars"]]
    text = "".join(c["c"] for c in chars)
    match = KOR.search(text)
    if not match:
        return None
    start = match.start()
    if start and text[start - 1] == "\ufffd":
        start -= 1
    # Retain the initial QR/AI prefix when it belongs to Korean wording.
    prefix = text[max(0, start - 3):start]
    leading = re.search(r"(?:QR|AI)\s*$", prefix)
    if leading:
        start -= len(leading.group())
    end = len(text)
    for other in FOREIGN.finditer(text, match.end()):
        if KOR.search(text[match.start():other.start()]):
            end = other.start()
            break
    while end > start and text[end - 1] in " /|•\u00a0":
        end -= 1
    if end <= start:
        return None
    return chars[start:end], re.sub(r"\s+", " ", text[start:end]).strip()


def tight_ocr(page, line, chars, dpi):
    direction = line.get("dir", (1, 0))
    boxes = [c["bbox"] for c in chars]
    x0 = min(b[0] for b in boxes) - 2
    x1 = max(b[2] for b in boxes) + 2
    first_span = line["spans"][0]
    baseline = first_span["origin"][1]
    size = first_span["size"]
    upside_down = direction[0] < -0.8
    if upside_down:
        y0, y1 = baseline - size * .18, baseline + size * 1.0
    else:
        y0, y1 = baseline - size * 1.05, baseline + size * .22
    rect = fitz.Rect(x0, y0, x1, y1) & page.rect
    if rect.is_empty:
        return ""
    pix = page.get_pixmap(
        clip=rect,
        matrix=fitz.Matrix(dpi / 72, dpi / 72),
        alpha=False,
    )
    image = Image.open(io.BytesIO(pix.tobytes("png")))
    if upside_down:
        image = image.rotate(180, expand=True)
    image = ImageOps.autocontrast(ImageOps.grayscale(image))
    # Border is critical: Tesseract rejects tightly cropped short lines.
    image = ImageOps.expand(image, border=25, fill=255)
    try:
        result = pytesseract.image_to_string(
            image, lang="kor+eng", config="--oem 3 --psm 7"
        ).strip()
    except pytesseract.TesseractNotFoundError as exc:
        raise RuntimeError("Tesseract 프로그램 설치가 필요합니다. packages.txt를 확인하세요.") from exc
    except pytesseract.TesseractError as exc:
        raise RuntimeError("Tesseract 한국어 언어팩 설치를 확인하세요.") from exc
    result = re.sub(r"\s+", " ", result)
    match = KOR.search(result)
    if not match:
        return ""
    start = match.start()
    # A corrupted PDF digit such as '�배' can be restored as '4배'.
    number = re.search(r"\d\s*$", result[:start])
    if number:
        start = number.start()
    prefix = re.search(r"(?:QR|AI)\s*$", result[max(0, start - 3):start])
    if prefix:
        start -= len(prefix.group())
    end = len(result)
    next_language = FOREIGN.search(result, match.end())
    if next_language:
        end = next_language.start()
    return result[start:end].strip(" /|•")


def extract_pdf(pdf_bytes, filename, dpi=350, mode="korean", max_pages=20):
    rows, summaries = [], []
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    try:
        if doc.page_count > max_pages:
            raise ValueError(f"파일이 최대 페이지 수({max_pages})를 초과했습니다.")
        for page_num, page in enumerate(doc, 1):
            page_rows = 0
            ocr_lines = 0
            for block in page.get_text("rawdict", flags=0)["blocks"]:
                for line in block.get("lines", []):
                    segment = korean_segment(line)
                    if not segment:
                        continue
                    chars, native = segment
                    direction = line.get("dir", (1, 0))
                    curved = abs(direction[1]) > .3
                    broken = "\ufffd" in native
                    candidate = ""
                    if (broken or mode == "all") and not curved:
                        candidate = tight_ocr(page, line, chars, dpi)
                        ocr_lines += 1
                    if broken:
                        anchor = "".join(KOR.findall(native))
                        recognized = "".join(KOR.findall(candidate))
                        similarity = (
                            SequenceMatcher(None, anchor, recognized).ratio()
                            if anchor and recognized else 0.0
                        )
                        if candidate and similarity >= .7 and "\ufffd" not in candidate:
                            best = candidate
                            status = "OCR 복원 후보 · 검증 필요"
                        else:
                            best = native
                            status = "복원 실패 · 원본 확인"
                    else:
                        best = native
                        status = "곡선 배치 · 연결 확인" if curved else "원본 추출 정상"
                    rows.append({
                        "file": filename,
                        "page": page_num,
                        "korean_text": best,
                        "status": status,
                        "pdf_original": native,
                        "ocr_candidate": candidate,
                        "x0": round(min(c["bbox"][0] for c in chars), 1),
                        "y0": round(min(c["bbox"][1] for c in chars), 1),
                    })
                    page_rows += 1
            summaries.append({
                "file": filename, "page": page_num,
                "korean_lines": page_rows, "ocr_lines": ocr_lines,
            })
    finally:
        doc.close()
    return rows, summaries


def export_zip(rows, summaries):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        csv_content = io.StringIO(newline="")
        if rows:
            writer = csv.DictWriter(csv_content, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
        archive.writestr("korean_only.csv", "\ufeff" + csv_content.getvalue())
        archive.writestr("korean_only.json", json.dumps(rows, ensure_ascii=False, indent=2))
        archive.writestr(
            "korean_only.txt",
            "\n".join(
                f"[{r['file']} / p.{r['page']}] {r['korean_text']}  ({r['status']})"
                for r in rows
            ),
        )
        archive.writestr("summary.json", json.dumps(summaries, ensure_ascii=False, indent=2))
    return output.getvalue()
