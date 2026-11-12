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
# Other scripts in multilingual packaging are not Korean review copy.
# Preserve the complete original only in raw PDF evidence.
NON_KOREAN_SCRIPT = re.compile(
    r"[\u0e00-\u0e7f\u0600-\u06ff\u0750-\u077f"
    r"\u3040-\u30ff\u3400-\u9fff\u0400-\u052f]"
)


# Latin-language bibliographic attributions can be embedded in Korean copy.
# Preserve only text actually printed in the PDF; never fill from a template.
INLINE_SOURCE = re.compile(
    r"Euromonitor\s+International\s+Limited\s*,?\s*"
    r"Home\s+and\s+Garden\s+\d{4}",
    re.IGNORECASE,
)


def _korean_scope_end(text, hangul_position):
    """Limit Korean copy while retaining its actual inline English citation."""
    protected_until = -1
    latin_end = len(text)
    for foreign in FOREIGN.finditer(text, hangul_position + 1):
        if foreign.start() < protected_until:
            continue
        source = INLINE_SOURCE.match(text, foreign.start())
        if source:
            protected_until = source.end()
            continue
        latin_end = foreign.start()
        break
    other_script = NON_KOREAN_SCRIPT.search(text, hangul_position + 1)
    return min(latin_end, other_script.start() if other_script else len(text))


def korean_segment(line):
    chars = [c for span in line["spans"] for c in span["chars"]]
    text = "".join(c["c"] for c in chars)
    match = KOR.search(text)
    if not match:
        return None
    start = match.start()
    if start and text[start - 1] == "\ufffd":
        start -= 1
    # Keep numeric prefixes of Korean copy, e.g. "18/10 스테인리스".
    preceding = text[:match.start()]
    numeric_prefix = re.search(
        r"(?:^|\s)(\d{1,4}(?:\s*/\s*\d{1,4})?|\d{1,4}(?:[,.]\d+)?\s*%)\s*$",
        preceding
    )
    if numeric_prefix:
        start = min(start, numeric_prefix.start(1))
    # Damaged digits can precede the first Korean glyph, e.g.
    # "��% 수납" and "��/�� 스테인리스". Do not discard them.
    damaged_numeric_prefix = re.search(
        r"(?:\ufffd{1,6}\s*/\s*\ufffd{1,6}|\ufffd{1,6}\s*%)\s*$",
        preceding,
    )
    if damaged_numeric_prefix:
        start = min(start, damaged_numeric_prefix.start())
    # Retain the initial QR/AI prefix when it belongs to Korean wording.
    prefix = text[max(0, start - 3):start]
    leading = re.search(r"(?:QR|AI)\s*$", prefix)
    if leading:
        start -= len(leading.group())
    end = _korean_scope_end(text, match.start())
    while end > start and text[end - 1] in " /|•\u00a0":
        end -= 1
    if end <= start:
        return None
    return chars[start:end], re.sub(r"\s+", " ", text[start:end]).strip()


def tight_ocr(page, line, chars, dpi, numeric_context=False):
    direction = line.get("dir", (1, 0))
    boxes = [c["bbox"] for c in chars]
    x0 = min(b[0] for b in boxes) - (min(95, line["spans"][0]["size"] * 12) if numeric_context else 2)
    x1 = max(b[2] for b in boxes) + (max(12, line["spans"][0]["size"] * 2) if numeric_context else 4)
    first_span = line["spans"][0]
    baseline = first_span["origin"][1]
    size = first_span["size"]
    upside_down = direction[0] < -0.8
    if upside_down:
        y0, y1 = baseline - size * .38, baseline + size * 1.30
    else:
        # PDF glyphs can extend beyond font metrics; tight vertical clipping
        # truncates the second half of multiword Korean OCR candidates.
        factor_top, factor_bottom = (1.30, .40) if numeric_context else (1.15, .30)
        y0, y1 = baseline - size * factor_top, baseline + size * factor_bottom
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
    # A narrow one-line OCR pass can stop after the first Korean word.
    # Retry as a single text block only for demonstrably truncated outputs.
    korean_length = sum(bool(KOR.search(c["c"])) for c in chars)
    result_korean_length = len(KOR.findall(result))
    if (korean_length >= 10 and result_korean_length < korean_length * .60):
        try:
            alternative = pytesseract.image_to_string(
                image, lang="kor+eng", config="--oem 3 --psm 6"
            ).strip()
            if len(KOR.findall(alternative)) > result_korean_length * 1.35:
                result = alternative
        except pytesseract.TesseractError:
            pass  # Preserve the original OCR candidate as evidence.
    result = re.sub(r"\s+", " ", result)
    match = KOR.search(result)
    if not match:
        return ""
    start = match.start()
    # A corrupted PDF digit such as '�배' can be restored as '4배'.
    number = re.search(r"\d\s*$", result[:start])
    if number:
        start = number.start()
    numeric_lead = re.search(
        r"(?:^|\s)(\d{1,4}(?:\s*/\s*\d{1,4})?|\d{1,4}(?:[,.]\d+)?\s*%)\s*$",
        result[:match.start()]
    )
    if numeric_lead:
        start = numeric_lead.start(1)
    prefix = re.search(r"(?:QR|AI)\s*$", result[max(0, start - 3):start])
    if prefix:
        start -= len(prefix.group())
    end = _korean_scope_end(result, match.start())
    return result[start:end].strip(" /|•")



