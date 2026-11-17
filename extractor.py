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

from ocr_batch import batch_ocr, strip_ocr
from region_text import (find_untexted_regions, find_label_tables, render_region,
                         crop_box_to_pdf, direction_for, split_text_bands)

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


def _ocr_korean_span(result):
    """Korean reading range of an OCR string.

    The crop already covers only the Korean glyph boxes of the native PDF
    line, so the range is first Hangul (with a numeric / QR / AI lead) to the
    LAST Hangul, plus its directly attached closing punctuation. Latin
    garbage that OCR produces *inside* a Korean sentence (e.g. 'SEA' for a
    misread word) must not truncate the rest of the sentence; it is kept as
    evidence and the native text stays authoritative.
    """
    result = re.sub(r"\s+", " ", result or "").strip()
    match = KOR.search(result)
    if not match:
        return ""
    start = match.start()
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
    last = max(m.end() for m in KOR.finditer(result))
    tail = re.match(r"[.)\]）」』%]*", result[last:])
    end = last + (tail.end() if tail else 0)
    return result[start:end].strip(" /|•")


def ocr_crop_rect(page, line, chars, numeric_context=False):
    boxes = [c["bbox"] for c in chars]
    size = line["spans"][0]["size"]
    x0 = min(b[0] for b in boxes) - (min(95, size * 12) if numeric_context else 2)
    x1 = max(b[2] for b in boxes) + (max(12, size * 2) if numeric_context else 4)
    baseline = line["spans"][0]["origin"][1]
    upside_down = line.get("dir", (1, 0))[0] < -0.8
    if upside_down:
        # Rotated 180°: the glyphs sit ABOVE the baseline in page space. A
        # taller window pulls in half of the neighbouring line and makes
        # Tesseract misread short words (e.g. 테팔 -> "AIS").
        y0, y1 = baseline - size * .25, baseline + size * 1.05
    else:
        # PDF glyphs can extend beyond font metrics; tight vertical clipping
        # truncates the second half of multiword Korean OCR candidates.
        factor_top, factor_bottom = (1.30, .40) if numeric_context else (1.15, .30)
        y0, y1 = baseline - size * factor_top, baseline + size * factor_bottom
    return fitz.Rect(x0, y0, x1, y1) & page.rect, upside_down


def line_text_rgb(line):
    """Printed colour of the Korean glyphs of a native PDF line."""
    for span in line.get("spans", []):
        if any(KOR.search(c["c"]) for c in span.get("chars", [])):
            colour = int(span.get("color", 0))
            return ((colour >> 16) & 255, (colour >> 8) & 255, colour & 255)
    return None


