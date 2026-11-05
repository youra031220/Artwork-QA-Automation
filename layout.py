"""Conservative paragraph reconstruction from Korean artwork lines.

Do NOT invent missing words. A paragraph is a display-only grouping of
adjacent PDF text lines from the same original text block.
"""
import re

PARAGRAPH_START = re.compile(
    r"^(?:취급\s*주의\s*사항\s*[:：]|적절한\s*분리배출|"
    r"QR\s*코드를|테팔은\s*모든\s*제조|사용\s*시\s*주의)"
)


def _should_join(previous, current):
    if previous["file"] != current["file"] or previous["page"] != current["page"]:
        return False
    if previous.get("block_id") != current.get("block_id"):
        return False
    if previous.get("line_id", -10) + 1 != current.get("line_id", -1):
        return False
    if previous.get("curved") or current.get("curved"):
        return False
    if PARAGRAPH_START.search(current["korean_text"]):
        return False

    # Both lines must have similar orientation and font size.
    if abs(previous.get("dir_x", 1) - current.get("dir_x", 1)) > .1:
        return False
    if abs(previous.get("dir_y", 0) - current.get("dir_y", 0)) > .1:
        return False
    a = float(previous.get("font_size", 0))
    b = float(current.get("font_size", 0))
    if a and b and abs(a - b) / max(a, b) > .18:
        return False

    # Do not merge two separate columns or widely separated lines.
    x0a, x0b = float(previous["x0"]), float(current["x0"])
    height = max(a, b, 1)
    if abs(x0a - x0b) > max(12, height * 2.5):
        return False
    baseline_a = float(previous.get("baseline_y", previous["y0"]))
    baseline_b = float(current.get("baseline_y", current["y0"]))
    dist = baseline_b - baseline_a
    if not (0 < dist <= max(12, height * 2.0)):
        return False
    return True


def group_paragraphs(rows):
    """Return grouped text and line references, preserving all source lines."""
    groups = []
    current = []
    for idx, row in enumerate(rows):
        if not current or _should_join(current[-1][1], row):
            current.append((idx, row))
        else:
            groups.append(current)
            current = [(idx, row)]
    if current:
        groups.append(current)

    output = []
    for group in groups:
        texts = [item["korean_text"].strip() for _, item in group]
        output.append({
            "file": group[0][1]["file"],
            "page": group[0][1]["page"],
            "paragraph": " ".join(t for t in texts if t),
            "line_count": len(group),
            "line_indices": [i for i, _ in group],
            "status": (
                "원본 확인 필요"
                if any("확인" in item["status"] or "후보" in item["status"] for _, item in group)
                else "원본 추출 정상"
            ),
        })
    return output
