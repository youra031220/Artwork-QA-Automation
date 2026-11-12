"""Raster evidence for Tefal artwork logos/QR marks.

No company PDF, logo screenshot, or template is shipped with the source.
OpenCV detects an actual QR finder/code pattern in rendered PDF pixels.
Other logo classes are conservative *visual candidates*: native printed
anchors yield small image crops for review, never automatic logo presence.
"""
import io
import re

import fitz

MARKS = (
    ("TEFAL_COMMITMENTS_QR", "테팔 커미트먼트 QR"),
    ("USE_CARE_QR", "사용방법 QR"),
    ("RECYCLING", "재활용 마크"),
    ("WORLD_NO1", "세계 1위 엠블럼"),
    ("INDUCTION", "인덕션 아이콘"),
    ("MADE_IN_FRANCE", "Made in France 배지"),
)

ANCHORS = {
    "TEFAL_COMMITMENTS_QR": ("COMMITMENTS", "COMMITMENT"),
    "USE_CARE_QR": ("SCAN", "USE & CARE", "USE AND CARE", "QR"),
    "RECYCLING": ("RECYCLABLE", "RECYCLING", "재활용", "RECYCLABLE METAL"),
    "WORLD_NO1": ("WORLD N", "WORLD", "세계판매", "세계 판매"),
    "INDUCTION": ("ALL HOBS", "INDUCTION", "인덕션"),
    "MADE_IN_FRANCE": ("MADE IN FRANCE", "FABRIQUÉ EN FRANCE"),
}


def _compact_rect(box, page):
    if box is None:
        return None
    r=fitz.Rect(box) & page.rect
    return r if not r.is_empty else None


def _near_anchor(anchor, rect, radius=145):
    a=fitz.Rect(anchor)
    dx=max(0, rect.x0-a.x1, a.x0-rect.x1)
    dy=max(0, rect.y0-a.y1, a.y0-rect.y1)
    return dx <= radius and dy <= radius


def _anchors(page, terms):
    result=[]
    for term in terms:
        try:
            found=page.search_for(term)
        except (ValueError, RuntimeError):
            found=[]
        for rect in found:
            if not any(abs(old.x0-rect.x0)<2 and abs(old.y0-rect.y0)<2
                       for old in result):
                result.append(rect)
    return result


def _qr_in_crop(page, region, scale, detector):
    import cv2
    import numpy as np
    region=_compact_rect(region,page)
    if region is None:
        return []
    pix=page.get_pixmap(clip=region,
                        matrix=fitz.Matrix(scale,scale),
                        colorspace=fitz.csGRAY,alpha=False)
    pixels=np.frombuffer(pix.samples,dtype=np.uint8).reshape(pix.height,pix.width)
    results=[]
    # Use detectMulti to include codes which cannot be decoded because of
    # print noise. A QR finder must be present (not a text guess).
    try:
        present, points=detector.detectMulti(pixels)
    except cv2.error:
        present,points=False,None
    if not present or points is None:
        return []
    for corners in points:
        bbox=[
            region.x0+float(corners[:,0].min())/scale,
            region.y0+float(corners[:,1].min())/scale,
            region.x0+float(corners[:,0].max())/scale,
            region.y0+float(corners[:,1].max())/scale,
        ]
        text=""
        try:
            text,_,_=detector.detectAndDecode(pixels[
                max(0,int(corners[:,1].min())-12):min(pixels.shape[0],int(corners[:,1].max())+13),
                max(0,int(corners[:,0].min())-12):min(pixels.shape[1],int(corners[:,0].max())+13)])
        except (cv2.error,ValueError):
            pass
        results.append({"bbox":bbox,"decoded":text or "",
                        "method":"raster_qr_finder","confidence":"DETECTED"})
    return results


def _qr_candidates(page):
    """Zoom around native anchor words; tiny QR codes evade full-page scans."""
    try:
        import cv2
    except ImportError:
        return []
    decoder=cv2.QRCodeDetector()
    areas=[]
    for token in ("COMMITMENTS","SCAN","QR","USE & CARE"):
        for anchor in _anchors(page,(token,)):
            # Include codes directly above or next to their label.
            areas.append((token,anchor,fitz.Rect(
                anchor.x0-125,anchor.y0-100,anchor.x1+115,anchor.y1+95)))
    unique=[]
    for token,anchor,region in areas:
        if len(unique)>=16:
            break
        for result in _qr_in_crop(page,region,3.5,decoder):
            box=fitz.Rect(result["bbox"])
            if any(abs(box.x0-fitz.Rect(old["bbox"]).x0)<8
                   and abs(box.y0-fitz.Rect(old["bbox"]).y0)<8
                   for old in unique):
                continue
            result["anchor"]=token
            unique.append(result)
    return unique