def repair_damaged_native(native, candidate):
    """Never splice OCR numbers into native text.

    The previous regex copied only the last portion of a fraction into an
    unrelated replacement glyph (18/10 -> ...10...), producing false claims.
    Preserve the source and present OCR only as review evidence.
    """
    if "\ufffd" not in native or not candidate:
        return native, []
    # Even readable matching numbers do not authorize replacing a damaged
    # interval without a verified character-to-rectangle alignment.
    return native, ["OCR 후보 분리 보존"]


# A numeric qualifier with Korean units is not a damaged number.
NUMERIC_TOKEN_PATTERN = re.compile(
    r"(?<![A-Za-z0-9])(?:"
    r"\d{1,4}\s*/\s*\d{1,4}"
    r"|\d{1,4}(?:[.,]\d+)?\s*%"
    r"|\d{1,4}(?:[.,]\d+)?\s*(?:배|년|위|개|명|cm|mm|L|PCS|YEARS|X)\b"
    r"|(?:No\.?\s*)\d+"
    r"|\d{4}"
    r")(?!\d)", re.I
)


def normalize_numeric_token(token):
    return re.sub(r"\s+", "", token).casefold().replace(",", ".")


def numeric_tokens(text):
    return set(normalize_numeric_token(m.group())
               for m in NUMERIC_TOKEN_PATTERN.finditer(text))


def numeric_evidence_disagrees(native, ocr):
    """Report conflicts without treating a missing/unreliable OCR as proof."""
    if not ocr:
        return False
    native_tokens = numeric_tokens(native)
    ocr_tokens = numeric_tokens(ocr)
    if not ocr_tokens:
        # An OCR candidate like "409" instead of "40%" has a visible
        # number but no unit: flag it, do not silently accept or replace.
        return bool(native_tokens and re.search(r"(?<!\d)\d{1,4}(?!\d)", ocr))
    # Never treat an OCR-only token as authoritatively correct.
    return native_tokens != ocr_tokens


def source_citation_prefix(text, preceding=""):
    """Extract *observed* contiguous Euromonitor attribution fragments."""
    prefix = text.split("에디션", 1)[0]
    local = re.search(
        r"Euromonitor\s+International\s+Limited\s*,?\s*"
        r"Home\s+and\s+Garden\s+\d{4}\s*$",
        prefix, re.I
    )
    if local:
        return local.group().strip(), []
    partial = re.search(
        r"\bLimited\s*,?\s*Home\s+and\s+Garden\s+\d{4}\s*$",
        prefix, re.I
    )
    if partial:
        earlier = re.search(r"Euromonitor\s+International\s*$", preceding, re.I)
        if earlier:
            return earlier.group().strip() + " " + partial.group().strip(), []
        return partial.group().strip(), ["영문 출처 앞부분 분리 확인"]
    return "", []


def merge_source_citation(citation, native, full_text):
    """Reattach only observed citation characters without duplicating an overlap.

    A native Korean segment can start at the source's final year ("2026
    에디션"). That year is already included in the extracted English source.
    Remove the *shared rendered token*, not a distinct second year. Only
    collapse when the PDF's full native line contains a single copy at the
    citation-to-Korean boundary.
    """
    if not citation or citation in native:
        return native
    tail = re.search(r"(\d{4})\s*$", citation)
    if tail:
        year = tail.group(1)
        leading = re.match(r"^\s*" + re.escape(year) + r"(?=\s*에디션\b)", native)
        if leading:
            boundary = re.search(
                re.escape(year) + r"\s*에디션\b", full_text
            )
            if boundary and len(re.findall(re.escape(year), full_text)) == 1:
                # The year belongs to the citation and was also selected as
                # a Korean prefix; it is one original token, not two.
                native = native[leading.end():].lstrip()
    return citation + " " + native


