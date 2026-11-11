"""Conservative Korean layout reconstruction for artwork PDFs.

Regular paragraphs: join consecutive lines from the same PDF text block.
Curved labels: group adjacent rotated fragments using angle and position.
Source lines and coordinates are ALWAYS retained separately.
"""
import math
import re

HANGUL = re.compile(r"[가-힣]+")
PARAGRAPH_START = re.compile(
    r"^(?:취급\s*주의\s*사항\s*[:：]|적절한\s*분리배출|"
    r"QR\s*코드를|테팔은\s*모든\s*제조|사용\s*시\s*주의)"
)


def _same_page(left, right):
    return left["file"] == right["file"] and left["page"] == right["page"]


def _should_join_lines(previous, current):
    """Join same-block physical lines; never guess reading order across blocks."""
    if not _same_page(previous, current):
        return False
    if previous.get("block_id") != current.get("block_id"):
        return False
    if previous.get("line_id", -10) + 1 != current.get("line_id", -1):
        return False
    if previous.get("curved") or current.get("curved"):
        return False
    if PARAGRAPH_START.search(current["korean_text"]):
        return False
    if abs(previous.get("dir_x", 1) - current.get("dir_x", 1)) > .1:
        return False
    if abs(previous.get("dir_y", 0) - current.get("dir_y", 0)) > .1:
        return False
    a = float(previous.get("font_size", 0))
    b = float(current.get("font_size", 0))
    if a and b and abs(a - b) / max(a, b) > .18:
        return False
    if _maximum_continuation(previous, current):
        return True
    # A numeric claim can wrap at the right edge of the same text block.
    # Allow only a preceding "최대" and a following damaged/visible percentage;
    # do not generally join distant columns.
    wraps_numeric_claim = bool(
        re.search(r"최대\s*$", previous["korean_text"])
        and re.match(r"^(?:\ufffd{1,6}|\d{1,3})\s*%\s*", current["korean_text"])
    )
    if (not wraps_numeric_claim and
            abs(float(previous["x0"]) - float(current["x0"])) > max(12, max(a, b, 1) * 2.5)):
        return False
    baseline_a = float(previous.get("baseline_y", previous["y0"]))
    baseline_b = float(current.get("baseline_y", current["y0"]))
    distance = baseline_b - baseline_a
    return 0 < distance <= max(12, max(a, b, 1) * 2.0)


def _maximum_continuation(previous, current):
    """Connect dangling maximum only to a spatially adjacent continuation."""
    if not _same_page(previous, current) or previous.get("curved") or current.get("curved"):
        return False
    if previous["korean_text"].strip() != "최대":
        return False
    phrase = current["korean_text"].strip()
    if not re.match(r"^(?:(?:\ufffd{1,5}|\d{1,3})\s*%|수납\b|공간\s*절약\b)", phrase):
        return False
    if PARAGRAPH_START.match(phrase):
        return False
    if abs(float(previous.get("dir_x", 1))-float(current.get("dir_x", 1))) > .1:
        return False
    if abs(float(previous.get("dir_y", 0))-float(current.get("dir_y", 0))) > .1:
        return False
    size_a = float(previous.get("font_size", 0))
    size_b = float(current.get("font_size", 0))
    if not min(size_a, size_b) or max(size_a, size_b)/min(size_a, size_b) > 1.35:
        return False
    x0, y0, x1, y1 = [float(previous[k]) for k in ("x0","y0","x1","y1")]
    u0, v0, u1, v1 = [float(current[k]) for k in ("x0","y0","x1","y1")]
    dx = max(0, u0-x1, x0-u1)
    dy = max(0, v0-y1, y0-v1)
    font = max(size_a, size_b)
    same_line = abs((y0+y1)/2 - (v0+v1)/2) <= font*.6
    next_line = 0 <= v0-y0 <= font*2.1
    return bool((same_line and dx <= font*4) or
                (next_line and dy <= font*1.2 and dx <= font*2.5))


def _should_join_across_blocks(previous, current):
    """Join a few verified *continuations* even when PDF block IDs differ.

    Use textual continuity only to decide GROUPING, never to insert or change
    letters. Require adjacency in extraction order and matching orientation.
    These patterns avoid merging unrelated columns or independent claims.
    """
    if not _same_page(previous, current):
        return False
    if previous.get("curved") or current.get("curved"):
        return False
    if abs(float(previous.get("dir_x", 1)) - float(current.get("dir_x", 1))) > .1:
        return False
    if abs(float(previous.get("dir_y", 0)) - float(current.get("dir_y", 0))) > .1:
        return False
    a = previous["korean_text"].strip()
    b = current["korean_text"].strip()
    if not a or not b:
        return False
    if PARAGRAPH_START.match(b):
        return False
    if _maximum_continuation(previous, current):
        return True

    # Packaging artwork can split one legal paragraph into separate text
    # objects. Keep the exact text from both objects.
    if (
        a.startswith("테팔은 모든 제조 과정")
        and a.endswith(("결함에 대하여", "구입일로부터"))
        and b.startswith(("구입일로부터", "2년간", "�년간"))
    ):
        return True
    if a == "AI가" and b.startswith("생성한 이미지"):
        return True

    # Main performance claim is often typeset over three distinct blocks.
    if re.search(r"테팔 기본 코팅 대비(?: 최대)?$", a) and re.match(r"(?:최대\s*)?\d+\s*배\b", b):
        return True
    if re.search(r"(?:최대\s*)?\d+\s*배 더 오래가는$", a) and b.startswith("엑스트라 라이프 논스틱 코팅"):
        return True

    # A headline can wrap after '1위' while its supporting footnote
    # remains a separate group.
    if re.search(r"세계판매\s*1위$", a) and b.startswith("주방용품"):
        return True
    return False


