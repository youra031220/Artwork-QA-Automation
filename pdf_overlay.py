"""PDF text evidence overlay with coordinate-accurate per-line highlights."""
import io
import re
import fitz
from PIL import Image, ImageDraw

COLORS = {
    "한국어": "#2788DA",
    "OCR 확인": "#1B9E77",
    "수치 확인": "#D94A4A",
    "곡선": "#F39C12",
    "전면 제품명": "#8A49C7",
    "GAMME": "#E64C59",
    "PRODUIT": "#77818E",
}

def _citation_rects(row, evidence):
    """Per-line observed English citation rectangles; never fabricate positions."""
    if not row.get("source_citation"):
        return []
    result = []
    for item_id in row.get("raw_evidence_ids", []):
        entry = evidence.get(item_id)
        if not entry:
            continue
        source = entry.get("text", "")
        chars = [c for span in entry.get("spans", []) for c in span.get("chars", [])]
        for match in re.finditer(
            r"Euromonitor\s+International(?:\s+Limited)?"
            r"|Limited\s*,?\s*Home\s+and\s+Garden\s+\d{4}"
            r"|Home\s+and\s+Garden\s+\d{4}", source, re.I
        ):
            boxes = [c["bbox"] for c in chars[match.start():match.end()] if "bbox" in c]
            if boxes:
                result.append([min(b[0] for b in boxes), min(b[1] for b in boxes),
                               max(b[2] for b in boxes), max(b[3] for b in boxes)])
    return result


def _kind(status, curved=False, product_curve=False):
    if "수치" in status:
        return "수치 확인"
    if "확인" in status or "OCR" in status or "복원" in status:
        return "OCR 확인"
    return "곡선" if product_curve else "한국어"

def collect_boxes(rows, groups, identity_checks, filename, page, group_view=True, raw_summaries=None):
    """Use original line rectangles, not a guessed paragraph bounding box."""
    output = []
    page_rows = {(i): row for i, row in enumerate(rows)
                 if row["file"] == filename and int(row["page"]) == page}
    evidence = {item["id"]: item
                for summary in (raw_summaries or [])
                if summary.get("file") == filename and int(summary.get("page", -1)) == page
                for item in summary.get("raw_evidence", [])}
    if group_view:
        for group in groups:
            if group["file"] != filename or int(group["page"]) != page:
                continue
            indices = [i for i in group["line_indices"] if i in page_rows]
            if not indices:
                continue
            color = _kind(group["status"], product_curve=group["type"] == "곡선 제품명")
            output.append({
                "label": group["paragraph"], "kind": color,
                "source": "추출 문단", "status": group["status"],
                "rects": [rect for i in indices for rect in (
                    [rect_from_row(page_rows[i])] + _citation_rects(page_rows[i], evidence)
                )],
            })
    else:
        for row in page_rows.values():
            color = _kind(row["status"], product_curve=row.get("curved", False))
            output.append({
                "label": row["korean_text"], "kind": color,
                "source": "원본 줄", "status": row["status"],
                "rects": [rect_from_row(row)] + _citation_rects(row, evidence),
            })
    for item in identity_checks:
        if item["file"] != filename or int(item["page"]) != page or item.get("x0") is None:
            continue
        field = item["check"]
        kind = ("전면 제품명" if "패키지 전면" in field else
                "GAMME" if "GAMME" in field else "PRODUIT")
        output.append({
            "label": item["extracted"], "kind": kind,
            "source": field, "status": item["status"],
            "rects": [rect_from_row(item)],
        })
    return output


def rect_from_row(row):
    return [float(row[k]) for k in ("x0", "y0", "x1", "y1")]


def render_overlay(pdf_bytes, page_number, items, selected=None, show_all=True):
    """Render and draw in PDF pixels using PyMuPDF's page rotation matrix.

    Text rectangles come from rawdict/dict (unrotated page space). The page's
    rotation_matrix maps them to displayed coordinates. Pixmap's integer origin
    is subtracted, and image pixels map 1:1 to the rasterized PDF pixels.
    """
    with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
        page = doc[page_number - 1]
        dimensions = page.rect
        scale = min(2.0, 1600 / max(1, dimensions.width),
                    2200 / max(1, dimensions.height))
        pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
        original = Image.open(io.BytesIO(pix.tobytes("png"))).convert("RGBA")
        overlay = Image.new("RGBA", original.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)
        rotate = page.rotation_matrix
        for i, item in enumerate(items):
            if not show_all and i != selected:
                continue
            active = i == selected
            color = COLORS[item["kind"]]
            for coords in item["rects"]:
                rect = fitz.Rect(*coords)
                if rect.is_empty or rect.is_infinite:
                    continue
                rotated = rect * rotate
                x0 = round(rotated.x0 * scale - pix.x)
                y0 = round(rotated.y0 * scale - pix.y)
                x1 = round(rotated.x1 * scale - pix.x)
                y1 = round(rotated.y1 * scale - pix.y)
                x0, x1 = sorted((max(0, min(original.width - 1, x0)),
                                 max(0, min(original.width - 1, x1))))
                y0, y1 = sorted((max(0, min(original.height - 1, y0)),
                                 max(0, min(original.height - 1, y1))))
                if x1 <= x0 or y1 <= y0:
                    continue
                stroke = 5 if active else 2
                draw.rectangle((x0, y0, x1, y1), outline=color, width=stroke)
                if active:
                    draw.rectangle((x0, y0, x1, y1),
                                   fill=(255, 215, 0, 42),
                                   outline="#FFB500", width=6)
        return Image.alpha_composite(original, overlay).convert("RGB")