def all_raw_lines(page, rawdict=None):
    """Lossless page-level evidence layer, independent of Korean filtering."""
    evidence = []
    if rawdict is None:
        rawdict = page.get_text("rawdict", flags=0)
    for block_id, block in enumerate(rawdict["blocks"]):
        for line_id, line in enumerate(block.get("lines", [])):
            spans = line.get("spans", [])
            if not spans:
                continue
            chars = [c for span in spans for c in span.get("chars", [])]
            if not chars:
                continue
            evidence.append({
                "id": f"p{page.number+1}:b{block_id}:l{line_id}",
                "page": page.number + 1, "block_id": block_id,
                "line_id": line_id,
                "text": "".join(c["c"] for c in chars),
                "bbox": [round(float(v), 2) for v in line["bbox"]],
                "direction": [round(float(v), 4) for v in line.get("dir", (1, 0))],
                "font_size": round(float(spans[0]["size"]), 2),
                "spans": [{
                    "span_id": i,
                    "text": "".join(c["c"] for c in span.get("chars", [])),
                    "chars": [{
                        "text": c["c"],
                        "bbox": [round(float(v), 2) for v in c["bbox"]]
                    } for c in span.get("chars", [])]
                } for i, span in enumerate(spans)],
                "source": "native_pdf"
            })
    return evidence




NUMERIC_CONTEXT = re.compile(
    r"(?:최대.{0,18}(?:수납|공간|절약)|스테인리스|매출.{0,22}기준|"
    r"Euromonitor|Home and Garden|코팅.{0,18}배|보증.{0,14}년)",
    re.I,
)


def candidate_quality_warnings(native, candidate):
    """Describe suspect OCR artifacts; never silently change the candidate."""
    if not candidate:
        return []
    raw_latin = set(re.findall(r"\b[A-Za-z]{2,4}\b", native, re.I))
    unexpected_latin = [
        token for token in re.findall(r"\b[A-Za-z]{2,4}\b", candidate)
        if token not in raw_latin and token.upper() not in {"QR", "AI"}
    ]
    return ["OCR 후보에 불확실한 영문 조각이 포함됨 · 원본 확인"] if unexpected_latin else []

def numeric_peer_for(row, raw_lines):
    """Collect nearby standalone numeric glyphs as evidence, not auto-fixes."""
    if not re.search(r"(?:최대|수납|절약|내구성|스테인리스)", row["korean_text"]):
        return []
    own = fitz.Rect(row["x0"], row["y0"], row["x1"], row["y1"])
    peers = []
    for item in raw_lines:
        value = item["text"].strip()
        if not re.fullmatch(r"\d{1,4}(?:[,.]\d+)?\s*(?:%|배|년|위|cm|L)|\d{1,4}\s*/\s*\d{1,4}", value, re.I):
            continue
        box = fitz.Rect(item["bbox"])
        if box.intersects(own):
            continue
        dy = max(0, box.y0-own.y1, own.y0-box.y1)
        dx = max(0, box.x0-own.x1, own.x0-box.x1)
        font = max(float(row["font_size"]), float(item["font_size"]), 1)
        if (dy <= font*1.5 and dx <= font*8 and
                abs(item["direction"][0]-row["dir_x"]) < .15 and
                abs(item["direction"][1]-row["dir_y"]) < .15):
            peers.append(item)
    return sorted(peers, key=lambda e:
                  abs(e["bbox"][0]-row["x0"])+abs(e["bbox"][1]-row["y0"]))


