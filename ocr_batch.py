"""Single-process batch OCR for many small PDF crops.

Every crop is rendered once at the caller's DPI (350 by default), stacked
vertically with wide white gaps, and read with ONE Tesseract process.
Words are assigned back to their crop by position, so a crop can never
silently borrow text from a neighbour. A crop that yields nothing is
reported as empty; callers decide whether to re-read it individually.
"""
import re
import statistics
import time

from PIL import Image, ImageOps, ImageStat
import pytesseract

GAP = 60          # white separator between crops (px)
MARGIN = 40       # left/top margin (px)
HANGUL = re.compile(r"[가-힣]")


def normalize_crop(image, invert_dark=True):
    """Grayscale + autocontrast; light text on dark ground is inverted."""
    gray = ImageOps.autocontrast(ImageOps.grayscale(image))
    if invert_dark and ImageStat.Stat(gray).median[0] < 128:
        gray = ImageOps.invert(gray)
    return gray


def _binarize(image):
    """Per-crop Otsu threshold.

    Tesseract thresholds the whole sheet at once; without this, a dark crop
    elsewhere in the stack shifts the global threshold and degrades a
    neighbouring crop. Binarizing each crop first makes the batch read every
    crop as if it were OCR'd on its own.
    """
    import numpy as np
    pixels = np.asarray(image.convert("L"))
    histogram = np.bincount(pixels.ravel(), minlength=256).astype(float)
    total = pixels.size
    cumulative = np.cumsum(histogram)
    cumulative_mean = np.cumsum(histogram * np.arange(256))
    global_mean = cumulative_mean[-1]
    with np.errstate(divide="ignore", invalid="ignore"):
        between = (global_mean * cumulative / total - cumulative_mean) ** 2 / (
            cumulative * (total - cumulative))
    threshold = int(np.nanargmax(between)) if np.isfinite(between).any() else 128
    return Image.fromarray(np.where(pixels > threshold, 255, 0).astype("uint8"))


def _stack(images):
    images = [_binarize(image) for image in images]
    width = max(image.width for image in images) + 2 * MARGIN
    height = sum(image.height + GAP for image in images) + MARGIN
    sheet = Image.new("L", (width, height), 255)
    spans = []
    y = MARGIN
    for image in images:
        sheet.paste(image, (MARGIN, y))
        spans.append((y, y + image.height))
        y += image.height + GAP
    return sheet, spans


def _lines_from_words(words, use_layout=True):
    """Group words into visual lines, then order each line by x.

    With a layout page mode (psm 3/4/6) Tesseract's own block/line ids are
    used, so table bars or tall separators cannot glue two rows together.
    Sparse mode (psm 11) has no line ids; group by vertical centre, using
    only normal-height words to estimate the line height.
    """
    if not words:
        return []
    if use_layout:
        keyed = {}
        for word in words:
            keyed.setdefault(word["key"], []).append(word)
        lines = [{"centre": statistics.median(w["top"] + w["height"] / 2 for w in group),
                  "words": group} for group in keyed.values()]
        return _finish_lines(lines)
    typical_height = statistics.median(w["height"] for w in words)
    words = sorted(words, key=lambda w: (w["top"] + w["height"] / 2, w["left"]))
    lines = []
    for word in words:
        centre = word["top"] + word["height"] / 2
        for line in lines:
            if abs(centre - line["centre"]) <= max(6, min(line["height"], typical_height * 1.6) * .55):
                line["words"].append(word)
                count = len(line["words"])
                line["centre"] = (line["centre"] * (count - 1) + centre) / count
                line["height"] = max(line["height"], word["height"])
                break
        else:
            lines.append({"centre": centre, "height": word["height"], "words": [word]})
    return _finish_lines(lines)


