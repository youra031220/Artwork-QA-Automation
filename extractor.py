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



def repair_damaged_native(native, candidate):
    """Patch only unreadable glyphs; never overwrite readable Korean with OCR.

    OCR can omit the rest of a long line. Restoring only supported numbers
    and confirmed spacing keeps valid native wording intact.
    """
    repaired = native
    repairs = []
    for found in re.finditer(r"(\d{1,4})\s*([가-힣]{1,3})", candidate):
        number, following = found.groups()
        for n in range(min(3, len(following)), 0, -1):
            anchor = following[:n]
            pattern = r"\ufffd{1,8}(\s*)" + re.escape(anchor)
            match = re.search(pattern, repaired)
            if match:
                repaired = (
                    repaired[:match.start()]
                    + number
                    + match.group(1)
                    + repaired[match.end() - len(anchor):]
                )
                repairs.append("숫자")
                break

    # Korean-only artwork often maps spaces to replacement glyphs.
    # Require a matching word boundary in OCR before repairing spacing.
    chunks = [c for c in re.split(r"\ufffd+", native) if c.strip()]
    evidence = False
    for left, right in zip(chunks, chunks[1:]):
        lwords, rwords = left.strip().split(), right.strip().split()
        if lwords and rwords:
            lword, rword = lwords[-1], rwords[0]
            if lword[-2:] + " " + rword[:2] in candidate:
                evidence = True
                break
    if evidence:
        repaired = re.sub(r"(?<=[가-힣])\ufffd+(?=[가-힣])", " ", repaired)
        repairs.append("공백")
    return repaired, repairs


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
                        best, repaired_parts = repair_damaged_native(native, candidate)
                        status = (
                            "부분 복원 · 원본 확인" if "\ufffd" in best
                            else "OCR 복원 후보 · 검증 필요"
                        )
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
