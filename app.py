import pandas as pd
import streamlit as st
from extractor import extract_pdf, export_zip
from layout import group_paragraphs
from product_identity import check_product_identity
import io
import zipfile
import json
import fitz

st.set_page_config(page_title="아트웍 검수 자동화 — 국문 추출", layout="wide")
st.title("아트웍 검수 자동화")
st.caption("아트웍 문구 추출 · 한국어 문구와 문맥상 필요한 영문 표기를 함께 추출합니다.")
files = st.file_uploader("아트웍 PDF 업로드", type=["pdf"], accept_multiple_files=True)
col1, col2 = st.columns(2)
with col1:
    dpi = st.select_slider("OCR 해상도", options=[200, 300, 350, 400], value=350)
with col2:
    page_limit = st.number_input("파일당 최대 페이지", min_value=1, max_value=100, value=20)
if st.button("텍스트 추출", type="primary", disabled=not files):
    rows, summaries, errors, identity_checks = [], [], [], []
    bar = st.progress(0)
    for index, file in enumerate(files):
        try:
            extracted, info = extract_pdf(file.getvalue(), file.name, dpi=int(dpi), max_pages=int(page_limit))
            rows.extend(extracted)
            summaries.extend(info)
            identity_checks.extend(check_product_identity(file.getvalue(), file.name))
        except Exception as exc:
            errors.append(f"{file.name}: {exc}")
        bar.progress((index + 1) / len(files))
    if errors:
        st.error("\n".join(errors))
    if identity_checks:
        st.subheader("패키지 제품명 ↔ 작업정보 GAMME 교차 검수")
        checks_df = pd.DataFrame(identity_checks)
        overall = (
            checks_df[checks_df["is_primary"]].groupby("file")["status"].apply(
                lambda statuses: "FAIL" if "FAIL" in statuses.values
                else ("OK" if all(status == "OK" for status in statuses) else "REVIEW")
            ).reset_index(name="종합 판정")
        )
        a, b, c = st.columns(3)
        a.metric("OK 제품", int((overall["종합 판정"] == "OK").sum()))
        b.metric("REVIEW 제품", int((overall["종합 판정"] == "REVIEW").sum()))
        c.metric("FAIL 제품", int((overall["종합 판정"] == "FAIL").sum()))
        st.dataframe(overall, use_container_width=True, hide_index=True)
        st.dataframe(
            checks_df[["file", "page", "location", "check", "comparison_reference", "extracted",
                       "status", "context", "x0", "y0", "note"]],
            use_container_width=True, hide_index=True
        )
        st.caption("종합 판정은 PDF 내부의 전면 제품명과 GAMME 철자 일치만 사용합니다. 파일명과 PRODUIT는 참고용이며 종합 판정에 반영되지 않습니다. 주변 광고 문구는 별도의 승인 원문이 있어야 검수할 수 있습니다.")
        with st.expander("PDF 추출 위치 미리보기 · 근거 확인"):
            available = checks_df[checks_df["x0"].notna()]
            if available.empty:
                st.info("좌표가 확인된 문구가 없습니다.")
            else:
                file_options = available["file"].drop_duplicates().tolist()
                selected_file = st.selectbox("PDF 파일", file_options, key="identity_file")
                source_rows = available[available["file"] == selected_file]
                labels = [
                    f"{r['check']} · p.{int(r['page'])} · {r['extracted']}"
                    for _, r in source_rows.iterrows()
                ]
                selected_index = st.selectbox(
                    "확인할 위치", range(len(labels)),
                    format_func=lambda i: labels[i], key="identity_position"
                )
                selected = source_rows.iloc[selected_index]
                uploaded = next((item for item in files if item.name == selected_file), None)
                if uploaded:
                    with fitz.open(stream=uploaded.getvalue(), filetype="pdf") as evidence_pdf:
                        evidence_page = evidence_pdf[int(selected["page"]) - 1]
                        target = fitz.Rect(
                            float(selected["x0"]), float(selected["y0"]),
                            float(selected["x1"]), float(selected["y1"])
                        )
                        margin_x = max(25, target.width * 1.0)
                        margin_y = max(18, target.height * 2.0)
                        crop = fitz.Rect(
                            target.x0 - margin_x, target.y0 - margin_y,
                            target.x1 + margin_x, target.y1 + margin_y
                        ) & evidence_page.rect
                        if not crop.is_empty:
                            pixmap = evidence_page.get_pixmap(
                                clip=crop, matrix=fitz.Matrix(2, 2), alpha=False
                            )
                            st.image(pixmap.tobytes("png"), caption=(
                                f"{selected['location']} · PDF {int(selected['page'])}페이지"
                                f" · x={selected['x0']}, y={selected['y0']}"
                            ))
                            st.write("추출 문구:", selected["extracted"])
                            if selected["context"]:
                                st.write("주변 문구:", selected["context"])
        
    if rows:
        df = pd.DataFrame(rows)
        a, b, c = st.columns(3)
        a.metric("국문 문구 줄", len(rows))
        b.metric("OCR 재판독", sum(x["ocr_lines"] for x in summaries))
        c.metric("확인 필요", int((df["status"] != "원본 추출 정상").sum()))
        grouped = group_paragraphs(rows)
        st.subheader("추출 문구 정리")
        st.caption("일반 문구는 텍스트 블록·줄 좌표를 기준으로 결합하고, 일부 블록이 나뉜 보증문구·AI 표기·코팅 성능 문구도 이어 붙입니다. 곡선 제품명 및 원본 줄별 결과도 보존합니다.")
        groups_df = pd.DataFrame(grouped)
        st.dataframe(
            groups_df[["file", "page", "type", "paragraph", "line_count", "status"]],
            use_container_width=True, hide_index=True
        )
        with st.expander("원본 줄별 추출 결과 보기"):
            st.dataframe(
                df[["file", "page", "korean_text", "status", "pdf_original", "ocr_candidate"]],
                use_container_width=True, hide_index=True
            )
        original_zip = io.BytesIO(export_zip(rows, summaries))
        output_zip = io.BytesIO()
        with zipfile.ZipFile(original_zip) as source, zipfile.ZipFile(output_zip, "w", zipfile.ZIP_DEFLATED) as dest:
            for item in source.infolist():
                dest.writestr(item.filename, source.read(item.filename))
            if identity_checks:
                dest.writestr("product_identity_checks.csv", checks_df.to_csv(index=False).encode("utf-8-sig"))
                dest.writestr("product_identity_checks.json",
                              json.dumps(identity_checks, ensure_ascii=False, indent=2))
            dest.writestr("korean_paragraphs.csv", groups_df.to_csv(index=False).encode("utf-8-sig"))
            dest.writestr("korean_paragraphs.json", json.dumps(grouped, ensure_ascii=False, indent=2))
            dest.writestr("korean_paragraphs.txt", "\n\n".join(
                f"[{g['file']} / p.{g['page']}]\n{g['paragraph']}" for g in grouped
            ))
        st.download_button("텍스트 추출 결과 ZIP 다운로드", output_zip.getvalue(),
                           file_name="artwork_korean_text.zip", mime="application/zip")
    elif not errors and not identity_checks:
        st.warning("추출 가능한 문구가 없습니다. PDF의 텍스트 레이어를 확인하세요.")
