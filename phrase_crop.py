"""Crop the printed source of each QA phrase from the PDF for the review table.

The crop is the union of the phrase's source line boxes (padded), with each
source box outlined in red, so the reviewer sees exactly what was extracted.
Upside-down and vertical lines are turned upright. Returned as small JPEG data URIs.
"""
import base64
import io

import fitz
from PIL import Image, ImageDraw

MAX_WIDTH_PX = 760
SEGMENT_PT = 150   # longest printed span per stacked crop piece


def _turn(flag):
    """Rotation (degrees, counter-clockwise) that makes the printed text upright.

    Accepts the legacy bool (True = upside down) or an angle: 0 normal,
    180 upside down, 90 text running top→bottom, 270 text running bottom→top.
    """
    if flag is True:
        return 180
    if flag in (False, None):
        return 0
    return int(flag) % 360


def crop_data_uris(pdf_bytes, requests):
    """requests: iterable of (page_no, ((x0,y0,x1,y1), ...), turn).

    ``turn`` is the text direction (see ``_turn``). Vertical and upside-down
    lines are turned upright and cut along their reading direction, so a
    vertical line becomes a few short horizontal strips instead of one very
    tall narrow image. Returns one data URI (or "") per request, in order.
    """
    output = []
    with fitz.open(stream=pdf_bytes, filetype="pdf") as document:
        display_lists = {}
        for page_no, boxes, flag in requests:
            try:
                turn = _turn(flag)
                page = document[int(page_no) - 1]
                rects = [fitz.Rect(box) for box in boxes if box and len(box) == 4]
                rects = [rect for rect in rects if not rect.is_empty]
                if not rects:
                    output.append("")
                    continue
                # Line order in reading direction.
                if turn == 180:
                    rects.sort(key=lambda r: -r.y0)
                elif turn == 90:
                    rects.sort(key=lambda r: -r.x0)
                elif turn == 270:
                    rects.sort(key=lambda r: r.x0)
                vertical = turn in (90, 270)
                # One tight crop per source line, stacked in reading order:
                # a union box over a multilingual paragraph would shrink the
                # Korean text to an unreadable size. Long lines are cut into
                # short segments along the reading direction.
                segments = []
                for rect in rects:
                    length = rect.height if vertical else rect.width
                    parts = max(1, int(-(-length // SEGMENT_PT)))
                    step = length / parts
                    order = range(parts) if turn in (0, 90) else reversed(range(parts))
                    for k in order:
                        if vertical:
                            seg = fitz.Rect(rect.x0, rect.y0 + k * step, rect.x1, rect.y0 + (k + 1) * step)
                        else:
                            seg = fitz.Rect(rect.x0 + k * step, rect.y0, rect.x0 + (k + 1) * step, rect.y1)
                        segments.append((rect, seg))
                widest = max((s.height if vertical else s.width) for _, s in segments) + 12
                zoom = max(1.0, min(4.0, MAX_WIDTH_PX / widest))
                display = display_lists.get(page.number)
                if display is None:
                    display = display_lists[page.number] = page.get_displaylist()
                pieces = []
                for rect, segment in segments:
                    pad = (-3, -6, 3, 6) if vertical else (-6, -3, 6, 3)
                    clip = (segment + pad) & page.rect
                    pixmap = display.get_pixmap(matrix=fitz.Matrix(zoom, zoom), clip=clip, alpha=False)
                    piece = Image.frombytes("RGB", (pixmap.width, pixmap.height), pixmap.samples)
                    ImageDraw.Draw(piece).rectangle(
                        [(rect.x0 - clip.x0 - 1) * zoom, (rect.y0 - clip.y0 - 1) * zoom,
                         (rect.x1 - clip.x0 + 1) * zoom, (rect.y1 - clip.y0 + 1) * zoom],
                        outline=(220, 30, 30), width=2)
                    if turn:
                        piece = piece.rotate(turn, expand=True)
                    pieces.append(piece)
                width = max(piece.width for piece in pieces)
                height = sum(piece.height for piece in pieces) + 6 * (len(pieces) - 1)
                image = Image.new("RGB", (width, height), (255, 255, 255))
                y = 0
                for piece in pieces:
                    image.paste(piece, (0, y))
                    y += piece.height + 6
                if image.width > MAX_WIDTH_PX:
                    image = image.resize((MAX_WIDTH_PX, max(1, int(image.height * MAX_WIDTH_PX / image.width))))
                buffer = io.BytesIO()
                image.save(buffer, "JPEG", quality=82)
                output.append("data:image/jpeg;base64," + base64.b64encode(buffer.getvalue()).decode())
            except Exception:
                output.append("")
    return output
