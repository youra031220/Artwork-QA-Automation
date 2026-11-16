"""Find printed text that has NO PDF text layer (outlined vectors, images).

Packaging artwork often converts small legal tables or badges to outlines
or embeds them as raster images. PyMuPDF cannot read those characters.
This module selects only compact candidate regions:

* vector glyph clusters: many small filled paths aligned like text lines;
* small placed images (badge sized), never large product photographs.

Regions that overlap the native text layer are skipped, so text that PyMuPDF
already extracted is never OCR'd a second time. Reading orientation comes
from the dominant direction of native text lines around the region (artwork
panels are frequently printed upside down on the folded box).
"""
import io
import math

import fitz
import numpy as np
from PIL import Image, ImageOps

from ocr_batch import normalize_crop

MAX_IMAGE_SIDE = 160      # pt; larger placed images are photographs
MIN_IMAGE_SIDE = 12
MAX_GLYPH_HEIGHT = 18     # pt
MAX_GLYPH_WIDTH = 40
MIN_GLYPHS_PER_LINE = 6


def _cluster(rects, gap_x, gap_y):
    """Union-find of rectangles whose expanded boxes intersect."""
    parent = list(range(len(rects)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    order = sorted(range(len(rects)), key=lambda i: rects[i].x0)
    for position, i in enumerate(order):
        a = rects[i]
        right = a.x1 + gap_x
        for j in order[position + 1:]:
            b = rects[j]
            if b.x0 > right:
                break
            if b.y0 <= a.y1 + gap_y and b.y1 >= a.y0 - gap_y:
                parent[find(i)] = find(j)
    groups = {}
    for i in range(len(rects)):
        groups.setdefault(find(i), []).append(rects[i])
    output = []
    for members in groups.values():
        union = fitz.Rect(members[0])
        for rect in members[1:]:
            union |= rect
        output.append((union, len(members)))
    return output


def _text_layer_boxes(rawdict):
    boxes = []
    for block in rawdict.get("blocks", []):
        for line in block.get("lines", []):
            text = "".join(c["c"] for s in line.get("spans", []) for c in s.get("chars", []))
            if text.strip():
                boxes.append((fitz.Rect(line["bbox"]), line.get("dir", (1, 0)), len(text.strip())))
    return boxes


def _orientation(rect, text_boxes, radius=220):
    """Rotation (degrees, PIL counter-clockwise) for upright reading."""
    centre = (rect.tl + rect.br) / 2
    votes = {0: 0, 180: 0, 90: 0, -90: 0}
    for box, (dx, dy), weight in text_boxes:
        middle = (box.tl + box.br) / 2
        if abs(middle - centre) > radius:
            continue
        if dx < -.8:
            votes[180] += weight
        elif dy < -.8:
            votes[-90] += weight
        elif dy > .8:
            votes[90] += weight
        else:
            votes[0] += weight
    best = max(votes, key=votes.get)
    return best if votes[best] else 0


def _overlaps_text(rect, text_boxes):
    """True when the region is mostly native text (already extracted).

    A small native label inside a vector table (e.g. a reference number)
    must NOT disqualify the whole table, so coverage is measured against
    the region's own area.
    """
    area = rect.get_area()
    if area <= 0:
        return True
    covered = 0.0
    for box, _, _ in text_boxes:
        intersection = rect & box
        if not intersection.is_empty:
            covered += intersection.get_area()
    return covered > .5 * area


def _glyph_paths(drawings):
    glyphs = []
    for drawing in drawings:
        if "f" not in str(drawing.get("type", "")):
            continue
        rect = fitz.Rect(drawing["rect"])
        if not (.8 <= rect.height <= MAX_GLYPH_HEIGHT and rect.width <= MAX_GLYPH_WIDTH):
            continue
        if len(drawing.get("items", [])) < 2:
            continue
        glyphs.append(rect)
    return glyphs


def find_label_tables(page, rawdict, drawings=None):
    """Statutory label tables (한글표시사항: 제품명/제조자/원산지/수입원/주소/
    품질보증기간/주의사항 ...) are OUT OF SCOPE for phrase QA.

    They are recognised by STRUCTURE, not by fixed coordinates: a ruled grid
    of short stroked cell borders (>= 8 distinct row rules and >= 2 column
    rules, each segment shorter than a dieline) enclosing dense lettering
    (>= 60 outline glyphs or >= 20 native text characters). Pictogram boxes
    and packaging panels have few rules; glyphs are filled, not stroked.
    """
    drawings = page.get_cdrawings() if drawings is None else drawings
    horizontal, vertical = [], []
    for drawing in drawings:
        # Cell borders are simple stroked single segments. Glyph outlines
        # are FILLED paths and dielines are much longer, so neither counts.
        items = drawing.get("items", [])
        if drawing.get("type") != "s" or len(items) != 1 or items[0][0] != "l":
            continue
        segment = fitz.Rect(fitz.Point(items[0][1]), fitz.Point(items[0][2])).normalize()
        if segment.height < .6 and 10 <= segment.width <= 300:
            horizontal.append(segment)
        elif segment.width < .6 and 5 <= segment.height <= 300:
            vertical.append(segment)
    glyphs = _glyph_paths(drawings)
    native = []
    for block in rawdict.get("blocks", []):
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                for char in span.get("chars", []):
                    if char["c"].strip():
                        native.append(fitz.Rect(char["bbox"]))
    grids = [rect for rect, _ in _cluster([s + (-.5, -.5, .5, .5) for s in horizontal + vertical], 3, 3)]
    # Columns of one table can be separate rule clusters: join close ones.
    grids = [rect for rect, _ in _cluster(grids, 12, 12)]
    tables = []
    for rect in grids:
        if not (40 <= rect.width <= 500 and 30 <= rect.height <= 400):
            continue
        area = rect + (-2, -2, 2, 2)
        rows = {round(s.y0) for s in horizontal if s in area}
        cols = {round(s.x0) for s in vertical if s in area}
        # A label table has many row rules (one per field); pictogram
        # boxes and packaging panels have only a few.
        if len(rows) < 8 or len(cols) < 2:
            continue
        lettering = sum(1 for g in glyphs if g in area)
        native_chars = sum(1 for c in native if c in area)
        if lettering >= 60 or native_chars >= 20:
            tables.append(area)
    return tables


def find_untexted_regions(page, rawdict, exclude=None):
    """Return candidate regions: dicts with rect, kind and rotation.

    Regions inside an excluded area (statutory label tables) are dropped
    before any rendering or OCR.
    """
    exclude = list(exclude or [])

    def excluded(rect):
        return any((rect & area).get_area() > .5 * rect.get_area() for area in exclude)

    text_boxes = _text_layer_boxes(rawdict)
    glyphs = []
    for drawing in page.get_cdrawings():
        if "f" not in str(drawing.get("type", "")):
            continue
        rect = fitz.Rect(drawing["rect"])
        if not (.8 <= rect.height <= MAX_GLYPH_HEIGHT and rect.width <= MAX_GLYPH_WIDTH):
            continue
        if len(drawing.get("items", [])) < 2:
            continue
        glyphs.append(rect)
    regions = []
    lines = [rect for rect, count in _cluster(glyphs, 6, 3) if count >= MIN_GLYPHS_PER_LINE]
    blocks = [rect for rect, _ in _cluster(lines, 14, 10)]
    # Padded blocks that touch belong to one printed panel (e.g. a table):
    # merge them so no text is read twice from overlapping crops.
    blocks = [rect for rect, _ in _cluster([b + (-3, -3, 3, 3) for b in blocks], 0, 0)]
    for rect in blocks:
        rect = rect & page.rect
        if rect.is_empty or _overlaps_text(rect, text_boxes) or excluded(rect):
            continue
        glyph_count = sum(1 for glyph in glyphs if glyph in rect)
        regions.append({"rect": rect, "kind": "vector", "glyphs": glyph_count,
                        "rotation": _orientation(rect, text_boxes)})
    images = []
    for info in page.get_image_info():
        rect = fitz.Rect(info["bbox"]) & page.rect
        if rect.is_empty:
            continue
        if MIN_IMAGE_SIDE <= rect.width <= MAX_IMAGE_SIDE and MIN_IMAGE_SIDE <= rect.height <= MAX_IMAGE_SIDE:
            images.append(rect)
    for rect, _ in _cluster(images, 1, 1):
        if rect.width > MAX_IMAGE_SIDE or rect.height > MAX_IMAGE_SIDE:
            continue
        if _overlaps_text(rect, text_boxes) or excluded(rect):
            continue
        if any((rect & region["rect"]).get_area() > .5 * rect.get_area() for region in regions):
            continue
        regions.append({"rect": rect, "kind": "image",
                        "rotation": _orientation(rect, text_boxes)})
    return regions


def _light_text_mask(image):
    """Isolate light lettering on a coloured badge; drop border-touching
    shapes (rings, background) so only enclosed characters remain."""
    import cv2
    pixels = np.asarray(image.convert("RGB")).astype(int)
    light = (pixels.min(axis=2) > 190).astype("uint8")
    count, labels, stats, _ = cv2.connectedComponentsWithStats(light, 8)
    height, width = light.shape
    keep = np.zeros_like(light)
    for index in range(1, count):
        x, y, w, h, _ = stats[index]
        if x == 0 or y == 0 or x + w >= width or y + h >= height:
            continue
        if h > height * .6 or w > width * .8:
            continue
        keep[labels == index] = 1
    if keep.sum() < 30:
        return None
    return Image.fromarray(np.where(keep == 1, 0, 255).astype("uint8"))


def page_pixmap(page, rect, dpi):
    """Render a clip from ONE cached display list per page.

    page.get_pixmap() rebuilds the display list of the whole (very large)
    artwork page on every call; reusing it removes that repeated cost.
    """
    display = getattr(page, "_qa_display_list", None)
    if display is None:
        display = page.get_displaylist()
        try:
            page._qa_display_list = display
        except AttributeError:
            pass
    return display.get_pixmap(matrix=fitz.Matrix(dpi / 72, dpi / 72), clip=rect, alpha=False)


def render_region(page, region, dpi):
    pixmap = page_pixmap(page, region["rect"], dpi)
    image = Image.open(io.BytesIO(pixmap.tobytes("png")))
    if region["rotation"]:
        image = image.rotate(region["rotation"], expand=True)
    if region["kind"] == "image":
        mask = _light_text_mask(image)
        if mask is not None:
            return ImageOps.expand(mask, border=10, fill=255)
    return ImageOps.expand(normalize_crop(image), border=10, fill=255)


def crop_box_to_pdf(region, box, image_size, dpi):
    """Map an OCR line bbox (px in the rotated crop) back to PDF points."""
    scale = 72 / dpi
    x0, y0, x1, y1 = [v - 10 for v in box]   # remove the 10px border
    width, height = image_size[0] - 20, image_size[1] - 20
    rotation = region["rotation"] % 360
    if rotation == 180:
        x0, x1 = width - x1, width - x0
        y0, y1 = height - y1, height - y0
    elif rotation == 90:      # image rotated CCW: undo
        x0, y0, x1, y1 = height - y1, x0, height - y0, x1
    elif rotation == 270:
        x0, y0, x1, y1 = y0, width - x1, y1, width - x0
    rect = region["rect"]
    return [round(rect.x0 + x0 * scale, 1), round(rect.y0 + y0 * scale, 1),
            round(rect.x0 + x1 * scale, 1), round(rect.y0 + y1 * scale, 1)]


def direction_for(rotation):
    angle = {0: (1.0, 0.0), 180: (-1.0, 0.0), 90: (0.0, 1.0), -90: (0.0, -1.0)}
    return angle.get(rotation, (1.0, 0.0))


def split_text_bands(image, min_height=10, gap=4):
    """Horizontal text bands of a light-background crop (top to bottom).

    A badge such as 'IH / 인덕션' is read far more reliably one line at a
    time; each band becomes one crop in the shared OCR batch.
    """
    pixels = np.asarray(image.convert("L")) < 128
    rows = np.where(pixels.sum(axis=1) > 0)[0]
    if rows.size == 0:
        return []
    bands, start, previous = [], rows[0], rows[0]
    for row in rows[1:]:
        if row > previous + gap:
            bands.append((start, previous))
            start = row
        previous = row
    bands.append((start, previous))
    output = []
    for top, bottom in bands:
        if bottom - top + 1 < min_height:
            continue
        top, bottom = max(0, top - 8), min(image.height, bottom + 9)
        output.append(((top, bottom), ImageOps.expand(
            image.crop((0, top, image.width, bottom)), border=0)))
    return output
