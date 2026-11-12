"""Read missing WORLD N°1 Korean citation digits from their printed image.

We never substitute the approved workbook, English citation or the edition
year for a missing Korean number. A numeric restoration requires independent
raster OCR evidence from the Korean citation's physical PDF area. The native
source remains in original_paragraph and the item retains numeric REVIEW.
"""
import re

import fitz
import pytesseract
from PIL import Image, ImageOps

BAD = r"[\ufffd□埻埼基埿]"
WORLD = re.compile(r"세계\s*판매\s*"+BAD+r"{0,2}\s*위|세계\s*판매\s*1\s*위")
YEAR_LOST = re.compile(r"("+BAD+r"{2,8})\s*기준")
LOST_RANK = re.compile(BAD+r"{1,3}\s*위")


def _bounds(group):
    boxes=[fitz.Rect(c["bbox"]) for c in group.get("source_coordinates",[])
           if c.get("bbox") and len(c["bbox"])==4]
    if not boxes:
        return None
    out=boxes[0]
    for r in boxes[1:]:
        out |= r
    return out


def _read_korean_print(page, rect, dpi=350):
    """Read Korean rank and sales-data year from printed Korean lines only.

    A narrow crop can clip the line ending, so inspect two bounded margins
    and two Tesseract segmentations. Return only digits OCR observed after
    Korean anchors; never copy the adjacent Turkish/English year.
    """
    found_rank=None
    found_year=None
    evidence=[]
    for top_margin in (5,12):
        clip=fitz.Rect(rect.x0-5,rect.y0-top_margin,
                       rect.x1+5,rect.y1+7) & page.rect
        if clip.is_empty:
            continue
        pix=page.get_pixmap(clip=clip,
             matrix=fitz.Matrix(dpi/72,dpi/72),alpha=False)
        img=ImageOps.autocontrast(ImageOps.grayscale(
            Image.frombytes("RGB",(pix.width,pix.height),pix.samples)))
        for psm in (6,3):
            try:
                result=pytesseract.image_to_string(
                    img,lang="kor+eng",config=f"--oem 3 --psm {psm}")
            except pytesseract.TesseractError:
                continue
            norm=" ".join(result.split())
            evidence.append(norm)
            if re.search(r"세계\s*판매\s*1\s*위",norm):
                found_rank="1"
            korean_year=re.search(
                r"브랜드\s*(?:매출|메출)\s*[,，]?\s*(20\d{2})\s*기[준순]",
                norm)
            if korean_year:
                found_year=korean_year.group(1)
            if found_rank and found_year:
                return found_rank,found_year,norm
    if found_rank or found_year:
        return found_rank,found_year," ".join(evidence)
    return None


def repair_korean_world_years(groups,pdf_contents,dpi=350):
    """Repair only in PDF-cropped source, never based on matching template."""
    docs={}
    out=[]
    try:
        for g in groups:
            old=str(g.get("paragraph",""))
            if not ("세계판매" in old or "세계 판매" in old):
                out.append(g)
                continue
            if "Euromonitor" not in old:
                out.append(g)
                continue
            needs_rank=bool(LOST_RANK.search(old))
            needs_year=bool(YEAR_LOST.search(old))
            if not(needs_rank or needs_year):
                out.append(g)
                continue
            filename=g.get("file")
            bbox=_bounds(g)
            if bbox is None or filename not in pdf_contents:
                out.append(g)
                continue
            try:
                if filename not in docs:
                    docs[filename]=fitz.open(stream=pdf_contents[filename],filetype="pdf")
                page=docs[filename][int(g["page"])-1]
                read=_read_korean_print(page,bbox,dpi)
            except (ValueError,IndexError,fitz.FileDataError):
                read=None
            if not read:
                out.append(g)
                continue
            number,year,ocr=read
            new=old
            if needs_rank and number:
                new=LOST_RANK.sub(number+"위",new,count=1)
            if needs_year and year:
                new=YEAR_LOST.sub(year+" 기준",new,count=1)
            if new==old:
                out.append(g)
                continue
            updated=dict(g)
            updated["paragraph"]=new
            updated["original_paragraph"]=g.get("original_paragraph",old)
            updated["numeric_review"]=True
            updated["ocr_reconstructed"]=True
            updated["status"]="국문 각주 숫자 원본 확인 필요"
            updated["ocr_candidates"]=list(g.get("ocr_candidates") or [])+[{
                "text":new,"source":"국문 세계 1위 각주 인쇄 영역 OCR"}]
            out.append(updated)
    finally:
        for doc in docs.values():
            doc.close()
    return out