def _should_join_curve(previous, current):
    """Connect successive glyph fragments on the same curved baseline.

    Each label fragment is often an independent PDF text block. Avoid requiring
    block_id equality, but require matching page, close centers and similar
    rotation. Do not use product dictionaries to fill missing letters.
    """
    if not (_same_page(previous, current) and previous.get("curved") and current.get("curved")):
        return False
    p_size = float(previous.get("font_size", 0))
    c_size = float(current.get("font_size", 0))
    if min(p_size, c_size) <= 0:
        return False
    if max(p_size, c_size) / min(p_size, c_size) > 1.35:
        return False
    p_angle = math.atan2(float(previous["dir_y"]), float(previous["dir_x"]))
    c_angle = math.atan2(float(current["dir_y"]), float(current["dir_x"]))
    angle_difference = abs(math.atan2(math.sin(c_angle - p_angle), math.cos(c_angle - p_angle)))
    if angle_difference > .25:  # ≈14 degrees between adjacent fragments
        return False
    p_center = ((float(previous["x0"]) + float(previous["x1"])) / 2,
                (float(previous["y0"]) + float(previous["y1"])) / 2)
    c_center = ((float(current["x0"]) + float(current["x1"])) / 2,
                (float(current["y0"]) + float(current["y1"])) / 2)
    gap = math.hypot(c_center[0] - p_center[0], c_center[1] - p_center[1])
    return gap <= max(30, max(p_size, c_size) * 4.0)


def group_paragraphs(rows, raw_summaries=None):
    """Return paragraph/curved-label groups without modifying the raw rows."""
    groups = []
    current = []
    for index, row in enumerate(rows):
        if not current:
            current = [(index, row)]
            continue
        previous = current[-1][1]
        join = (
            _should_join_curve(previous, row)
            if previous.get("curved") or row.get("curved")
            else (_should_join_lines(previous, row) or _should_join_across_blocks(previous, row))
        )
        if join:
            current.append((index, row))
        else:
            groups.append(current)
            current = [(index, row)]
    if current:
        groups.append(current)

    output = []
    for group in groups:
        is_curved = all(row.get("curved") for _, row in group)
        if is_curved and any(
            len(row["korean_text"].strip()) >= 12
            or (len(row["korean_text"].strip()) >= 6
                and re.search(r"[,().%:：]", row["korean_text"]))
            for _, row in group
        ):
            # Full rotated sentences (heat, usage, legal copy) are not
            # curved product-name glyphs. Preserve spaces and punctuation.
            text = " ".join(row["korean_text"].strip() for _, row in group)
            kind = "세로 일반 문구"
            status = "회전 문구 · 원본 확인"
        elif is_curved:
            # Preserve explicit word separators from the PDF when joining
            # rotated glyphs; discard surrounding foreign "• T" fragments.
            # Do not guess spaces from dictionary words or product names.
            parts = []
            for position, (_, row) in enumerate(group):
                letters = "".join(HANGUL.findall(row["korean_text"]))
                if letters:
                    prefix = " " if position and row.get("curve_leading_space") else ""
                    parts.append(prefix + letters)
            text = "".join(parts)
            kind = "곡선 제품명"
            status = "곡선 결합 · 원본 확인" if len(group) > 1 else "곡선 배치 · 연결 확인"
        else:
            text = " ".join(row["korean_text"].strip() for _, row in group if row["korean_text"].strip())
            kind = "일반 문구"
            status = (
                "OCR 복원 후보 · 검증 필요"
                if any("확인" in row["status"] or "후보" in row["status"] for _, row in group)
                else "원본 추출 정상"
            )
        # A lone "최대" is not a complete numeric QA claim.
        standalone_maximum = (len(group) == 1 and
                              group[0][1]["korean_text"].strip() == "최대")
        if standalone_maximum:
            text = "최대"
            kind = "문장 연결 확인"
            status = "문장 연결 확인 필요 · 숫자 객체 연결 미확정"
        # Keep the most severe original warning; never silently downgrade a
        # numerical ambiguity to a generic OCR flag in paragraph or ZIP views.
        warnings = list(dict.fromkeys(
            warning
            for _, row in group
            for warning in (row.get("warnings") or [])
        ))
        if standalone_maximum:
            warnings.append("'최대'에 연결되는 수치와 후속 문구를 원본 PDF에서 확인하세요")
            status = "문장 연결 확인 필요 · 숫자 객체 연결 미확정"
        elif any(row.get("numeric_review") for _, row in group):
            status = "수치 대조 필요 · 원본 확인"
            if not any("수치" in warning for warning in warnings):
                warnings.insert(0, status)
        elif warnings:
            status = warnings[0]
        evidence_ids = list(dict.fromkeys(
            ident for _, row in group
            for ident in row.get("raw_evidence_ids", [])
        ))
        numeric = sorted(set(
            token for _, row in group
            for token in row.get("native_numeric_tokens", [])
        ))
        candidates = [
            {"text": row["ocr_candidate"], "line_index": index}
            for index, row in group if row.get("ocr_candidate")
        ]
        positions = [
            {"line_index": index, "page": row["page"],
             "bbox": [row["x0"], row["y0"], row["x1"], row["y1"]]}
            for index, row in group
        ]
        output.append({
            "file": group[0][1]["file"],
            "page": group[0][1]["page"],
            "paragraph": text,
            "type": kind,
            "line_count": len(group),
            "line_indices": [index for index, _ in group],
            "status": status,
            "warnings": warnings,
            "numeric_review": any(row.get("numeric_review") for _, row in group),
            "raw_evidence_ids": evidence_ids,
            "numeric_tokens": numeric,
            "ocr_candidates": candidates,
            "numeric_peer_evidence": [e for _, row in group for e in row.get("numeric_peer_evidence", [])],
            "source_coordinates": positions,
        })
    return _rebuild_storage_claim(output, raw_summaries)


