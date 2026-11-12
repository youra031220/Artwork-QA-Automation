"""Recover readable *review candidates* for physically fragmented coating claims.

PDF-native glyphs often map Korean spaces and digits to replacement characters
despite printing correctly. Never silently rewrite source evidence, and never
approve numeric values read only by OCR. A candidate is displayed as OCR_REVIEW.
"""
import io
import re

import fitz
from PIL import Image, ImageOps
import pytesseract

KO = re.compile(r"[가-힣]")
COATING_HEAD = re.compile(r"테팔.*기본.*코팅.*대비")
COATING_NUMBER = re.compile(r"배.*더.*오래가는")
COATING_TAIL = re.compile(r"엑스트라.*라이프.*논스틱.*코팅")


def _bounds(group):
    coords = [p.get("bbox") for p in group.get("source_coordinates", [])
              if p.get("bbox") and len(p["bbox"]) == 4]
    if not coords:
        return None
    r = fitz.Rect(coords[0])
    for box in coords[1:]:
        r |= fitz.Rect(box)
    return r


def _close(a, b):
    xgap = max(0, b.x0 - a.x1, a.x0 - b.x1)
    ygap = max(0, b.y0 - a.y1, a.y0 - b.y1)
    return xgap < 75 and ygap < 70 and abs(a.x0-b.x0) < 85


def _ocr_coating(page, bounds, dpi, upside_down):
    region = fitz.Rect(bounds.x0-6, bounds.y0-4,
                       bounds.x1+8, bounds.y1+5) & page.rect
    if region.is_empty:
        return None
    pix = page.get_pixmap(matrix=fitz.Matrix(dpi/72,dpi/72),
                          clip=region, alpha=False)
    img = Image.frombytes("RGB",(pix.width,pix.height),pix.samples)
    if upside_down:
        img = img.rotate(180, expand=True)
    img = ImageOps.expand(ImageOps.autocontrast(ImageOps.grayscale(img)),
                           border=30, fill=255)
    for psm in (6, 11):
        try:
            raw = pytesseract.image_to_string(
                img, lang="kor+eng", config=f"--oem 3 --psm {psm}")
        except pytesseract.TesseractError:
            continue
        normalized = re.sub(r"\s+", " ", raw)
        head = re.search(r"테팔\s*기본\s*코팅\s*대비\s*(최대)?", normalized)
        numeric = re.search(r"(?:최대\s*)?(\d{1,2})\s*배\s*더\s*오래가는", normalized)
        tail = re.search(r"엑스트라\s*라이프\s*논스틱\s*코팅", normalized)
        if not (head and numeric and tail):
            continue
        # Verify their reading order; OCR is not permitted to piece a claim
        # together from unrelated image regions or languages.
        if not (head.start() < numeric.start() < tail.start()):
            continue
        value = numeric.group(1)
        if int(value) < 1 or int(value) > 20:
            continue
        return (f"테팔 기본 코팅 대비 최대 {value}배 더 오래가는 "
                "엑스트라 라이프 논스틱 코팅")
    return None


def combine_damaged_coating(groups, rows, pdf_contents, dpi=350):
    """Join at most one *verified OCR reading candidate* per physical cluster.

    pdf_contents maps the original uploaded filenames to PDF bytes. The
    unmodified raw Korean lines remain available in the app's evidence and ZIP.
    If OCR fails or the three printed objects are not uniquely located, keep
    every original group unchanged.
    """
    if not pdf_contents:
        return groups
    by_file = {}
    for i, g in enumerate(groups):
        key = (g.get("file"), g.get("page"))
        by_file.setdefault(key, []).append((i,g))
    replacements = {}
    removed = set()
    documents = {}
    try:
        for (filename, page_num), entries in by_file.items():
            if filename not in pdf_contents:
                continue
            heads = [(i,g) for i,g in entries
                     if COATING_HEAD.search(g.get("paragraph",""))]
            for head_idx, head in heads:
                if head_idx in removed or head_idx in replacements:
                    continue
                head_box = _bounds(head)
                if head_box is None:
                    continue
                neighbors = []
                for pattern in (COATING_NUMBER, COATING_TAIL):
                    nearby = [(i,g) for i,g in entries
                              if i != head_idx and i not in removed
                              and pattern.search(g.get("paragraph",""))
                              and _bounds(g) is not None
                              and _close(head_box,_bounds(g))]
                    if len(nearby) != 1:
                        break
                    neighbors.append(nearby[0])
                if len(neighbors) != 2 or neighbors[0][0] == neighbors[1][0]:
                    continue
                number_idx, number = neighbors[0]
                tail_idx, tail = neighbors[1]
                # Only OCR visibly damaged source, never replace already clean
                # native PDF digits with an OCR alternative.
                parts = (head, number, tail)
                original = " / ".join(p["paragraph"] for p in parts)
                if "\ufffd" not in original:
                    continue
                joined = head_box | _bounds(number) | _bounds(tail)
                if joined.width > 240 or joined.height > 145:
                    continue
                try:
                    if filename not in documents:
                        documents[filename] = fitz.open(
                            stream=pdf_contents[filename], filetype="pdf")
                    doc = documents[filename]
                    page = doc[int(page_num)-1]
                    source_indices = [
                        x for p in parts for x in p.get("line_indices", [])
                        if isinstance(x,int) and 0 <= x < len(rows)
                    ]
                    upside_down = bool(source_indices and
                                       rows[source_indices[0]].get("dir_x",1) < -0.8)
                    candidate = _ocr_coating(page, joined, dpi, upside_down)
                except (ValueError, IndexError, fitz.FileDataError):
                    continue
                if not candidate:
                    continue
                base = dict(head)
                base["paragraph"] = candidate
                base["original_paragraph"] = original
                base["type"] = "OCR 문구 연결"
                base["status"] = "OCR 읽기 후보 · PDF 원본 확인 필요"
                base["numeric_review"] = True
                base["ocr_reconstructed"] = True
                base["ocr_candidates"] = (
                    [x for p in parts for x in p.get("ocr_candidates", [])] +
                    [{"text":candidate, "source":"원본 PDF 인접 3개 객체를 350 DPI로 재인식"}]
                )
                base["warnings"] = list(dict.fromkeys(
                    [x for p in parts for x in p.get("warnings", [])] +
                    ["OCR에서 읽은 수치는 최종 정답으로 확정하지 않았습니다."]
                ))
                for key in ("source_coordinates", "line_indices",
                            "raw_evidence_ids", "numeric_tokens"):
                    data = [x for p in parts for x in p.get(key, [])]
                    base[key] = list(dict.fromkeys(data)) if key in (
                        "line_indices", "raw_evidence_ids", "numeric_tokens") else data
                base["line_count"] = sum(p.get("line_count",0) for p in parts)
                replacements[head_idx] = base
                removed.update((number_idx,tail_idx))
    finally:
        for doc in documents.values():
            doc.close()
    return [replacements.get(i,g) for i,g in enumerate(groups) if i not in removed]
