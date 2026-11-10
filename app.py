import pandas as pd
import streamlit as st
from extractor import extract_pdf, export_zip
from layout import group_paragraphs
from product_identity import check_product_identity
from pdf_overlay import collect_boxes, render_overlay, COLORS
from product_parser import parse_product_pdf
from embedded_reference import load_master
import io
import zipfile
import json
import fitz
import hashlib

st.set_page_config(page_title="아트웍 검수 자동화 — 텍스트 추출", layout="wide")
st.title("아트웍 검수 자동화")
st.caption("아트웍 문구 추출 · 한국어 문구와 문맥상 필요한 영문 표기를 함께 추출합니다.")
files = st.file_uploader("아트웍 PDF 업로드", type=["pdf"], accept_multiple_files=True)
try:
        @st.cache_data(show_spinner=False)
        def load_p0_master():
            return load_master()
        master = load_p0_master()
        st.subheader("P0 · Excel 기준 데이터")
        a, b, c, d = st.columns(4)
        a.metric("문구 수", len(master["phrases"]))
        b.metric("카테고리", len(set(p["category_id"] for p in master["phrases"])))
        c.metric("규칙 그룹", len(master["rules"]))
        d.metric("검토 이슈", len(master["validation_issues"]))
        with st.expander("문구·규칙·변수·데이터 이슈", expanded=False):
            st.write("**Rule Master**")
            st.dataframe(pd.DataFrame(master["rules"]), use_container_width=True, hide_index=True)
            st.write("**Phrase Master**")
            categories = sorted(set(p["category_id"] for p in master["phrases"]))
            selected_category = st.selectbox("TYPE 필터", ["전체"] + categories, key="p0_type")
            phrases = [p for p in master["phrases"] if selected_category == "전체"
                       or p["category_id"] == selected_category]
            st.dataframe(pd.DataFrame(phrases), use_container_width=True, hide_index=True)
            st.write("**Variant Master**")
            st.dataframe(pd.DataFrame(master["variants"]), use_container_width=True, hide_index=True)
            st.write("**검토가 필요한 데이터**")
            st.dataframe(pd.DataFrame(master["validation_issues"]),
                         use_container_width=True, hide_index=True)
        st.download_button(
            "P0 구조화 데이터 JSON", json.dumps(master, ensure_ascii=False, indent=2),
            file_name="artwork_rules_p0.json", mime="application/json"
        )
        st.caption("기준 문구 240개를 코드에서 자동 로딩합니다. D229 영문 오타는 수정했으며, 나머지 원문은 유지했습니다. 승인 상태는 별도 확인 대상입니다.")
except Exception as exc:
    st.error("내장 검수 기준 로딩 실패: " + str(exc))

col1, col2 = st.columns(2)
with col1:
    dpi = st.select_slider("OCR 해상도", options=[200, 300, 350, 400], value=350)
with col2:
    page_limit = st.number_input("파일당 최대 페이지", min_value=1, max_value=100, value=20)
signature = tuple((f.name, hashlib.sha256(f.getvalue()).hexdigest()) for f in (files or []))
if st.session_state.get("qa_signature") != signature:
    st.session_state.pop("qa_result", None)
    st.session_state["qa_signature"] = signature

if st.button("텍스트 추출", type="primary", disabled=not files):
    rows, summaries, errors, identity_checks, product_metadata = [], [], [], [], []
    bar = st.progress(0)
    for index, file in enumerate(files):
        try:
            extracted, info = extract_pdf(file.getvalue(), file.name, dpi=int(dpi), max_pages=int(page_limit))
            rows.extend(extracted)
            summaries.extend(info)
            identity_checks.extend(check_product_identity(file.getvalue(), file.name))
            product_metadata.append(parse_product_pdf(file.getvalue(), file.name))
        except Exception as exc:
            errors.append(f"{file.name}: {exc}")
        bar.progress((index + 1) / len(files))
    st.session_state["qa_result"] = {
        "rows": rows, "summaries": summaries,
        "errors": errors, "identity_checks": identity_checks, "product_metadata": product_metadata,
    }

