"""PDF text evidence overlay with coordinate-accurate per-line highlights."""
import io
import fitz
from PIL import Image, ImageDraw

COLORS = {
    "한국어": "#2788DA",
    "OCR 확인": "#1B9E77",
    "곡선": "#F39C12",
    "전면 제품명": "#8A49C7",
    "GAMME": "#E64C59",
    "PRODUIT": "#77818E",
}

def collect_boxes(rows, groups, identity_checks, filename, page, group_view=True):
    """Use original line rectangles, not a guessed paragraph bounding box."""
    output = []
    page_rows = {(i): row for i, row in enumerate(rows)
                 if row["file"] == filename and int(row["page"]) == page}
    if group_view:
        for group in groups:
            if group["file"] != filename or int(group["page"]) != page:
                continue
            indices = [i for i in group["line_indices"] if i in page_rows]
            if not indices:
                continue
            color = "곡선" if group["type"] == "곡선 제품명" else (
                "OCR 확인" if any(
                    "후보" in page_rows[i]["status"] or
                    "확인" in page_rows[i]["status"] and not page_rows[i].get("curved")
                    for i in indices
                ) else "한국어"
            )
            output.append({
                "label": group["paragraph"], "kind": color,
                "source": "추출 문단", "status": group["status"],
                "rects": [rect_from_row(page_rows[i]) for i in indices],
            })
    else:
        for row in page_rows.values():
            color = "곡선" if row.get("curved") else (
                "OCR 확인" if "후보" in row["status"] or "부분 복원" in row["status"]
                else "한국어"
            )
            output.append({
                "label": row["korean_text"], "kind": color,
                "source": "원본 줄", "status": row["status"],
                "rects": [rect_from_row(row)],
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