def _world_badge_pixels(page, rect):
    """Require BOTH 'WORLD' native glyphs and a compact saturated red badge.

    A plain WORLD text label, even next to a logo, is not enough. A positively
    observed red artwork panel with text inside it is a stronger pixel match.
    """
    import cv2
    import numpy as np
    rect=fitz.Rect(rect)
    clip=fitz.Rect(rect.x0-18,rect.y0-18,
                   rect.x1+22,rect.y1+24) & page.rect
    if clip.is_empty:
        return False
    pix=page.get_pixmap(clip=clip,matrix=fitz.Matrix(1.5,1.5),
                        colorspace=fitz.csRGB,alpha=False)
    rgb=np.frombuffer(pix.samples,dtype=np.uint8).reshape(pix.height,pix.width,3)
    hsv=cv2.cvtColor(rgb,cv2.COLOR_RGB2HSV)
    red=(cv2.inRange(hsv,np.array((0,100,90),dtype=np.uint8),
                     np.array((12,255,255),dtype=np.uint8)) |
         cv2.inRange(hsv,np.array((170,100,90),dtype=np.uint8),
                     np.array((179,255,255),dtype=np.uint8)))
    return float(np.count_nonzero(red))/(red.size or 1) >= .16


def _recycling_pixel_candidates(page):
    """Find plausible compact green circular recycling pictograms in pixels.

    This is shape evidence, not proof of recycling semantics. Keep REVIEW.
    Vector logos embedded in PDF still appear in the rendered raster image.
    """
    import cv2
    import numpy as np
    render_scale=min(1.15,max(0.55,1500/max(page.rect.width,page.rect.height)))
    pix=page.get_pixmap(matrix=fitz.Matrix(render_scale,render_scale),
                        colorspace=fitz.csRGB,alpha=False)
    pixels=np.frombuffer(pix.samples,dtype=np.uint8).reshape(
        pix.height,pix.width,3)
    hsv=cv2.cvtColor(pixels,cv2.COLOR_RGB2HSV)
    mask=cv2.inRange(hsv,np.array((30,35,20),dtype=np.uint8),
                     np.array((95,255,240),dtype=np.uint8))
    contours,_=cv2.findContours(mask,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
    found=[]
    for contour in contours:
        x,y,w,h=cv2.boundingRect(contour)
        if not (18*render_scale <= w <= 105*render_scale and
                18*render_scale <= h <= 105*render_scale):
            continue
        if not (.74<=w/h<=1.32):
            continue
        filled=cv2.contourArea(contour)/(w*h)
        if not (.55<=filled<=.90):
            continue
        bbox=[x/render_scale,y/render_scale,(x+w)/render_scale,(y+h)/render_scale]
        found.append(dict(bbox=bbox,method="green_circular_pixel_candidate"))
    return sorted(found,key=lambda x:(x["bbox"][1],x["bbox"][0]))[:15]


def detect_pdf_marks(pdf_bytes, filename, metadata=None, max_pixels=30_000_000):
    """Return conservative per-page mark evidence with PDF coordinates.

    Status DETECTED means QR pixels actually formed a finder/code pattern.
    Candidate marks do NOT mean a verified recycling, no.1 or origin logo.
    Absence of a detected QR/mark is always NOT_VERIFIED, not 'absent'.
    """
    metadata=metadata or {}
    findings=[]
    with fitz.open(stream=pdf_bytes,filetype="pdf") as doc:
        for page in doc:
            if page.rect.width*page.rect.height > max_pixels:
                # Unusually huge vector pages can be rendered locally by
                # a human. Do not blow worker memory on unbounded artboards.
                continue
            qr=_qr_candidates(page)
            commitment_anchors=_anchors(page,ANCHORS["TEFAL_COMMITMENTS_QR"])
            care_anchors=_anchors(page,ANCHORS["USE_CARE_QR"])
            for item in qr:
                region=fitz.Rect(item["bbox"])
                commitment=any(_near_anchor(a,region,100) for a in commitment_anchors)
                care=any(_near_anchor(a,region,95) for a in care_anchors)
                # A QR near the commitment banner is not necessarily the
                # separate use/care QR on another panel.
                code="TEFAL_COMMITMENTS_QR" if commitment else (
                    "USE_CARE_QR" if care else "UNKNOWN_QR")
                findings.append(dict(file=filename,page=page.number+1,
                    code=code,label=dict(MARKS).get(code,"기타 QR"),
                    status="DETECTED",bbox=item["bbox"],method="qr_pixels",
                    decoded=item["decoded"],finding="QR 코드 이미지 확인됨"))
            for candidate in _recycling_pixel_candidates(page):
                findings.append(dict(file=filename,page=page.number+1,
                    code="RECYCLING",label="재활용 마크",status="CANDIDATE",
                    bbox=candidate["bbox"],method=candidate["method"],
                    decoded="",finding="재활용 마크 형태의 녹색 원형 이미지 후보"))
            for code,label in MARKS[2:]:
                if code=="MADE_IN_FRANCE" and metadata.get("manufacturing_country")!="FRANCE":
                    continue
                # OCR'd logos or labels must still be visually inspected.
                # We show the rendered region but do NOT promote text
                # presence into a verified raster logo detection.
                positions=_anchors(page,ANCHORS[code])
                for anchor in positions[:5]:
                    r=fitz.Rect(anchor.x0-35,anchor.y0-35,
                                anchor.x1+35,anchor.y1+35) & page.rect
                    if r.is_empty:
                        continue
                    is_red_badge=(code=="WORLD_NO1" and
                                  _world_badge_pixels(page,anchor) and
                                  bool(re.search(r"WORLD",page.get_textbox(anchor),re.I)))
                    findings.append(dict(file=filename,page=page.number+1,
                        code=code,label=label,
                        status="DETECTED" if is_red_badge else "CANDIDATE",
                        bbox=[r.x0,r.y0,r.x1,r.y1],
                        method=("red_world_badge_pixels" if is_red_badge
                                else "image_region_text_anchor"),decoded="",
                        finding=("붉은 WORLD 엠블럼 이미지 확인됨" if is_red_badge
                                 else "관련 인쇄 영역 발견 · 마크 모양 확인 필요")))
    return findings


def review_mark_rules(findings, summaries, metadata, filename):
    """Mark/claim conditional checks, with no unproved image absence FAIL."""
    in_file=[f for f in findings if f.get("file")==filename]
    native=" ".join(line.get("text","") for s in summaries
                    if s.get("file")==filename
                    for line in s.get("raw_evidence",[]))
    ko=" ".join(s.get("korean_text","") for s in summaries
                if s.get("file")==filename)
    product=next((m for m in metadata if m.get("file")==filename),{})
    results=[]
    for code,label in MARKS:
        if code=="MADE_IN_FRANCE" and product.get("manufacturing_country")!="FRANCE":
            continue
        hits=[f for f in in_file if f["code"]==code]
        definite=[f for f in hits if f["status"]=="DETECTED"]
        status="OK" if definite and code=="TEFAL_COMMITMENTS_QR" else "REVIEW"
        if definite:
            finding=label+" 이미지 발견"
        elif hits:
            finding=label+" 관련 이미지 영역 확인 필요"
        else:
            finding=label+" 이미지 미확인 · 실제 부재로 확정 불가"
        if code=="RECYCLING" and hits:
            if not re.search(r"적절한\s*분리\s*배출",native+ko):
                finding+=" · 한국어 분리배출 안내 문구 확인 필요"
        if code=="WORLD_NO1" and hits:
            if "Euromonitor" not in native:
                finding+=" · 세계 1위 출처 각주 확인 필요"
        if code=="INDUCTION" and not re.search(r"\bINDUCTION\b|인덕션",native,re.I):
            continue
        if code=="USE_CARE_QR" and not hits:
            finding+=" · 슬리브 적용 여부에 따라 필수 여부 확인"
        results.append(dict(
            file=filename,rule_id="IMG-"+code,category="마크·QR",
            rule_type="IMAGE_CONDITIONAL",condition="원장·회의 조건",
            min_count=0,max_count=None,found_occurrences=len(definite),
            distinct_variants=len(hits),matched_phrase_ids=[],
            review_candidates=[],applicability="APPLICABLE" if hits else "UNDETERMINED",
            status=status,finding=finding,
            source_reference="PDF raster + Excel/meeting criteria",
            image_evidence=hits))
    return results


def preview_mark(pdf_bytes, page_no, bbox, scale=3.0):
    """PNG evidence only; no files persisted."""
    with fitz.open(stream=pdf_bytes,filetype="pdf") as doc:
        page=doc[int(page_no)-1]
        r=fitz.Rect(bbox)
        margin=max(12,min(r.width,r.height)*.45)
        clip=fitz.Rect(r.x0-margin,r.y0-margin,r.x1+margin,r.y1+margin) & page.rect
        pix=page.get_pixmap(clip=clip,matrix=fitz.Matrix(scale,scale),alpha=False)
        return pix.tobytes("png")