if st.session_state.get("qa_result"):
    data = st.session_state["qa_result"]
    rows, summaries, errors, identity_checks = (
        data["rows"], data["summaries"], data["errors"], data["identity_checks"]
    )
    product_metadata = data.get("product_metadata", [])
    if errors:
        st.error("\n".join(errors))
    if product_metadata:
        st.subheader("P0 · PDF 제품정보 구조화 (검수 승인 아님)")
        meta_fields = [
            "file", "range_name", "cmmf", "dossier", "product_type_raw",
            "product_type_standard", "size_cm", "capacity_l", "has_lid",
            "lid_material", "manufacturing_country", "induction_compatible",
            "material", "production_agency", "parse_status"
        ]
        meta_table = pd.DataFrame([
            {field: item.get(field) for field in meta_fields}
            for item in product_metadata
        ])
        st.dataframe(meta_table, use_container_width=True, hide_index=True)
        pick_file = st.selectbox("근거 확인할 파일", [m["file"] for m in product_metadata],
                                 key="p0_meta_file")
        detail = next(m for m in product_metadata if m["file"] == pick_file)
        with st.expander("제품정보 원문과 PDF 좌표"):
            evidence_rows = []
            for field, items in detail.get("evidence", {}).items():
                for item in items:
                    evidence_rows.append({"field": field, **item})
            if evidence_rows:
                st.dataframe(pd.DataFrame(evidence_rows), hide_index=True,
                             use_container_width=True)
                selected_evidence = st.selectbox(
                    "위치 미리보기",
                    range(len(evidence_rows)),
                    format_func=lambda i: evidence_rows[i]["field"] + ": "
                    + evidence_rows[i].get("original_text", "")[:55],
                    key="p0_meta_evidence"
                )
                entry = evidence_rows[selected_evidence]
                original_file = next((f for f in files if f.name == pick_file), None)
                if original_file and entry.get("bbox"):
                    with fitz.open(stream=original_file.getvalue(), filetype="pdf") as doc:
                        page = doc[int(entry["page"]) - 1]
                        box = fitz.Rect(*entry["bbox"])
                        crop = fitz.Rect(box.x0 - 25, box.y0 - 20,
                                         box.x1 + 25, box.y1 + 20) & page.rect
                        if not crop.is_empty:
                            st.image(page.get_pixmap(
                                clip=crop, matrix=fitz.Matrix(2, 2),
                                alpha=False
                            ).tobytes("png"), caption=entry["original_text"])
            st.write("확인 필요:", detail["uncertain_fields"])
        st.download_button("제품정보 CSV 다운로드",
                           meta_table.to_csv(index=False).encode("utf-8-sig"),
                           "p0_product_metadata.csv", mime="text/csv")
        st.download_button("제품정보 JSON 다운로드",
                           json.dumps(product_metadata, ensure_ascii=False, indent=2),
                           "p0_product_metadata.json", mime="application/json")

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
        st.subheader("PDF 전체 추출 위치 확인")
        st.caption("문단·원본 줄·영문 제품명의 PDF 추출 좌표를 색깔 박스로 표시합니다. 항목 선택 시 해당 위치를 강조합니다.")
        view_files = sorted(set(
            [r["file"] for r in rows] + [r["file"] for r in identity_checks]
        ))
        if view_files:
            view_file = st.selectbox("파일 선택", view_files, key="overlay_file")
            view_pages = sorted(set(
                [int(r["page"]) for r in rows if r["file"] == view_file] +
                [int(r["page"]) for r in identity_checks if r["file"] == view_file]
            ))
            view_page = st.selectbox("페이지 선택", view_pages, key="overlay_page")
            left, right = st.columns([1, 2.2])
            with left:
                display_mode = st.radio("표시 방식", ["문단별", "원본 줄별"],
                                        horizontal=True, key="overlay_mode")
                show_all = st.checkbox("전체 박스 표시", value=True, key="overlay_all")
                boxes = collect_boxes(
                    rows, grouped, identity_checks, view_file, view_page,
                    group_view=display_mode == "문단별"
                )
                kinds = list(COLORS)
                selected_kinds = st.multiselect(
                    "표시할 유형", kinds, default=kinds, key="overlay_types"
                )
                boxes = [box for box in boxes if box["kind"] in selected_kinds]
                for kind, color in COLORS.items():
                    if kind in selected_kinds:
                        st.markdown(
                            f'<span style="color:{color};font-weight:bold">■</span> {kind}',
                            unsafe_allow_html=True
                        )
                if boxes:
                    item_index = st.selectbox(
                        "추출 항목 선택",
                        range(len(boxes)),
                        format_func=lambda i: (
                            f"{i + 1}. [{boxes[i]['kind']}] "
                            f"{boxes[i]['label'][:75]}"
                        ),
                        key="overlay_item"
                    )
                    picked = boxes[item_index]
                    st.write("**추출 원문**")
                    st.write(picked["label"])
                    st.caption(f"출처: {picked['source']} · 상태: {picked['status']}")
                    st.caption(f"표시 박스: {sum(len(b['rects']) for b in boxes)}개")
                else:
                    item_index = None
                    st.info("선택한 조건에 해당하는 추출 문구가 없습니다.")
            with right:
                uploaded_pdf = next(
                    (item for item in files if item.name == view_file), None
                )
                if uploaded_pdf:
                    image = render_overlay(
                        uploaded_pdf.getvalue(), view_page, boxes,
                        selected=item_index, show_all=show_all
                    )
                    st.image(
                        image,
                        caption=f"{view_file} · {view_page}페이지 (박스는 실제 PDF 텍스트 좌표 기준)",
                        use_container_width=True
                    )
                    st.caption("PDF 전체 페이지를 표시합니다. 선택된 항목은 노란색으로 강조됩니다.")

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
