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
    # Thin green dielines can connect the true recycling disc to the entire
    # carton outline. Opening FIRST disconnects these 1px paths; closing
    # afterwards restores the disc. Verified against Mint Calm and Ruby PDFs.
    green=cv2.morphologyEx(green,cv2.MORPH_OPEN,np.ones((2,2),np.uint8))
    green=cv2.morphologyEx(green,cv2.MORPH_CLOSE,np.ones((3,3),np.uint8))
    for x,y,cw,ch,area in _solid_color_regions(green,12,95):
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
        except (pytesseract.TesseractError, pytesseract.TesseractNotFoundError):
            continue
        if not (re.search(r"N[°º'’\s\\-]{0,3}1",text)
                and re.search(r"WORLD|MONDIAL|COOKWARE",text)):
            continue
        add("WORLD_NO1","세계 1위 엠블럼",box,
            "world_red_panel_verified_by_raster_text","DETECTED")

    # Native glyphs may remain selectable inside a flattened-looking badge.
    # Mint Calm's WORLD / N1 / IN COOKWARE are separate text objects.
    # Confirm a compact red panel surrounding all three, not a footnote.
    words=page.get_text("words")
    worlds=[z for z in words if z[4].strip().upper()=="WORLD"]
    for word in worlds:
        wx0,wy0,wx1,wy1=word[:4]
        nearby=[z for z in words if
                abs(z[1]-wy0)<85 and abs(z[0]-wx0)<100]
        tokens=" ".join(z[4] for z in nearby).upper()
        if not (re.search(r"N\s*[°º]?\s*1|N1",tokens)
                and re.search(r"COOKWARE",tokens)):
            continue
        # Candidate is centred on WORLD and includes the badge's N1 line.
        region=fitz.Rect(wx0-7,wy0-8,wx1+9,wy1+28)&page.rect
        pix=page.get_pixmap(clip=region,matrix=fitz.Matrix(2,2),
                            colorspace=fitz.csRGB,alpha=False)
        patch=np.frombuffer(pix.samples,dtype=np.uint8).reshape(
            pix.height,pix.width,3)
        phsv=cv2.cvtColor(patch,cv2.COLOR_RGB2HSV)
        redmask=cv2.inRange(phsv,np.array((0,90,60),dtype=np.uint8),
                                 np.array((13,255,255),dtype=np.uint8))
        redmask |=cv2.inRange(phsv,np.array((170,90,60),dtype=np.uint8),
                                   np.array((179,255,255),dtype=np.uint8))
        if cv2.countNonZero(redmask)/redmask.size<.035:
            continue
        add("WORLD_NO1","세계 1위 엠블럼",
            [region.x0,region.y0,region.x1,region.y1],
            "native_world_n1_cookware_on_red_panel","DETECTED")

    # Direct raster pattern recognition: detect the white FRANCE label and
    # orange IH circle independently of PDF selectable text.
    # Colour masks restrict candidates to actual artwork (not footnotes).
    for code,label,mask,shape in (
        ("MADE_IN_FRANCE","Made in France 배지",
         cv2.inRange(hsv,np.array((90,45,40),np.uint8),
                         np.array((145,255,255),np.uint8)),"rect"),
        ("INDUCTION","인덕션 아이콘",
         cv2.bitwise_or(cv2.inRange(hsv,np.array((0,80,45),np.uint8),
                                       np.array((26,255,255),np.uint8)),
                        cv2.inRange(hsv,np.array((170,80,45),np.uint8),
                                       np.array((179,255,255),np.uint8))),"circle"),
    ):
        contours,_=cv2.findContours(mask,cv2.RETR_LIST,cv2.CHAIN_APPROX_SIMPLE)
        for cnt in contours:
            x,y,cw,ch=cv2.boundingRect(cnt)
            if not (12<=cw<=110 and 12<=ch<=110):
                continue
            ratio=cw/max(ch,1)
            if shape=="circle" and not (.75<=ratio<=1.25):
                continue
            # Evaluate the complete neighbourhood rather than the isolated
            # colour stroke. Native text is optional (flattened logos).
            margin=max(5,int(max(cw,ch)*.25))
            xx=max(0,x-margin); yy=max(0,y-margin)
            xx2=min(w,x+cw+margin);yy2=min(h,y+ch+margin)
            patch=rgb[yy:yy2,xx:xx2]
            if patch.size==0: continue
            gray=cv2.cvtColor(patch,cv2.COLOR_RGB2GRAY)
            try:
                import pytesseract
                from PIL import Image
                text=pytesseract.image_to_string(
                    Image.fromarray(cv2.resize(patch,None,fx=5,fy=5)),
                    lang="eng",config="--psm 11").upper()
            except Exception:
                text=""
            if code=="MADE_IN_FRANCE" and not re.search(r"FRANCE",text):
                continue
            if code=="INDUCTION" and not re.search(r"(?<![A-Z])I\\s*H(?![A-Z])",text):
                continue
            add(code,label,_rect(xx,yy,xx2-xx,yy2-yy,scale),
                "raster_badge_with_local_ocr","DETECTED")
    # France badge: detect the actual compact FABRIQUÉ EN / FRANCE
    # typography, not a manufacturer address or barcode.
    words=page.get_text("words")
    for word in words:
        if word[4].strip().upper()!="FRANCE":
            continue
        x0,y0,x1,y1=word[:4]
        nearby=" ".join(z[4] for z in words if
            abs(z[1]-y0)<38 and abs(z[0]-x0)<65).upper()
        if not ("FABRIQU" in nearby or "MADE IN" in nearby):
            continue
        bounds=fitz.Rect(x0-12,y0-32,x1+12,y1+8)&page.rect
        pix=page.get_pixmap(clip=bounds,matrix=fitz.Matrix(3,3),
                            colorspace=fitz.csRGB,alpha=False)
        patch=np.frombuffer(pix.samples,dtype=np.uint8).reshape(
            pix.height,pix.width,3)
        phsv=cv2.cvtColor(patch,cv2.COLOR_RGB2HSV)
        blue=cv2.inRange(phsv,np.array((95,65,55),dtype=np.uint8),
                              np.array((140,255,255),dtype=np.uint8))
        if cv2.countNonZero(blue)<8:
            continue
        add("MADE_IN_FRANCE","Made in France 배지",
            [bounds.x0,bounds.y0,bounds.x1,bounds.y1],
            "france_label_blue_flag_raster","DETECTED")

    # IH circular badge: find local 'IH' text, then verify a compact
    # warm-coloured disc. This excludes standalone induction claims.
    for word in words:
        if word[4].strip().upper()!="IH":
            continue
        x0,y0,x1,y1=word[:4]
        side=max(18,(y1-y0)*3.0)
        center=((x0+x1)/2,(y0+y1)/2)
        bounds=fitz.Rect(center[0]-side,center[1]-side,
                         center[0]+side,center[1]+side)&page.rect
        pix=page.get_pixmap(clip=bounds,matrix=fitz.Matrix(3,3),
                            colorspace=fitz.csRGB,alpha=False)
        patch=np.frombuffer(pix.samples,dtype=np.uint8).reshape(
            pix.height,pix.width,3)
        phsv=cv2.cvtColor(patch,cv2.COLOR_RGB2HSV)
        warm=cv2.inRange(phsv,np.array((0,85,55),dtype=np.uint8),
                              np.array((25,255,255),dtype=np.uint8))
        warm |=cv2.inRange(phsv,np.array((170,85,55),dtype=np.uint8),
                                np.array((179,255,255),dtype=np.uint8))
        if cv2.countNonZero(warm)/warm.size<.10:
            continue
        add("INDUCTION","인덕션 아이콘",
            [bounds.x0,bounds.y0,bounds.x1,bounds.y1],
            "ih_label_inside_warm_badge","DETECTED")
    return results


def clean_and_detect(page, filename, earlier, metadata=None):
    """No text-nearby crops survive as logo evidence."""
    qr=[item for item in earlier if item.get("code") in
        {"TEFAL_COMMITMENTS_QR","USE_CARE_QR","UNKNOWN_QR"}
        and item.get("status")=="DETECTED"]
    visuals=image_mark_candidates(page,filename,metadata)
    return qr+visuals
