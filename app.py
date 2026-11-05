import pandas as pd
import streamlit as st
from extractor import extract_pdf, export_zip

st.set_page_config(page_title="아트웍 검수 자동화 — 국문 추출", layout="wide")
st.title("아트웍 검수 자동화")
st.caption("텍스트 추출 MVP · 아트웍 PDF에서 한국어 문구만 추출하고 원본 텍스트와 OCR 판독을 비교합니다.")
files = st.file_uploader("아트웍 PDF 업로드", type=["pdf"], accept_multiple_files=True)
col1, col2 = st.columns(2)
with col1:
    dpi = st.select_slider("OCR 해상도", options=[200, 300, 350, 400], value=350)
with col2:
    page_limit = st.number_input("파일당 최대 페이지", min_value=1, max_value=100, value=20)
st.info("다국어 문서에서 한국어가 포함된 줄만 표시합니다. 깨진 숫자·공백은 OCR 후보를 확인하세요. 결과는 검수 확정본이 아닙니다.")
if st.button("한국어만 추출", type="primary", disabled=not files):
    rows, summaries, errors = [], [], []
    bar = st.progress(0)
    for index, file in enumerate(files):
        try:
            extracted, info = extract_pdf(file.getvalue(), file.name, dpi=int(dpi), max_pages=int(page_limit))
            rows.extend(extracted)
            summaries.extend(info)
        except Exception as exc:
            errors.append(f"{file.name}: {exc}")
        bar.progress((index + 1) / len(files))
    if errors:
        st.error("\n".join(errors))
    if rows:
        df = pd.DataFrame(rows)
        st.metric("한국어 문구 줄 수", len(rows))
        st.dataframe(df[["file", "page", "korean_ocr", "pdf_original", "needs_review"]],
                     use_container_width=True, hide_index=True)
        review = int(df["needs_review"].sum())
        st.caption(f"확인 필요로 표시된 줄: {review}개. OCR과 원본이 다르면 PDF 화면을 기준으로 확인하세요.")
        st.download_button("국문 추출 결과 ZIP 다운로드", export_zip(rows, summaries),
                           file_name="artwork_korean_text.zip", mime="application/zip")
    elif not errors:
        st.warning("한국어 문구를 발견하지 못했습니다. 이 버전은 PDF 텍스트 레이어에 한국어가 존재해야 합니다.")