def _finish_lines(lines):
    output = []
    for line in sorted(lines, key=lambda item: item["centre"]):
        # Every recognised token is kept as evidence (a misread Korean word
        # may come out as Latin); line confidence uses the Korean words.
        kept = [w for w in line["words"] if str(w["text"]).strip()]
        if not kept:
            continue
        ordered = sorted(kept, key=lambda w: w["left"])
        heights = [w["height"] for w in ordered]
        typical = statistics.median(heights) if heights else 10
        text = ordered[0]["text"]
        for previous, current in zip(ordered, ordered[1:]):
            gap = current["left"] - (previous["left"] + previous["width"])
            # Tesseract can split one Korean word into syllable "words".
            # Only a visibly wide gap is a printed word space.
            text += (" " if gap > typical * .22 else "") + current["text"]
        korean_words = [w for w in ordered if HANGUL.search(w["text"])]
        confidences = [float(w["conf"]) for w in (korean_words or ordered)
                       if float(w["conf"]) >= 0]
        output.append({
            "text": text.strip(),
            "conf": round(sum(confidences) / len(confidences), 1) if confidences else -1.0,
            "bbox": (min(w["left"] for w in ordered), min(w["top"] for w in ordered),
                     max(w["left"] + w["width"] for w in ordered),
                     max(w["top"] + w["height"] for w in ordered)),
        })
    return output


def batch_ocr(images, psm=4, lang="kor+eng", timeout=90, stats=None):
    """Return one list of line dicts per input image (same order).

    Raises RuntimeError on timeout so the caller can fall back explicitly.
    """
    if not images:
        return []
    sheet, spans = _stack(images)
    started = time.perf_counter()
    try:
        data = pytesseract.image_to_data(
            sheet, lang=lang, config=f"--oem 3 --psm {psm}",
            output_type=pytesseract.Output.DICT, timeout=timeout,
        )
    finally:
        if stats is not None:
            stats["calls"] = stats.get("calls", 0) + 1
            stats["seconds"] = round(stats.get("seconds", 0.0)
                                     + time.perf_counter() - started, 3)
            stats["pixels"] = stats.get("pixels", 0) + sheet.width * sheet.height
    per_crop = [[] for _ in images]
    for index, text in enumerate(data["text"]):
        if not str(text).strip():
            continue
        top, height = data["top"][index], data["height"][index]
        centre = top + height / 2
        for crop_index, (start, end) in enumerate(spans):
            if start - GAP / 2 <= centre <= end + GAP / 2:
                per_crop[crop_index].append({
                    "text": str(text).strip(), "conf": data["conf"][index],
                    "left": data["left"][index] - MARGIN, "top": top - start,
                    "width": data["width"][index], "height": height,
                    "key": (data["block_num"][index], data["par_num"][index],
                            data["line_num"][index]),
                })
                break
    return [_lines_from_words(words, use_layout=psm != 11) for words in per_crop]


def strip_ocr(images, lang="kor+eng", timeout=60, stats=None, gap=80):
    """Read many single-line crops as ONE horizontal line (psm 7).

    Short bold badge lines ('IH', '인덕션') are misread by block layout
    modes but read correctly in single-line mode. Placing every such line
    side by side keeps it to one Tesseract process; words are mapped back
    to their crop by x position.
    """
    if not images:
        return []
    images = [_binarize(image) for image in images]
    height = max(image.height for image in images) + 40
    width = sum(image.width + gap for image in images) + gap
    sheet = Image.new("L", (width, height), 255)
    spans, x = [], gap // 2
    for image in images:
        sheet.paste(image, (x, (height - image.height) // 2))
        spans.append((x, x + image.width, (height - image.height) // 2))
        x += image.width + gap
    started = time.perf_counter()
    try:
        data = pytesseract.image_to_data(
            sheet, lang=lang, config="--oem 3 --psm 7",
            output_type=pytesseract.Output.DICT, timeout=timeout,
        )
    finally:
        if stats is not None:
            stats["calls"] = stats.get("calls", 0) + 1
            stats["seconds"] = round(stats.get("seconds", 0.0)
                                     + time.perf_counter() - started, 3)
            stats["pixels"] = stats.get("pixels", 0) + sheet.width * sheet.height
    per_crop = [[] for _ in images]
    for index, text in enumerate(data["text"]):
        if not str(text).strip():
            continue
        centre = data["left"][index] + data["width"][index] / 2
        for crop_index, (start, end, top) in enumerate(spans):
            if start - gap / 2 <= centre <= end + gap / 2:
                per_crop[crop_index].append({
                    "text": str(text).strip(), "conf": data["conf"][index],
                    "left": data["left"][index] - start, "top": data["top"][index] - top,
                    "width": data["width"][index], "height": data["height"][index],
                    "key": (0, 0, 0),
                })
                break
    return [_lines_from_words(words, use_layout=True) for words in per_crop]
