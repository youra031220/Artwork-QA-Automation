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
    if abs(float(previous["x0"]) - float(current["x0"])) > max(12, max(a, b, 1) * 2.5):
        return False
    baseline_a = float(previous.get("baseline_y", previous["y0"]))
    baseline_b = float(current.get("baseline_y", current["y0"]))
    distance = baseline_b - baseline_a
    return 0 < distance <= max(12, max(a, b, 1) * 2.0)


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


def group_paragraphs(rows):
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
            else _should_join_lines(previous, row)
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
        if is_curved:
            # Artwork circular product names may include foreign "• T" fragments.
            # Only join printed Hangul glyphs, in source reading order.
            text = "".join("".join(HANGUL.findall(row["korean_text"])) for _, row in group)
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
        output.append({
            "file": group[0][1]["file"],
            "page": group[0][1]["page"],
            "paragraph": text,
            "type": kind,
            "line_count": len(group),
            "line_indices": [index for index, _ in group],
            "status": status,
        })
    return output
