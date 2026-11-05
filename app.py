import streamlit as st
import pandas as pd
from extractor import extract_pdf, export_zip

st.set_page_config(page_title='Artwork Text Extractor MVP',layout='wide')
st.title('아트웍 PDF 텍스트 추출 MVP')
st.caption('원본 PDF 텍스트와 한국어 OCR 결과를 나란히 비교합니다. 외부 AI API 호출 없음.')
files=st.file_uploader('PDF 업로드 (여러 개 가능)',type=['pdf'],accept_multiple_files=True)
c1,c2,c3=st.columns(3)
with c1: mode=st.selectbox('OCR 대상', ['국문 포함 또는 깨진 줄','깨진 줄만','모든 줄'],index=0)
with c2: dpi=st.select_slider('OCR 해상도',options=[150,200,300,400],value=300)
with c3: limit=st.number_input('파일당 최대 페이지',min_value=1,max_value=100,value=20)
mode_map={'국문 포함 또는 깨진 줄':'korean','깨진 줄만':'suspect','모든 줄':'all'}
st.info('원본 텍스트를 자동 수정하지 않습니다. OCR은 검토용 후보로 제공하며 숫자·연도·보증기간은 원본 PDF와 대조하세요.')
if st.button('텍스트 추출 시작',type='primary',disabled=not files):
    rows=[]; summaries=[]; failures=[]
    progress=st.progress(0)
    for i,f in enumerate(files):
        try:
            r,s=extract_pdf(f.getvalue(),f.name,dpi=dpi,mode=mode_map[mode],max_pages=int(limit))
            rows.extend(r);summaries.extend(s)
        except Exception as e: failures.append(f'{f.name}: {e}')
        progress.progress((i+1)/len(files))
    if failures: st.error('\n'.join(failures))
    if rows:
        df=pd.DataFrame(rows)
        st.success(f'{len(summaries)}페이지, {len(rows)}개 텍스트 줄 추출 / OCR 대상 {sum(x["ocr_lines"] for x in summaries)}줄')
        st.dataframe(df,use_container_width=True,hide_index=True)
        st.download_button('CSV · JSON · TXT 결과 ZIP 다운로드',export_zip(rows,summaries),'artwork_text_results.zip','application/zip')
    elif not failures: st.warning('추출된 텍스트가 없습니다. 스캔 이미지 PDF는 추후 전체 페이지 OCR 모드가 필요합니다.')