def _rebuild_storage_claim(groups, raw_summaries):
    """Assemble only independently observed, tightly colocated PDF glyphs.

    A complete '최대 40% 수납 공간 절약' spans three native text blocks
    on the Mint Calm package. Numeric glyphs come from the original PDF,
    NEVER from an OCR guess, a reference master, or the filename.
    """
    if not raw_summaries:
        return groups
    evidence = {
        (summary.get("file"), int(summary.get("page", -1))): summary.get("raw_evidence", [])
        for summary in raw_summaries
    }
    used = set()
    substitutions = {}
    for i, group in enumerate(groups):
        if group["paragraph"].strip() != "최대" or group.get("type") != "문장 연결 확인":
            continue
        file, page = group["file"], int(group["page"])
        anchor = group["source_coordinates"][0]["bbox"]
        if len(anchor) != 4:
            continue
        ax0,ay0,ax1,ay1 = map(float, anchor)
        # Native glyph evidence: explicit visible digits and percent mark.
        numbers = []
        for item in evidence.get((file,page),[]):
            value = item.get("text","").strip()
            if not re.fullmatch(r"\d{1,3}(?:[.,]\d+)?\s*%",value):
                continue
            box = item.get("bbox", [])
            if len(box) != 4:
                continue
            x0,y0,x1,y1 = map(float,box)
            if (x0 >= ax0-22 and x1 <= ax1+100 and
                y0 >= ay0-85 and y0 <= ay0+18 and
                x1 > ax0 and y1 >= ay0-5):
                numbers.append((item,box))
        if len(numbers) != 1:
            continue
        number, number_box = numbers[0]
        target = []
        for j, other in enumerate(groups):
            if j == i or j in used or other["file"] != file or int(other["page"]) != page:
                continue
            if other["paragraph"].strip() != "수납 공간 절약":
                continue
            pb = other["source_coordinates"][0]["bbox"]
            px0,py0,px1,py1 = map(float,pb)
            if (px0 >= ax0-90 and px1 <= ax1+100
                    and py0 >= ay0-6 and py0 <= ay1+90
                    and abs((px0+px1)/2-(float(number_box[0])+float(number_box[2]))/2) <= 115):
                target.append((j,other))
        if len(target) != 1:
            continue
        j,phrase = target[0]
        # Preserve original PDF location and evidence IDs for all three parts.
        # The new reading order reflects the printed claim, not PDF object order.
        new = dict(group)
        new["paragraph"] = "최대 " + number["text"].strip() + " 수납 공간 절약"
        new["type"] = "공간 배치 문구 연결"
        new["status"] = "PDF 원본 3개 객체 연결 · 확인 권장"
        new["numeric_review"] = False
        new["warnings"] = [
            "최대·숫자·수납 문구를 원본 PDF 좌표로 연결함 (내용 변경 없음)"
        ]
        new["line_indices"] = group["line_indices"] + phrase["line_indices"]
        new["line_count"] = group["line_count"] + phrase["line_count"]
        new["source_coordinates"] = (
            group["source_coordinates"] +
            [{"line_index": None, "page": page, "bbox": list(number_box)}] +
            phrase["source_coordinates"]
        )
        new["raw_evidence_ids"] = list(dict.fromkeys(
            group["raw_evidence_ids"] + [number["id"]] + phrase["raw_evidence_ids"]
        ))
        new["numeric_tokens"] = sorted(set(
            group["numeric_tokens"] + [number["text"].strip()] + phrase["numeric_tokens"]
        ))
        new["numeric_peer_evidence"] = [number]
        substitutions[i] = new
        used.add(j)
    return [substitutions.get(i, group) for i,group in enumerate(groups) if i not in used]
