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
        # The logo is often a flattened image, so page.get_textbox()
        # returns nothing. Read glyphs within the red raster emblem itself.
        from PIL import Image
        import pytesseract
        region=fitz.Rect(box)
        crop=fitz.Rect(region.x0-9,region.y0-10,
                       region.x1+9,region.y1+10)&page.rect
        px=page.get_pixmap(clip=crop,matrix=fitz.Matrix(5,5),alpha=False)
        pic=Image.frombytes("RGB",(px.width,px.height),px.samples)
        try:
            text=pytesseract.image_to_string(pic,lang="eng",
                       config="--oem 3 --psm 6").upper()
        except pytesseract.TesseractError:
            continue
        if not (re.search(r"N[°º'’\s\\-]{0,3}1",text)
                and re.search(r"WORLD|MONDIAL|COOKWARE",text)):
            continue
        add("WORLD_NO1","세계 1위 엠블럼",box,
            "world_red_panel_verified_by_raster_text","DETECTED")

    # MADE IN FRANCE: two small BLUE/RED bars on a pale badge with FRANCE
    # underneath. Manufacturer addresses elsewhere on the page are ignored.
    country=metadata.get("manufacturing_country")
    if country=="FRANCE":
        from PIL import Image
        import pytesseract
        blue=cv2.inRange(hsv,np.array((96,120,115),dtype=np.uint8),
                             np.array((135,255,255),dtype=np.uint8))
        redbar=red
        blue_contours,_=cv2.findContours(blue,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
        red_contours,_=cv2.findContours(redbar,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
        bars=[]
        for contour in red_contours:
            rx,ry,rw,rh=cv2.boundingRect(contour)
            if 7<=rw<=55 and 2<=rh<=13:
                bars.append((rx,ry,rw,rh))
        for contour in blue_contours:
            bx,by,bw,bh=cv2.boundingRect(contour)
            if not (7<=bw<=55 and 2<=bh<=13 and bw/bh>=2):
                continue
            partners=[bar for bar in bars if 4<=bar[0]-(bx+bw)<=55
                and abs(bar[1]-by)<=6 and .55<=bar[2]/bw<=1.65]
            for rx,ry,rw,rh in partners[:2]:
                bounds=fitz.Rect(
                    max(0,(bx-14)/scale),max(0,(by-26)/scale),
                    min(page.rect.x1,(rx+rw+15)/scale),
                    min(page.rect.y1,(by+52)/scale))
                pix=page.get_pixmap(clip=bounds,matrix=fitz.Matrix(5,5),alpha=False)
                patch=Image.frombytes("RGB",(pix.width,pix.height),pix.samples)
                try:
                    label=pytesseract.image_to_string(patch,lang="eng",
                                   config="--oem 3 --psm 6").upper()
                except pytesseract.TesseractError:
                    continue
                if "FRANCE" not in label:
                    continue
                add("MADE_IN_FRANCE","Made in France 배지",
                    [bounds.x0,bounds.y0,bounds.x1,bounds.y1],
                    "blue_red_france_badge_pixels","DETECTED")

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