def extract_pdf(pdf_bytes, filename, dpi=350, mode="korean", max_pages=None):
    rows, summaries = [], []
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    try:
        if max_pages is not None and doc.page_count > max_pages:
            raise ValueError(f"파일이 최대 페이지 수({max_pages})를 초과했습니다.")
        for page_num, page in enumerate(doc, 1):
            page_rows = 0
            ocr_lines = 0
            rawdict = page.get_text("rawdict", flags=0)
            raw_lines = all_raw_lines(page, rawdict=rawdict)
            previous_raw_by_block = {}
            for block_id, block in enumerate(rawdict["blocks"]):
                for line_id, line in enumerate(block.get("lines", [])):
                    evidence_id = f"p{page_num}:b{block_id}:l{line_id}"
                    full_text = "".join(
                        c["c"] for span in line.get("spans", [])
                        for c in span.get("chars", [])
                    )
                    previous_text = previous_raw_by_block.get(block_id, "")
                    previous_raw_by_block[block_id] = full_text
                    segment = korean_segment(line)
                    if not segment:
                        continue
                    chars, native = segment
                    # Keep the literal whitespace directly before the first
                    # Korean glyph, even if it was removed from the substring
                    # used for OCR. On circular labels a new rotated PDF span
                    # can begin with a real word separator (e.g. " 팬 • T").
                    original_chars = [c["c"] for span in line["spans"] for c in span["chars"]]
                    first_korean = next(
                        (i for i, ch in enumerate(original_chars) if KOR.search(ch)),
                        None,
                    )
                    curve_leading_space = bool(
                        first_korean is not None
                        and first_korean > 0
                        and original_chars[first_korean - 1].isspace()
                    )
                    direction = line.get("dir", (1, 0))
                    curved = abs(direction[1]) > .3
                    broken = "\ufffd" in native
                    candidate = ""
                    numeric_sensitive = bool(NUMERIC_CONTEXT.search(native) or re.search(r"\ufffd{1,5}\s*(?:%|/\s*\ufffd)", native))
                    if (broken or mode == "all") and not curved:
                        candidate = tight_ocr(
                            page, line, chars, dpi,
                            numeric_context=numeric_sensitive,
                        )
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
                    source_numbers = numeric_tokens(native)
                    ocr_numbers = numeric_tokens(candidate)
                    explicit_damage = bool(re.search(
                        r"\ufffd{1,6}\s*(?:%|/\s*\ufffd)", native
                    ))
                    numeric_discrepancy = bool(
                        explicit_damage or numeric_evidence_disagrees(native, candidate)
                    )
                    citation, citation_warnings = source_citation_prefix(
                        full_text, previous_text
                    )
                    if citation and KOR.search(native):
                        best = merge_source_citation(citation, best, full_text)
                    warnings = []
                    if numeric_discrepancy:
                        warnings.append("수치 대조 필요 · 원본 확인")
                        status = "수치 대조 필요 · 원본 확인"
                    elif broken:
                        warnings.append("손상된 글자 · OCR 원본 대조 필요")
                    warnings.extend(citation_warnings)
                    warnings.extend(candidate_quality_warnings(native, candidate))
                    if citation_warnings and not numeric_discrepancy:
                        status = "영문 출처 대조 필요 · 원본 확인"
                    rows.append({
                        "file": filename,
                        "page": page_num,
                        "block_id": block_id,
                        "line_id": line_id,
                        "curved": bool(curved),
                        "curve_leading_space": curve_leading_space,
                        "dir_x": round(direction[0], 3),
                        "dir_y": round(direction[1], 3),
                        "font_size": round(line["spans"][0]["size"], 2),
                        "baseline_y": round(line["spans"][0]["origin"][1], 2),
                        "korean_text": best,
                        "status": status,
                        "pdf_original": native,
                        "ocr_candidate": candidate,
                        "numeric_review": numeric_discrepancy,
                        "native_numeric_tokens": sorted(source_numbers),
                        "ocr_numeric_tokens": sorted(ocr_numbers),
                        "warnings": warnings,
                        "raw_evidence_ids": [evidence_id] + (
                            [f"p{page_num}:b{block_id}:l{line_id-1}"]
                            if line_id > 0 and "Euromonitor" in citation
                            and "Euromonitor" not in full_text
                            else []
                        ),
                        "source_citation": citation,
                        "x0": round(min(c["bbox"][0] for c in chars), 1),
                        "y0": round(min(c["bbox"][1] for c in chars), 1),
                        "x1": round(max(c["bbox"][2] for c in chars), 1),
                        "y1": round(max(c["bbox"][3] for c in chars), 1),
                    })
                    current = rows[-1]
                    peers = numeric_peer_for(current, raw_lines)
                    current["numeric_peer_evidence"] = [
                        {"id": e["id"], "text": e["text"], "bbox": e["bbox"]}
                        for e in peers[:5]
                    ]
                    if peers and not numeric_tokens(current["korean_text"]):
                        current["numeric_review"] = True
                        current["warnings"].append("수치 대조 필요 · 숫자 객체 연결 확인")
                        current["status"] = "수치 대조 필요 · 숫자 객체 연결 확인"
                    page_rows += 1
            summaries.append({
                "file": filename, "page": page_num,
                "korean_lines": page_rows, "ocr_lines": ocr_lines,
                "raw_evidence": raw_lines,
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
        summary_metadata = [{k: v for k, v in item.items() if k != "raw_evidence"}
                            for item in summaries]
        archive.writestr("summary.json", json.dumps(summary_metadata, ensure_ascii=False, indent=2))
        archive.writestr("raw_pdf_evidence.json", json.dumps([
            {"file": item["file"], "page": item["page"],
             "lines": item.get("raw_evidence", [])}
            for item in summaries
        ], ensure_ascii=False, indent=2))
    return output.getvalue()
