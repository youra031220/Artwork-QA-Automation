"""Artwork PDF text extraction: native text + Korean OCR for suspect spans.
No cloud calls. OCR is a *candidate*, never silently replaces source text.
"""
import io, re, json, csv, zipfile
import fitz
from PIL import Image
import pytesseract

HANGUL = re.compile(r'[가-힣]')
SUSPECT = re.compile(r'[\ufffd\u57d1\u57f7\u57fc\u57f5\u57f4\u57fa\u57f1\u57f0\u57f9\u57f2\u57f3\u57f6\u57f8\u57fb\u57fd]')

def _bbox(spans):
    return fitz.Rect(min(s['bbox'][0] for s in spans), min(s['bbox'][1] for s in spans),
                     max(s['bbox'][2] for s in spans), max(s['bbox'][3] for s in spans))

def _ocr_crop(page, rect, dpi=300, rotations=(0,180)):
    pad = max(3, rect.height * 0.35)
    clip = (rect + (-pad,-pad,pad,pad)) & page.rect
    if clip.is_empty:
        return '', None, -1
    pix = page.get_pixmap(clip=clip, matrix=fitz.Matrix(dpi/72,dpi/72), alpha=False)
    im = Image.open(io.BytesIO(pix.tobytes('png'))).convert('RGB')
    best = ('', None, -1)
    for angle in rotations:
        rotated = im.rotate(angle, expand=True) if angle else im
        try:
            data = pytesseract.image_to_data(rotated, lang='kor+eng', config='--psm 6', output_type=pytesseract.Output.DICT)
            items = [(t.strip(), float(c)) for t,c in zip(data['text'],data['conf']) if t.strip() and float(c)>=0]
            txt = ' '.join(t for t,c in items)
            score = (sum(c for t,c in items)/len(items) if items else -1) + min(10, len(HANGUL.findall(txt)))
            if score > best[2]:
                best = (txt, angle, round(score,1))
        except pytesseract.TesseractNotFoundError as exc:
            raise RuntimeError('Tesseract 실행 파일을 설치하고 PATH를 설정하세요.') from exc
        except pytesseract.TesseractError as exc:
            raise RuntimeError('Tesseract 한국어(kor)·영어(eng) 언어팩을 설치하세요.') from exc
    return best

def extract_pdf(pdf_bytes, filename, dpi=300, mode='korean', max_pages=20):
    rows=[]; summary=[]
    doc=fitz.open(stream=pdf_bytes, filetype='pdf')
    if doc.page_count > max_pages:
        raise ValueError(f'페이지 제한 {max_pages}장 초과: {filename}')
    try:
        for pi,page in enumerate(doc):
            data=page.get_text('dict', flags=0)
            line_count=0; ocr_count=0
            for block in data['blocks']:
                for line in block.get('lines',[]):
                    spans=[s for s in line['spans'] if s.get('text','').strip()]
                    if not spans:
                        continue
                    native=''.join(s['text'] for s in spans).strip()
                    if not native:
                        continue
                    line_count+=1
                    has_ko=bool(HANGUL.search(native))
                    bad='\ufffd' in native or bool(SUSPECT.search(native))
                    do_ocr=(mode=='all' or (mode=='korean' and (has_ko or bad)) or (mode=='suspect' and bad))
                    result=''; angle=None; score=None
                    rect=_bbox(spans)
                    if do_ocr:
                        result,angle,score=_ocr_crop(page,rect,dpi=dpi)
                        ocr_count+=1
                    rows.append({'file':filename,'page':pi+1,'native_text':native,
                                 'ocr_text':result,'needs_review':bool(bad or (do_ocr and not result)),
                                 'ocr_rotation':angle,'ocr_score_heuristic':score,
                                 'x0':round(rect.x0,1),'y0':round(rect.y0,1),
                                 'x1':round(rect.x1,1),'y1':round(rect.y1,1)})
            summary.append({'file':filename,'page':pi+1,'native_lines':line_count,'ocr_lines':ocr_count})
    finally:
        doc.close()
    return rows,summary

def export_zip(rows, summaries):
    buf=io.BytesIO()
    with zipfile.ZipFile(buf,'w',compression=zipfile.ZIP_DEFLATED) as z:
        csv_buf=io.StringIO(newline='')
        if rows:
            writer=csv.DictWriter(csv_buf,fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
        z.writestr('extracted_lines.csv', '\ufeff'+csv_buf.getvalue())
        z.writestr('extracted_lines.json',json.dumps(rows,ensure_ascii=False,indent=2))
        text='\n'.join(f"[{r['file']} / p{r['page']}]\n원본: {r['native_text']}\nOCR: {r['ocr_text']}\n" for r in rows)
        z.writestr('comparison.txt',text)
        z.writestr('summary.json',json.dumps(summaries,ensure_ascii=False,indent=2))
    return buf.getvalue()