def render_ocr_crop(page, rect, dpi, upside_down=False, text_rgb=None):
    """Render one crop at the OCR DPI as a dark-text-on-white image.

    With the native glyph colour known, every pixel is mapped by its colour
    distance to that text colour: the printed letters become black and all
    other inks (dielines crossing a word, coloured panels, neighbouring
    artwork) fade to white. This keeps a cyan cutting line through '인덕션'
    from hiding the word.
    """
    import numpy as np
    from region_text import page_pixmap
    pix = page_pixmap(page, rect, dpi)
    if text_rgb is not None and pix.n >= 3:
        pixels = np.frombuffer(pix.samples, dtype=np.uint8).reshape(
            pix.height, pix.width, pix.n)[:, :, :3].astype(float)
        text = np.array(text_rgb, dtype=float)
        sample = (pixels[::3, ::3].reshape(-1, 3).astype(int) // 16)
        packed = sample[:, 0] * 256 + sample[:, 1] * 16 + sample[:, 2]
        mode = int(np.bincount(packed, minlength=4096).argmax())
        background = np.array([mode // 256, (mode // 16) % 16, mode % 16]) * 16 + 8
        reference = max(np.sqrt(((background - text) ** 2).sum()), 60.0)
        distance = np.sqrt(((pixels - text) ** 2).sum(axis=2))
        image = Image.fromarray(np.clip(distance / reference * 255, 0, 255).astype("uint8"))
    else:
        image = ImageOps.autocontrast(ImageOps.grayscale(
            Image.open(io.BytesIO(pix.tobytes("png")))))
    if upside_down:
        image = image.rotate(180, expand=True)
    return image


# Per-call limit for single-line OCR. Streamlit Cloud CPU throttling made
# 6 s too short: calls timed out and verified digits fell back to '□'.
OCR_TIMEOUT = 30


def tight_ocr(page, line, chars, dpi, numeric_context=False, stats=None, psm=7, scale=1.0):
    """Individual OCR of one damaged line (fallback path)."""
    rect, upside_down = ocr_crop_rect(page, line, chars, numeric_context)
    if rect.is_empty:
        return ""
    image = render_ocr_crop(page, rect, dpi, upside_down, line_text_rgb(line))
    if scale != 1.0:
        # Same 350 DPI render, enlarged: an independent second look at small
        # thin glyphs (no lower-resolution reading is ever used).
        image = image.resize((int(image.width * scale), int(image.height * scale)),
                             Image.LANCZOS)
    # Border is critical: Tesseract rejects tightly cropped short lines.
    image = ImageOps.expand(image, border=25, fill=255)

    def read(psm):
        import time
        started = time.perf_counter()
        try:
            return pytesseract.image_to_string(
                image, lang="kor+eng", config=f"--oem 3 --psm {psm}", timeout=OCR_TIMEOUT
            ).strip()
        finally:
            if stats is not None:
                stats["calls"] = stats.get("calls", 0) + 1
                stats["seconds"] = round(stats.get("seconds", 0.0)
                                         + time.perf_counter() - started, 3)

    try:
        result = _ocr_korean_span(read(psm))
    except pytesseract.TesseractNotFoundError as exc:
        raise RuntimeError("Tesseract 프로그램 설치가 필요합니다. packages.txt를 확인하세요.") from exc
    except RuntimeError:
        if stats is not None:
            stats.setdefault("timeouts", 0)
            stats["timeouts"] += 1
        return ""  # OCR timeout: retain PDF evidence and continue QA.
    except pytesseract.TesseractError as exc:
        raise RuntimeError("Tesseract 한국어 언어팩 설치를 확인하세요.") from exc
    # A narrow one-line OCR pass can stop after the first Korean word.
    # Decide on the SAME post-processed text that is returned.
    korean_length = sum(bool(KOR.search(c["c"])) for c in chars)
    if korean_length >= 10 and len(KOR.findall(result)) < korean_length * .60:
        try:
            alternative = _ocr_korean_span(read(6))
            if len(KOR.findall(alternative)) > len(KOR.findall(result)) * 1.35:
                result = alternative
        except (pytesseract.TesseractError, RuntimeError):
            pass  # Preserve the original OCR candidate as evidence.
    return result


def _aligned(opcode, native, candidate):
    """Equal text, or a pure whitespace difference, counts as aligned."""
    tag, i1, i2, j1, j2 = opcode
    if tag == "equal":
        return True
    return not native[i1:i2].strip() and not candidate[j1:j2].strip()


def fill_damaged_glyphs(native, candidate):
    """Fill only U+FFFD holes in native PDF text from an aligned OCR reading.

    Native readable characters are authoritative and are never replaced.
    A hole is filled only when it sits between exactly aligned native/OCR
    text and the OCR material in its place is plausible for a glyph hole:
    a space for a single hole, or the same number of digits ('/', '.', ','
    kept as aligned literals). Everything else stays unresolved (U+FFFD).
    Returns (text, filled, unresolved) where filled lists (hole, value).
    """
    if "\ufffd" not in native or not candidate:
        return native, [], native.count("\ufffd")
    native_hangul = "".join(KOR.findall(native))
    ocr_hangul = "".join(KOR.findall(candidate))
    if not native_hangul or SequenceMatcher(None, native_hangul, ocr_hangul,
                                            autojunk=False).ratio() < .6:
        return native, [], native.count("\ufffd")
    matcher = SequenceMatcher(None, native, candidate, autojunk=False)
    opcodes = matcher.get_opcodes()
    output, filled = [], []
    for index, (tag, i1, i2, j1, j2) in enumerate(opcodes):
        source = native[i1:i2]
        if "\ufffd" not in source:
            output.append(source)
            continue
        previous_ok = index == 0 or _aligned(opcodes[index - 1], native, candidate)
        next_ok = index == len(opcodes) - 1 or _aligned(opcodes[index + 1], native, candidate)
        reading = candidate[j1:j2]
        value = None
        core = source.strip()
        if tag == "replace" and core and set(core) == {"\ufffd"} and core != source:
            # ' \ufffd' vs '1': whitespace next to the hole is native text and
            # stays; only the hole itself is evaluated.
            compact = re.sub(r"\s+", "", reading)
            if previous_ok and next_ok and compact.isdigit() and len(compact) == len(core):
                lead = source[:len(source) - len(source.lstrip())]
                trail = source[len(source.rstrip()):]
                output.append(lead + compact + trail)
                filled.append((core, compact))
            else:
                output.append(source)
            continue
        if tag == "replace" and set(source) != {"\ufffd"}:
            # Mixed run such as '\ufffd제품과\ufffd' vs ' MET ': the native
            # letters stay; only boundary holes facing an OCR space are filled.
            pieces = list(source)
            if pieces[0] == "\ufffd" and reading[:1].isspace() and previous_ok:
                pieces[0] = " "
                filled.append(("\ufffd", " "))
            if pieces[-1] == "\ufffd" and reading[-1:].isspace() and next_ok:
                pieces[-1] = " "
                filled.append(("\ufffd", " "))
            output.append("".join(pieces))
            continue
        if tag == "replace" and previous_ok and next_ok and set(source) == {"\ufffd"}:
            compact = re.sub(r"\s+", "", reading)
            if not compact and len(source) == 1:
                value = " "
            elif compact.isdigit() and len(compact) == len(source):
                value = compact
        if value is None:
            output.append(source)
        else:
            output.append(value)
            filled.append((source, value))
    text = "".join(output)
    return text, filled, text.count("\ufffd")


def merge_hole_readings(native, readings):
    """Combine several hole-filled readings of the SAME native line.

    fill_damaged_glyphs() is length preserving, so position i of every
    reading corresponds to native[i]. A digit is accepted only when at
    least two independent OCR readings agree on it; a disagreement or a
    single reading leaves the hole unresolved (shown as □). A space needs
    one reading and no competing digit.
    """
    output = list(native)
    for index, char in enumerate(native):
        if char != "\ufffd":
            continue
        values = [reading[index] for reading in readings
                  if len(reading) == len(native) and reading[index] != "\ufffd"]
        digits = [value for value in values if value.isdigit()]
        if digits:
            ranked = sorted(((digits.count(d), d) for d in set(digits)), reverse=True)
            top_count, top = ranked[0]
            runner_up = ranked[1][0] if len(ranked) > 1 else 0
            # At least two readings agree AND they outnumber any other digit.
            if top_count >= 2 and top_count > runner_up and " " not in values:
                output[index] = top
        elif " " in values:
            output[index] = " "
    return "".join(output)


def repair_damaged_native(native, candidate):
    """Use a second OCR reading only for directly aligned damaged numeric glyphs.

    Require a single numeric hole, unchanged readable Korean context, and a
    matching unit. Keep the original PDF text and numeric_review=True in the
    caller. Do not fill values from the master or other-language captions.
    """
    if "\ufffd" not in native or not candidate:
        return native, []
    # A line with several damaged numbers is ambiguous: keep OCR as evidence.
    holes = list(re.finditer(
        r"\ufffd{1,5}\s*/\s*\ufffd{1,5}(?=\s*스테인리스)|"
        r"\ufffd{1,5}(?=\s*(?:%|배|년|개|위)\b|\s*%)", native))
    if len(holes) != 1:
        return native, ["OCR 후보 분리 보존"]
    hole = holes[0]
    before, after = native[:hole.start()], native[hole.end():]
    # Compare meaningful readable Korean anchors on either side, avoiding
    # substitutions into unrelated text printed nearby.
    anchors = re.findall(r"[가-힣]{2,}", before + " " + after)
    if not anchors or not any(word in candidate for word in anchors):
        return native, ["OCR 후보 분리 보존"]
    if "/" in hole.group():
        observed = re.findall(r"(?<!\d)(\d{1,2}\s*/\s*\d{1,2})(?=\s*스테인리스)", candidate)
    else:
        unit = re.match(r"\s*(%|배|년|개|위)", after)
        if not unit:
            return native, ["OCR 후보 분리 보존"]
        observed = re.findall(
            r"(?<!\d)(\d{1,3})\s*" + re.escape(unit.group(1)), candidate)
    values = {re.sub(r"\s+", "", x) for x in observed}
    if len(values) != 1:
        return native, ["OCR 후보 분리 보존"]
    value = next(iter(values))
    # Reject OCR numbers that disagree with any intact same-unit native value.
    updated = before + value + after
    return updated, ["OCR 숫자 복원 후보 · 인쇄 영역 2차 판독 · 최종 확인 필요"]


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
    if not re.search(r"(?:최대|수납|절약|내구성|스테인리스|세계\\s*판매|품질\\s*보증|코팅|기준|인덕션)", row["korean_text"]):
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
        # Distance is measured in the ROW's text size: a large headline
        # number ('40%') must not reach unrelated small copy below it.
        font = max(float(row["font_size"]), 1)
        if (dy <= font*1.5 and dx <= font*8 and
                abs(item["direction"][0]-row["dir_x"]) < .15 and
                abs(item["direction"][1]-row["dir_y"]) < .15):
            peers.append(item)
    return sorted(peers, key=lambda e:
                  abs(e["bbox"][0]-row["x0"])+abs(e["bbox"][1]-row["y0"]))


def _row_for_ocr_line(filename, page_num, region_index, line_index, text, region,
                      bbox, conf):
    direction = direction_for(region["rotation"])
    height = max(1.0, bbox[3] - bbox[1])
    return {
        "file": filename, "page": page_num,
        # Each OCR line is its own block: table cells and badges are never
        # merged into prose paragraphs by the layout stage.
        "block_id": f"ocr{region_index}-{line_index}", "line_id": 0,
        "curved": False, "curve_leading_space": False,
        "dir_x": direction[0], "dir_y": direction[1],
        "font_size": round(height, 2), "baseline_y": bbox[3],
        "korean_text": text,
        "status": "이미지·벡터 문구 OCR · 원본 확인 필요",
        "pdf_original": "",
        "ocr_candidate": text,
        "numeric_review": bool(re.search(r"\d", text)),
        "native_numeric_tokens": [],
        "ocr_numeric_tokens": sorted(numeric_tokens(text)),
        "warnings": ["텍스트 레이어 없음 · " + ("이미지" if region["kind"] == "image" else "벡터 윤곽")
                     + " 영역 350 DPI OCR 판독 · 원본 확인 필요"],
        "raw_evidence_ids": [f"p{page_num}:ocr-region{region_index}"],
        "source_citation": "",
        "text_source": "image_ocr" if region["kind"] == "image" else "vector_ocr",
        "ocr_reconstructed": True, "region_ocr": True, "ocr_confidence": conf,
        "ocr_filled": [],
        "x0": bbox[0], "y0": bbox[1], "x1": bbox[2], "y1": bbox[3],
        "numeric_peer_evidence": [],
    }


def _compact_korean(text):
    return re.sub(r"[^가-힣0-9A-Za-z]", "", text or "")


def _region_rows(filename, page_num, regions, region_lines, region_sizes, dpi,
                 existing_texts):
    rows = []
    for index, (region, lines, size) in enumerate(zip(regions, region_lines, region_sizes)):
        # Small outline / badge regions are mostly logos; demand a clearly
        # read Korean word there. Large Korean panels use the normal gate.
        strict = region["kind"] == "vector" and region.get("glyphs", 0) < 100
        useful = [line for line in lines
                  if len(KOR.findall(line["text"])) >= (3 if strict else 2)
                  and line["conf"] >= (85 if strict else 45)]
        if not useful:
            continue
        # Inside a Korean panel (e.g. 한글표시사항 table) keep every row that
        # carries Korean, including rows that are mostly Latin
        # ('제조자 SUPOR VIETNAM CO.,LTD').
        useful = [line for line in lines
                  if KOR.search(line["text"]) and line["conf"] >= 45]
        if region["kind"] == "image":
            # One badge = one printed unit: keep all its lines in order.
            kept = [line for line in lines if line["conf"] >= 45 and line["text"].strip()]
            text = " ".join(line["text"] for line in kept)
            box = (min(l["bbox"][0] for l in kept), min(l["bbox"][1] for l in kept),
                   max(l["bbox"][2] for l in kept), max(l["bbox"][3] for l in kept))
            groups = [(text, box, round(sum(l["conf"] for l in kept) / len(kept), 1))]
        else:
            groups = [(line["text"], line["bbox"], line["conf"]) for line in useful]
        for line_index, (text, box, conf) in enumerate(groups):
            compact = _compact_korean(text)
            if any(compact and (compact in other or other in compact)
                   for other in existing_texts if len(other) >= 4):
                continue  # already extracted from the native text layer
            # A badge is one printed unit: point at the whole image region.
            pdf_box = ([round(v, 1) for v in region["rect"]] if region["kind"] == "image"
                       else crop_box_to_pdf(region, box, size, dpi))
            rows.append(_row_for_ocr_line(filename, page_num, index, line_index,
                                          text, region, pdf_box, conf))
    return rows


def extract_pdf(pdf_bytes, filename, dpi=350, mode="korean", max_pages=None):
    import time
    rows, summaries = [], []
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    try:
        if max_pages is not None and doc.page_count > max_pages:
            raise ValueError(f"파일이 최대 페이지 수({max_pages})를 초과했습니다.")
        for page_num, page in enumerate(doc, 1):
            started = time.perf_counter()
            stats = {"batch": {}, "fallback": {}, "damaged_lines": 0, "regions": 0}
            warnings_page = []
            page_rows = 0
            ocr_lines = 0
            rawdict = page.get_text("rawdict", flags=0)
            raw_lines = all_raw_lines(page, rawdict=rawdict)
            previous_raw_by_block = {}
            segments = []
            for block_id, block in enumerate(rawdict["blocks"]):
                for line_id, line in enumerate(block.get("lines", [])):
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
                    direction = line.get("dir", (1, 0))
                    segments.append({
                        "block_id": block_id, "line_id": line_id, "line": line,
                        "chars": chars, "native": native, "full_text": full_text,
                        "previous_text": previous_text, "direction": direction,
                        "curved": abs(direction[1]) > .3,
                        "broken": "\ufffd" in native,
                    })
            # Statutory 한글표시사항 tables are out of QA scope: find them by
            # structure and drop their native lines before any OCR.
            label_tables = find_label_tables(page, rawdict) if mode != "native" else []
            stats["label_tables"] = len(label_tables)
            if label_tables:
                def in_label_table(segment):
                    box = fitz.Rect(min(c["bbox"][0] for c in segment["chars"]),
                                    min(c["bbox"][1] for c in segment["chars"]),
                                    max(c["bbox"][2] for c in segment["chars"]),
                                    max(c["bbox"][3] for c in segment["chars"]))
                    centre = (box.tl + box.br) / 2
                    return any(centre in table for table in label_tables)
                kept = [segment for segment in segments if not in_label_table(segment)]
                stats["label_table_native_lines"] = len(segments) - len(kept)
                segments = kept
            stats["native_seconds"] = round(time.perf_counter() - started, 3)

            # ---- one rendering + ONE Tesseract process for every crop ----
            render_started = time.perf_counter()
            targets = [s for s in segments
                       if (s["broken"] or mode == "all") and not s["curved"]]
            images = []
            for target in targets:
                target["numeric_sensitive"] = bool(
                    NUMERIC_CONTEXT.search(target["native"])
                    or re.search(r"\ufffd{1,5}\s*(?:%|/\s*\ufffd)", target["native"]))
                rect, upside_down = ocr_crop_rect(
                    page, target["line"], target["chars"], target["numeric_sensitive"])
                target["rect_empty"] = rect.is_empty
                images.append(render_ocr_crop(page, rect, dpi, upside_down,
                                              line_text_rgb(target["line"]))
                              if not rect.is_empty else Image.new("L", (10, 10), 255))
            regions = (find_untexted_regions(page, rawdict, exclude=label_tables)
                       if mode != "native" else [])
            region_images = [render_region(page, region, dpi) for region in regions]
            stats["render_seconds"] = round(time.perf_counter() - render_started, 3)
            stats["damaged_lines"] = len(targets)
            stats["regions"] = len(regions)
            def run_batch(batch_images, psm, key, label):
                if not batch_images:
                    return []
                try:
                    return batch_ocr(batch_images, psm=psm, stats=stats.setdefault(key, {}))
                except pytesseract.TesseractNotFoundError as exc:
                    raise RuntimeError("Tesseract 프로그램 설치가 필요합니다. packages.txt를 확인하세요.") from exc
                except (RuntimeError, pytesseract.TesseractError) as exc:
                    warnings_page.append(f"{label} 일괄 OCR 실패 또는 시간 초과: {exc}")
                    return [[] for _ in batch_images]

            # ONE Tesseract process (layout mode psm 4, a column of lines)
            # reads: damaged native lines + vector-outline regions + each text
            # band of small raster badges. Per-crop binarization keeps every
            # crop independent of its neighbours in the sheet.
            vector_ids = [i for i, r in enumerate(regions) if r["kind"] == "vector"]
            image_ids = [i for i, r in enumerate(regions) if r["kind"] == "image"]
            # Badge text lines. Small badges carry no reliable orientation
            # cue (a badge on a folded flap is printed upside down), so each
            # badge is read upright AND turned 180°, and the reading with more
            # confidently recognised Korean wins. Lines are normalised to one
            # height so the single-line strip has a stable baseline.
            band_owner, band_images = [], []
            for i in image_ids:
                for turn in (0, 180):
                    image = region_images[i] if turn == 0 else region_images[i].rotate(180)
                    for (top, bottom), band in split_text_bands(image):
                        if band.height > 200:      # picture, not a text line
                            continue
                        band = band.resize((max(1, int(band.width * 64 / band.height)), 64),
                                           Image.LANCZOS)
                        band_owner.append((i, turn))
                        band_images.append(band)
            # Process plan (each call = one Tesseract process, 350 DPI crops).
            # Streamlit Cloud cost scales with OCR'd PIXELS, so sheets carry
            # no blank padding:
            #  1. all damaged native lines side by side in ONE single-line
            #     strip (psm 7, the mode proven for these lines);
            #  2. each dense outline panel (>= 60 glyphs, e.g. the
            #     한글표시사항 table) on its own (psm 4 keeps table rows);
            #  3. badge text lines from small images in one strip (psm 7).
            # Sparse outline clusters (< 60 glyphs: logos, pictograms) are not
            # OCR'd; they are counted in the timing table.
            large_vector = [i for i in vector_ids if regions[i].get("glyphs", 0) >= 60]
            stats["skipped_small_vector_regions"] = len(vector_ids) - len(large_vector)
            # Lines whose holes are NUMBERS are read on their own twice (tight
            # and wide crop, psm 7) and a digit is used only if both agree.
            # Lines with only spacing/letter holes share one strip.
            for target in targets:
                target["numeric_hole"] = bool(re.search(
                    r"\ufffd+\s*(?:%|/|배|개|년|위)|/\s*\ufffd", target["native"]))
            strip_ids = [k for k, t in enumerate(targets) if not t["numeric_hole"]]
            first = [[] for _ in images]
            if strip_ids:
                try:
                    for k, lines in zip(strip_ids, strip_ocr(
                            [images[k] for k in strip_ids], stats=stats.setdefault("batch", {}))):
                        first[k] = lines
                except (RuntimeError, pytesseract.TesseractError) as exc:
                    warnings_page.append(f"손상 문구 일괄 OCR 실패 또는 시간 초과: {exc}")
            # Badge text lines: one more process, single-line mode.
            if band_images:
                try:
                    first = first + strip_ocr(band_images, stats=stats.setdefault("badge", {}))
                except (RuntimeError, pytesseract.TesseractError) as exc:
                    warnings_page.append(f"이미지 배지 OCR 실패 또는 시간 초과: {exc}")
                    first = first + [[] for _ in band_images]
            line_results = first[:len(images)]
            region_results = [[] for _ in regions]
            offset = len(images)
            readings = {}
            for (i, turn), lines in zip(band_owner, first[offset:]):
                readings.setdefault((i, turn), []).extend(lines)

            def korean_score(lines):
                return sum(len(KOR.findall(l["text"])) for l in lines if l["conf"] >= 60)

            for i in image_ids:
                upright, turned = readings.get((i, 0), []), readings.get((i, 180), [])
                region_results[i] = turned if korean_score(turned) > korean_score(upright) else upright
            for i in large_vector:
                region_results[i] = run_batch([region_images[i]], 4, "table_reread",
                                              "한국어 표 영역")[0]
            # Rows of a Korean panel that came out weak (e.g. a row beside a
            # pictogram) are re-read as single lines - all of them in ONE
            # single-line strip - and replaced only when the re-read shows
            # more Korean with good confidence.
            weak = []
            for i in large_vector:
                image = region_images[i]
                for index, line in enumerate(region_results[i]):
                    if line["conf"] < 60 or len(KOR.findall(line["text"])) < 2:
                        top = max(0, line["bbox"][1] - 8)
                        bottom = min(image.height, line["bbox"][3] + 8)
                        if bottom - top >= 12:
                            weak.append((i, index, image.crop((0, top, image.width, bottom)), top))
            if weak:
                try:
                    reread = strip_ocr([crop for _, _, crop, _ in weak],
                                       stats=stats.setdefault("line_reread", {}))
                except (RuntimeError, pytesseract.TesseractError) as exc:
                    warnings_page.append(f"표 행 재판독 실패 또는 시간 초과: {exc}")
                    reread = [[] for _ in weak]
                for (i, index, crop, top), lines in zip(weak, reread):
                    if not lines:
                        continue
                    best = max(lines, key=lambda l: len(KOR.findall(l["text"])))
                    old_line = region_results[i][index]
                    others = ["".join(KOR.findall(l["text"])) for k, l in enumerate(region_results[i])
                              if k != index]
                    new_korean = "".join(KOR.findall(best["text"]))
                    duplicate = any(other and SequenceMatcher(None, new_korean, other).ratio() > .6
                                    for other in others)
                    if (len(KOR.findall(best["text"])) > len(KOR.findall(old_line["text"]))
                            and best["conf"] >= 60 and not duplicate):
                        x0, y0, x1, y1 = best["bbox"]
                        region_results[i][index] = dict(best, bbox=(x0, y0 + top, x1, y1 + top))
            ocr_lines = len(targets)
            for target, lines in zip(targets, line_results):
                native = target["native"]
                if target["rect_empty"]:
                    target.update(candidate="", filled_text=native, filled=[],
                                  unresolved=native.count("\ufffd"), digit_disagreement=False)
                    continue
                readings, candidates = [], []
                if target["numeric_hole"]:
                    for wide in (False, True):
                        reading = tight_ocr(page, target["line"], target["chars"], dpi,
                                            numeric_context=wide, stats=stats["fallback"])
                        if reading:
                            candidates.append(reading)
                            readings.append(fill_damaged_glyphs(native, reading)[0])
                    if "\ufffd" in merge_hole_readings(native, readings):
                        # Tie-break: the tight crop enlarged 1.5x. (The wide
                        # crop can take in neighbouring artwork, e.g. a photo,
                        # and misread a digit: 5 -> 9.)
                        reading = tight_ocr(page, target["line"], target["chars"], dpi,
                                            numeric_context=False, stats=stats["fallback"],
                                            scale=1.5)
                        if reading:
                            candidates.append(reading)
                            readings.append(fill_damaged_glyphs(native, reading)[0])
                else:
                    candidate = _ocr_korean_span(" ".join(l["text"] for l in lines))
                    first_text, _, unresolved = fill_damaged_glyphs(native, candidate)
                    if candidate:
                        candidates.append(candidate)
                        readings.append(first_text)
                    weak = len(KOR.findall(candidate)) < len(KOR.findall(native)) * .85
                    if unresolved or weak or not candidate:
                        second = tight_ocr(page, target["line"], target["chars"], dpi,
                                           numeric_context=target["numeric_sensitive"],
                                           stats=stats["fallback"])
                        if second:
                            candidates.append(second)
                            readings.append(fill_damaged_glyphs(native, second)[0])
                candidate = " ‖ ".join(candidates)
                filled_text = merge_hole_readings(native, readings)
                filled = [(h, v) for h, v in zip(native, filled_text)
                          if h == "\ufffd" and v != "\ufffd"]
                disagreement = any(
                    len(r) == len(native) and r[i] != "\ufffd" and r[i].isdigit()
                    and filled_text[i] == "\ufffd"
                    for r in readings for i in range(len(native)))
                target.update(candidate=candidate, filled_text=filled_text,
                              filled=filled, unresolved=filled_text.count("\ufffd"),
                              digit_disagreement=disagreement)

            for target in segments:
                block_id, line_id = target["block_id"], target["line_id"]
                line, chars, native = target["line"], target["chars"], target["native"]
                full_text, previous_text = target["full_text"], target["previous_text"]
                evidence_id = f"p{page_num}:b{block_id}:l{line_id}"
                original_chars = [c["c"] for span in line["spans"] for c in span["chars"]]
                first_korean = next(
                    (i for i, ch in enumerate(original_chars) if KOR.search(ch)),
                    None,
                )
                # Keep the literal whitespace directly before the first
                # Korean glyph on curved labels (e.g. " 팬 • T").
                curve_leading_space = bool(
                    first_korean is not None
                    and first_korean > 0
                    and original_chars[first_korean - 1].isspace()
                )
                direction = target["direction"]
                curved = target["curved"]
                broken = target["broken"]
                candidate = target.get("candidate", "")
                filled = target.get("filled", [])
                if broken:
                    best = target.get("filled_text", native)
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
                if broken:
                    # Damaged native glyphs: the numbers are trustworthy only
                    # if every numeric hole was filled by agreeing readings.
                    numeric_discrepancy = bool(
                        target.get("digit_disagreement")
                        or re.search(r"\ufffd+\s*(?:%|/|배|개|년|위)|/\s*\ufffd", best)
                    )
                else:
                    numeric_discrepancy = bool(
                        explicit_damage or numeric_evidence_disagrees(native, candidate))
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
                if target.get("digit_disagreement"):
                    warnings.append("OCR 숫자 판독 불일치 · 숫자 미복원(□) · 원본 PDF 확인 필요")
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
                    "ocr_filled": [value for _, value in filled],
                    "ocr_reconstructed": bool(filled),
                    "text_source": "native_pdf",
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
            existing = [_compact_korean(r["korean_text"]) for r in rows
                        if r["file"] == filename and r["page"] == page_num]
            extra = _region_rows(filename, page_num, regions, region_results,
                                 [image.size for image in region_images], dpi, existing)
            rows.extend(extra)
            page_rows += len(extra)
            stats["region_rows"] = len(extra)
            timeouts = (stats.get("fallback") or {}).get("timeouts", 0)
            if timeouts:
                warnings_page.append(
                    f"OCR 시간 초과 {timeouts}회 · 해당 줄의 판독하지 못한 글자·숫자는 □로 표시했습니다 "
                    "(서버 CPU 제한 가능성) · 다시 검수하거나 원본 PDF를 확인하세요")
            stats["total_seconds"] = round(time.perf_counter() - started, 3)
            summaries.append({
                "file": filename, "page": page_num,
                "korean_lines": page_rows, "ocr_lines": ocr_lines,
                "ocr_stats": stats, "ocr_warnings": warnings_page,
                "excluded_label_tables": [[round(v, 1) for v in table] for table in label_tables],
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
            fieldnames = list(dict.fromkeys(key for row in rows for key in row))
            writer = csv.DictWriter(csv_content, fieldnames=fieldnames, restval="")
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
