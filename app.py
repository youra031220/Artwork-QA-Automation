import pandas as pd
import streamlit as st
from extractor import extract_pdf, export_zip

st.set_page_config(page_title="아트웍 검수 자동화 — 국문 추출", layout="wide")
st.title("아트웍 검수 자동화")
st.caption("텍스트 추출 MVP · 국문 문구만 추출합니다. PDF의 깨진 문자는 글자 영역만 OCR로 재판독합니다.")
files = st.file_uploader("아트웍 PDF 업로드", type=["pdf"], accept_multiple_files=True)
col1, col2 = st.columns(2)
with col1:
    dpi = st.select_slider("OCR 해상도", options=[200, 300, 350, 400], value=350)
with col2:
    page_limit = st.number_input("파일당 최대 페이지", min_value=1, max_value=100, value=20)
st.info("정상 국문은 PDF 원본 텍스트를 보존하고, 깨진 문자만 OCR 판독 후보로 보완합니다. OCR로 복원한 숫자·문구는 검수 전 원본 화면과 대조하세요.")
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
        a, b, c = st.columns(3)
        a.metric("국문 문구 줄", len(rows))
        b.metric("OCR 재판독", sum(x["ocr_lines"] for x in summaries))
        c.metric("확인 필요", int((df["status"] != "원본 텍스트 정상").sum()))
        st.dataframe(df[["file", "page", "korean_text", "status", "pdf_original", "ocr_candidate"]],
                     use_container_width=True, hide_index=True)
        st.download_button("한국어 결과 ZIP 다운로드", export_zip(rows, summaries),
                           file_name="artwork_korean_text.zip", mime="application/zip")
    elif not errors:
        st.warning("한국어 문구가 없습니다. 현재 버전은 PDF에 한국어 문자 레이어가 있어야 작동합니다.")
