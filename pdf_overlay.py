"""PDF text evidence overlay with coordinate-accurate per-line highlights."""
import io
import re
import fitz
from PIL import Image, ImageDraw
from extractor import numeric_tokens

COLORS = {
    "한국어": "#2788DA",
    "영문": "#1B9E77",
    "수치 포함": "#487C9C",
    "곡선": "#F39C12",
    "제품명": "#8A49C7",
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
        # Multilingual legal lines contain unrelated source attributions.
        # Identify the source nearest this Korean reference, even when the
        # name follows Korean words on the *preceding* line.
        korean = re.search(r"[가-힣]", source)
        prefix = source[:korean.start()] if korean else source
        full = list(re.finditer(
            r"Euromonitor\s+International\s+Limited\s*,?\s*"
            r"Home\s+and\s+Garden\s+\d{4}", prefix, re.I
        ))
        trailing = list(re.finditer(
            r"Euromonitor\s+International(?:\s+Limited)?", source, re.I
        ))
        beginning = list(re.finditer(
            r"Limited\s*,?\s*Home\s+and\s+Garden\s+\d{4}", prefix, re.I
        ))
        if full:
            match = full[-1]
        elif trailing and len(source) - trailing[-1].end() < 12:
            match = trailing[-1]
        elif beginning:
            match = beginning[0]
        else:
            continue
        boxes = [c["bbox"] for c in chars[match.start():match.end()] if "bbox" in c]
        if boxes:
            result.append([min(b[0] for b in boxes), min(b[1] for b in boxes),
                           max(b[2] for b in boxes), max(b[3] for b in boxes)])
    return result


def _kind(status, curved=False, product_curve=False):
    return "곡선" if (curved or product_curve) else "한국어"


def _maximum_context(row, evidence):
    """Nearby native numeric and Korean objects for visual inspection only.

    No inferred numeric value is inserted into the extracted source sentence.
    """
    if row.get("korean_text", "").strip() != "최대":
        return []
    anchor = fitz.Rect(*rect_from_row(row))
    selected = {"number": None, "phrase": None}
    for item in evidence.values():
        value = item.get("text", "").strip()
        if re.fullmatch(r"\d{1,4}(?:[.,]\d+)?\s*(?:%|배|년|위)", value):
            kind = "number"
        elif (re.fullmatch(r"[가-힣]+(?:\s+[가-힣]+){1,7}", value)
              and 4 <= len(value) <= 36):
            kind = "phrase"
        else:
            continue
        rect = fitz.Rect(item.get("bbox", []))
        if rect.is_empty or rect.is_infinite:
            continue
        horizontal = max(0, rect.x0-anchor.x1, anchor.x0-rect.x1)
        vertical = max(0, rect.y0-anchor.y1, anchor.y0-rect.y1)
        if horizontal > 100 or vertical > 90:
            continue
        distance = horizontal + vertical + .1*abs(rect.y0-anchor.y0)
        previous = selected[kind]
        if previous is None or distance < previous[0]:
            selected[kind] = (distance, value, list(rect))
    return [
        {"kind": kind, "text": selected[kind][1],
         "rect": selected[kind][2]}
        for kind in ("number", "phrase") if selected[kind] is not None
    ]


def numeric_display_label(text, status, numeric_review=False, numeric_peers=None):
    """One simple numeric type; uncertainty remains in the separate QA result."""
    if numeric_review or "수치" in status or "숫자" in status:
        return "수치 포함"
    if re.search(r"\ufffd{1,6}\s*(?:%|/|배|년|위)", text):
        return "수치 포함"
    if numeric_tokens(text) or numeric_peers:
        return "수치 포함"
    return ""


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
            numeric_label = numeric_display_label(
                group["paragraph"], group["status"],
                group.get("numeric_review", False),
                group.get("numeric_peer_evidence", []),
            )
            color = ("수치 포함" if numeric_label else _kind(group["status"],
                                product_curve=group["type"] == "곡선 제품명"))
            claim_context = [
                hit for i in indices
                for hit in _maximum_context(page_rows[i], evidence)
            ]
            context_labels = [hit["text"] for hit in claim_context]
            display_text = (
                "최대 · 주변 PDF: " + " / ".join(context_labels)
                + " (연결 확인)"
                if group.get("type") == "문장 연결 확인" and context_labels
                else group["paragraph"]
            )
            output.append({
                "label": display_text, "kind": color,
                "source": "추출 문단", "status": group["status"],
                "original_label": group["paragraph"],
                "context_candidates": context_labels,
                "display_label": numeric_label or color,
                "rects": ([rect for i in indices for rect in (
                    [rect_from_row(page_rows[i])] + _citation_rects(page_rows[i], evidence)
                )] + [hit["rect"] for hit in claim_context]
                + [pos["bbox"] for pos in group.get("source_coordinates", [])
                   if pos.get("line_index") is None and pos.get("bbox")]),
            })
    else:
        for row_index, row in page_rows.items():
            numeric_label = numeric_display_label(
                row["korean_text"], row["status"],
                row.get("numeric_review", False),
                row.get("numeric_peer_evidence", []),
            )
            color = ("수치 포함" if numeric_label else _kind(row["status"], product_curve=row.get("curved", False)))
            claim_context = _maximum_context(row, evidence)
            display_text = (
                "최대 · 주변 PDF: " + " / ".join(hit["text"] for hit in claim_context)
                + " (연결 확인)" if claim_context else row["korean_text"]
            )
            output.append({
                "label": display_text, "kind": color,
                "source": "원본 줄", "status": row["status"],
                "original_label": row["korean_text"],
                "context_candidates": [hit["text"] for hit in claim_context],
                "display_label": numeric_label or color,
                "line_index": row_index,
                "rects": ([rect_from_row(row)] + _citation_rects(row, evidence)
                          + [hit["rect"] for hit in claim_context]),
            })
    for item in identity_checks:
        if item["file"] != filename or int(item["page"]) != page or item.get("x0") is None:
            continue
        field = item["check"]
        kind = "제품명"
        output.append({
            "label": item["extracted"], "kind": kind,
            "source": field, "status": item["status"],
            "rects": [rect_from_row(item)],
        })
    # Include readable English originals alongside Korean evidence.
    # Exclude single tokens, job-ticket metadata, URLs and foreign scripts.
    for item in evidence.values():
        value = item.get("text", "").strip()
        bbox = item.get("bbox")
        if not bbox or len(bbox) != 4 or re.search(r"[가-힣\ufffd]", value):
            continue
        if not re.search(r"[A-Za-z]{3,}\s+[A-Za-z]{3,}", value):
            continue
        if re.search(r"[\u0e00-\u0e7f\u0400-\u052f\u0600-\u06ff]", value):
            continue
        if re.match(r"^(?:CLIENT|GAMME|DOSSIER|PRODUIT|ECHELLE|BARCODE|REF\s*:)", value, re.I):
            continue
        output.append({
            "label": value, "kind": "영문", "display_label": "영문",
            "source": "영문 원본", "status": "PDF 영문 추출",
            "rects": [bbox],
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


def render_selected_crop(pdf_bytes, page_number, item, margin=24, numeric_context=220):
    """Render just the selected native PDF rectangles at readable resolution.

    Handles split paragraphs by taking the union of their distinct glyph
    rectangles; does not alter or infer the source coordinates. Return None
    for a selection without valid boxes.
    """
    with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
        page = doc[page_number - 1]
        rotated = []
        for values in item.get("rects", []):
            try:
                rect = fitz.Rect(*[float(value) for value in values])
            except (ValueError, TypeError, IndexError):
                continue
            if rect.is_empty or rect.is_infinite:
                continue
            visible = (rect * page.rotation_matrix) & page.rect
            if not visible.is_empty:
                rotated.append(visible)
        if not rotated:
            return None
        bounds = fitz.Rect(rotated[0])
        for rect in rotated[1:]:
            bounds |= rect
        margin_x = max(float(margin), min(50, bounds.width * .18))
        margin_y = max(14.0, min(35.0, bounds.height * .50))
        # A dangling numeric qualifier like '최대' usually has a digit or
        # unit in an adjacent PDF object *outside* this tiny selection box.
        # Expand the visual context without changing the QA text or evidence.
        label = item.get("label", "").strip()
        status = item.get("status", "")
        needs_context = (
            label == "최대"
            or label.startswith("최대 [")
            or ("문장 연결" in status)
            or (("수치" in status or item.get("display_label", "").startswith("수치"))
                and bounds.width < 95)
        )
        if needs_context and not item.get("context_candidates"):
            # No independently linked PDF glyphs: show generous neighboring
            # context so an unindexed number remains visible.
            context = max(100.0, min(float(numeric_context), 420.0))
            margin_x = max(margin_x, context)
            margin_y = max(margin_y, min(120.0, context * .42))
        elif item.get("context_candidates"):
            # All neighboring glyph boxes are already part of bounds; keep
            # the crop tight so the percentage is actually large and readable.
            margin_x = max(24.0, min(45.0, bounds.width * .22))
            margin_y = max(16.0, min(35.0, bounds.height * .40))
        crop = fitz.Rect(bounds.x0 - margin_x, bounds.y0 - margin_y,
                         bounds.x1 + margin_x, bounds.y1 + margin_y) & page.rect
        if crop.is_empty:
            return None
        # Crop directly from the vector PDF, not from a downscaled page image.
        zoom = min(4.0, 1800.0 / max(1, crop.width),
                   1100.0 / max(1, crop.height))
        zoom = max(.5, zoom)
        pix = page.get_pixmap(clip=crop, matrix=fitz.Matrix(zoom, zoom), alpha=False)
        image = Image.open(io.BytesIO(pix.tobytes("png"))).convert("RGB")
        draw = ImageDraw.Draw(image)
        for rect in rotated:
            x0 = round(rect.x0 * zoom - pix.x)
            y0 = round(rect.y0 * zoom - pix.y)
            x1 = round(rect.x1 * zoom - pix.x)
            y1 = round(rect.y1 * zoom - pix.y)
            x0, x1 = sorted((max(0, min(image.width - 1, x0)),
                             max(0, min(image.width - 1, x1))))
            y0, y1 = sorted((max(0, min(image.height - 1, y0)),
                             max(0, min(image.height - 1, y1))))
            if x1 > x0 and y1 > y0:
                draw.rectangle((x0, y0, x1, y1), outline="#E6A100", width=4)
        return image
