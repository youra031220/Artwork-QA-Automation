"""Pixel-first artwork pictogram candidate detection, without text-anchor crops.

Text-only candidate boxes are deliberately rejected: a Euromonitor footnote,
barcode, or large red headline is NOT the logo. Detection returns candidates
except for QR, which has a native pixel finder check. This module requires no
company-supplied reference assets checked into the repository.
"""
import re
import fitz


def _render(page, scale=1.2):
    import cv2
    import numpy as np
    pix=page.get_pixmap(matrix=fitz.Matrix(scale,scale),
                        colorspace=fitz.csRGB,alpha=False)
    a=np.frombuffer(pix.samples,dtype=np.uint8).reshape(pix.height,pix.width,3)
    return a,cv2.cvtColor(a,cv2.COLOR_RGB2HSV)


def _rect(x,y,w,h,scale):
    return [round(x/scale,2),round(y/scale,2),
            round((x+w)/scale,2),round((y+h)/scale,2)]


def _words_inside(page,box):
    return " ".join(page.get_textbox(fitz.Rect(box)).split())


def _solid_color_regions(mask,min_side=16,max_side=210):
    import cv2
    contours,_=cv2.findContours(mask,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
    for contour in contours:
        x,y,w,h=cv2.boundingRect(contour)
        if min_side<=w<=max_side and min_side<=h<=max_side:
            yield x,y,w,h,cv2.contourArea(contour)


def image_mark_candidates(page, filename, metadata=None):
    """Recognize logo-specific visual structures; never return random text crops.

    High precision over recall is intentional: without a positive visual match
    mark absence remains REVIEW, not FAIL.
    """
    import cv2
    import numpy as np
    metadata=metadata or {}
    scale=min(1.25,max(.7,1450/max(page.rect.width,page.rect.height)))
    rgb,hsv=_render(page,scale)
    h,w=hsv.shape[:2]
    results=[]

    def add(code,label,bbox,method,confidence="CANDIDATE"):
        x0,y0,x1,y1=bbox
        if not (x1>x0 and y1>y0):
            return
        if any(old["code"]==code and abs(old["bbox"][0]-x0)<8 and
               abs(old["bbox"][1]-y0)<8 for old in results):
            return
        results.append(dict(file=filename,page=page.number+1,
            code=code,label=label,status=confidence,bbox=bbox,
            method=method,decoded="",finding="로고 형태를 가진 이미지 후보"))

    # RECYCLABLE METAL: round dark/green core enclosing pale three-arrow mark.
    # Exclude a plain green check badge by requiring substantial light area
    # within the green disc rather than relying on a green contour alone.
    green=cv2.inRange(hsv,np.array((30,50,25),dtype=np.uint8),
                         np.array((96,255,248),dtype=np.uint8))
    green=cv2.morphologyEx(green,cv2.MORPH_CLOSE,np.ones((5,5),np.uint8))
    for x,y,cw,ch,area in _solid_color_regions(green,12,210):
        if not (.76<cw/ch<1.25 and .34<area/(cw*ch)<.94):
            continue
        disc=hsv[y:y+ch,x:x+cw]
        center=disc[ch//5:ch*4//5,cw//5:cw*4//5]
        white=((center[:,:,1]<75)&(center[:,:,2]>165)).mean()
        darkgreen=cv2.inRange(center,np.array((31,50,25),dtype=np.uint8),
                                    np.array((95,255,230),dtype=np.uint8)).mean()/255
        if white<.10 or darkgreen<.22:
            continue
        add("RECYCLING","재활용 마크",_rect(x,y,cw,ch,scale),
            "recycling_green_symbol_shape")

    # WORLD N1: actual red-panel glyphs, not nearby multilingual source text.
    red=cv2.inRange(hsv,np.array((0,100,65),dtype=np.uint8),
                       np.array((13,255,255),dtype=np.uint8))
    red |=cv2.inRange(hsv,np.array((170,100,65),dtype=np.uint8),
                         np.array((179,255,255),dtype=np.uint8))
    red=cv2.morphologyEx(red,cv2.MORPH_CLOSE,np.ones((5,5),np.uint8))
    for x,y,cw,ch,area in _solid_color_regions(red,28,270):
        if not (.60<cw/ch<3.5 and area/(cw*ch)>.46):
            continue
        box=_rect(x,y,cw,ch,scale)
        # Find actual glyphs inside or immediately above the red badge.
        region=fitz.Rect(box)
        text=_words_inside(page,region+(-8,-22,8,8)).upper()
        if not (re.search(r"\bWORLD\b",text) and
                re.search(r"N\s*[°ºO]?\s*1|NO\s*1",text)):
            continue
        add("WORLD_NO1","세계 1위 엠블럼",box,"world_red_panel_with_printed_title")

    # MADE IN FRANCE: compact light badge with French tricolor and word FRANCE.
    # Test a small surrounding rectangle rather than text at any location.
    country=metadata.get("manufacturing_country")
    if country=="FRANCE":
        for word in page.search_for("FRANCE")[:25]:
            box=fitz.Rect(word.x0-40,word.y0-45,word.x1+40,word.y1+18)&page.rect
            if box.is_empty or box.width>125 or box.height>125:
                continue
            pix=page.get_pixmap(clip=box,matrix=fitz.Matrix(2,2),alpha=False)
            pixels=np.frombuffer(pix.samples,dtype=np.uint8).reshape(pix.height,pix.width,3)
            subhsv=cv2.cvtColor(pixels,cv2.COLOR_RGB2HSV)
            blue=cv2.inRange(subhsv,np.array((95,85,55),dtype=np.uint8),
                                     np.array((140,255,255),dtype=np.uint8))
            # Printed FRANCE word together with actual blue accent is evidence
            # of badge layout, unlike a plain manufacturer address.
            if np.count_nonzero(blue)>15 and "FRANCE" in _words_inside(page,box).upper():
                add("MADE_IN_FRANCE","Made in France 배지",
                    [box.x0,box.y0,box.x1,box.y1],"french_badge_text_blue_pixel")

    # INDuction: orange round IH badge, distinguish from red text/panels.
    orange=cv2.inRange(hsv,np.array((4,95,55),dtype=np.uint8),
                           np.array((25,255,255),dtype=np.uint8))
    orange=cv2.morphologyEx(orange,cv2.MORPH_CLOSE,np.ones((5,5),np.uint8))
    for x,y,cw,ch,area in _solid_color_regions(orange,16,145):
        if not (.76<cw/ch<1.26 and .35<area/(cw*ch)<.93):
            continue
        roi=rgb[y:y+ch,x:x+cw]
        if roi.size==0:
            continue
        # Inner letters/white marks must interrupt the orange disc.
        light=(roi[:,:,0]>205)&(roi[:,:,1]>205)&(roi[:,:,2]>205)
        inner=light[ch//4:ch*3//4,cw//4:cw*3//4].mean()
        if inner<.055:
            continue
        add("INDUCTION","인덕션 아이콘",_rect(x,y,cw,ch,scale),
            "orange_round_ih_visual_candidate")
    return results


def clean_and_detect(page, filename, earlier, metadata=None):
    """No text-nearby crops survive as logo evidence."""
    qr=[item for item in earlier if item.get("code") in
        {"TEFAL_COMMITMENTS_QR","USE_CARE_QR","UNKNOWN_QR"}
        and item.get("status")=="DETECTED"]
    visuals=image_mark_candidates(page,filename,metadata)
    return qr+visuals
