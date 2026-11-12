import pandas as pd
import streamlit as st
from extractor import extract_pdf, export_zip
from layout import group_paragraphs
from ocr_review import combine_damaged_coating
from product_identity import check_product_identity
from pdf_overlay import collect_boxes, render_overlay, render_selected_crop, COLORS
from product_parser import parse_product_pdf
from embedded_reference import load_master
from phrase_matcher import match_phrases
from rule_engine import evaluate_rules, summarize_matches
from condition_engine import evaluate_conditions
from bilingual_engine import evaluate_bilingual
from symbol_detector import inspect_symbols
from qa_report import export_p1
from ui_labels import product_labels, display_file_table, readable_ocr_review
import io
import zipfile
import json
import fitz
import hashlib

st.set_page_config(page_title="아트웍 문구 검수", layout="wide")
st.title("아트웍 문구 검수")
st.caption("PDF를 업로드하면 제품정보와 문구를 확인하고 기준 문구와 다른 부분을 찾아줍니다.")
files = st.file_uploader("아트웍 PDF 업로드", type=["pdf"], accept_multiple_files=True)
master = None
try:
    @st.cache_data(show_spinner=False)
    def load_p0_master():
        return load_master()
    master = load_p0_master()
except Exception as exc:
    st.error("내장 검수 기준 로딩 실패: " + str(exc))

OCR_DPI = 350  # 실무자 화면에서는 숨기는 검증된 기본 OCR 해상도
page_limit = st.number_input("파일당 최대 페이지", min_value=1, max_value=100, value=20)
signature = tuple((f.name, hashlib.sha256(f.getvalue()).hexdigest()) for f in (files or []))
if st.session_state.get("qa_signature") != signature:
    st.session_state.pop("qa_result", None)
    st.session_state["qa_signature"] = signature

if st.button("문구 검수 시작", type="primary", disabled=not files):
    rows, summaries, errors, identity_checks, product_metadata = [], [], [], [], []
    bar = st.progress(0)
    for index, file in enumerate(files):
        try:
            extracted, info = extract_pdf(file.getvalue(), file.name, dpi=OCR_DPI, max_pages=int(page_limit))
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
    reviewer_labels = product_labels(product_metadata, {m["file"] for m in product_metadata} | {r["file"] for r in rows} | {c["file"] for c in identity_checks})
    def shown_file(filename):
        return reviewer_labels.get(filename, "제품정보 확인 필요")
    def shown_records(records):
        return display_file_table(records, reviewer_labels)
    if errors:
        st.error("\n".join(errors))
    if product_metadata:
        st.subheader("제품 기본정보")
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
        basic_info = [{
            "제품": shown_file(item["file"]),
            "제품유형": item.get("product_type_raw") or "확인 필요",
            "제품코드": item.get("cmmf") or "확인 필요",
            "제조국": item.get("manufacturing_country") or "확인 필요",
            "확인 상태": "검토 필요" if item.get("parse_status") == "REVIEW" else "추출 완료",
        } for item in product_metadata]
        st.dataframe(pd.DataFrame(basic_info), use_container_width=True, hide_index=True)
        st.caption("제품명은 PDF에서 읽은 레인지명·제품유형·크기로 표시합니다. 추출 성공은 최종 검수 승인을 뜻하지 않습니다.")
        pick_file = st.selectbox("상세 확인할 제품", [m["file"] for m in product_metadata],
                                 format_func=shown_file, key="p0_meta_file")
        detail = next(m for m in product_metadata if m["file"] == pick_file)
        with st.expander("제품정보 근거·원본 파일명"):
            st.caption(f"원본 파일명: {pick_file}")
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
        st.subheader("포장 제품명 일치 여부")
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
        st.dataframe(pd.DataFrame(shown_records(overall.to_dict("records"))), use_container_width=True, hide_index=True)
        identity_view = shown_records(
            checks_df[["file", "page", "check", "comparison_reference", "extracted",
                       "status", "note"]].to_dict("records")
        )
        st.dataframe(
            pd.DataFrame(identity_view).rename(columns={
                "page": "페이지", "check": "확인 항목",
                "comparison_reference": "비교 기준", "extracted": "PDF 실제 문구",
                "status": "판정", "note": "검토 사유",
            }),
            use_container_width=True, hide_index=True,
        )
        st.caption("포장에 인쇄된 제품명과 PDF 작업정보의 레인지명이 일치하는지 확인합니다. 원본 파일명은 판정에 사용하지 않습니다.")
        with st.expander("PDF 추출 위치 미리보기 · 근거 확인"):
            available = checks_df[checks_df["x0"].notna()]
            if available.empty:
                st.info("좌표가 확인된 문구가 없습니다.")
            else:
                file_options = available["file"].drop_duplicates().tolist()
                selected_file = st.selectbox("제품 선택", file_options, format_func=shown_file, key="identity_file")
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
        grouped = group_paragraphs(rows, raw_summaries=summaries)
        # Re-read tightly grouped Korean claims only when native Unicode is
        # visibly corrupted. Preserve every original extracted line in rows.
        grouped = combine_damaged_coating(
            grouped, rows, {f.name: f.getvalue() for f in files}, dpi=OCR_DPI
        )
        numeric_reviews = [g for g in grouped if g.get("numeric_review")]
        if numeric_reviews:
            st.warning(
                f"수치 확인이 필요한 문단 {len(numeric_reviews)}건이 있습니다. "
                "OCR 후보와 PDF 원본을 비교해야 하며 자동 승인되지 않습니다."
            )
        st.subheader("문구별 검수 결과")
        st.caption("기준 문구와 비교한 결과입니다. 검토 필요 항목은 담당자가 원본과 대조해 주세요.")
        try:
            p1_master = load_p0_master()
            p1_matches = match_phrases(grouped, p1_master)
            all_files = sorted({g["file"] for g in grouped} | {m["file"] for m in product_metadata})
            p1_rules = [
                result
                for filename in all_files
                for result in evaluate_rules(
                    p1_matches, p1_master, filename,
                    context={"raw_pdf_text": " ".join(
                        evidence.get("text", "")
                        for page in summaries if page.get("file") == filename
                        for evidence in page.get("raw_evidence", [])
                    )},
                )
            ]
            p1_rules.extend(evaluate_conditions(product_metadata, p1_matches, summaries))
            for filename in all_files:
                p1_rules.extend(evaluate_bilingual(
                    p1_master, p1_matches, summaries, filename
                ))
            p1_rules.extend(inspect_symbols(summaries, product_metadata))
            p1_summary = summarize_matches(p1_matches, p1_rules)
            if p1_summary:
                st.dataframe(pd.DataFrame(shown_records(p1_summary)).rename(columns={"extracted_count": "추출 문구", "matched_count": "기준 일치", "unregistered_count": "미등록", "ocr_review_count": "글자·숫자 확인", "rule_ok": "조건 충족", "rule_review": "검토 필요", "rule_fail": "오류", "overall": "종합 결과"}), use_container_width=True, hide_index=True)
            tab_matches, tab_rules, tab_unknown, tab_evidence = st.tabs(
                ["정답 대조", "카테고리별 규칙", "미등록 문구", "근거·상세정보"]
            )
            # Keep internal IDs and coordinate arrays in the evidence panel;
            # the primary tables contain only actionable reviewer information.
            match_columns = {
                "제품": "제품", "page": "페이지", "extracted": "PDF 추출 문구",
                "status": "대조 결과", "category": "카테고리",
                "reference_korean": "기준 국문", "reference_english": "기준 영문",
                "differences": "차이점", "reason": "검토 사유",
            }
            rule_columns = {
                "category": "카테고리", "rule_type": "검수 조건",
                "found_occurrences": "발견 횟수",
                "distinct_variants": "서로 다른 문구 수",
                "status": "판정", "finding": "검수 결과",
            }
            def reviewer_table(records, columns):
                display = shown_records(records)
                for entry, source in zip(display, records):
                    if "extracted" in entry:
                        entry["extracted"] = readable_ocr_review(source)
                view = pd.DataFrame(display)
                return view.reindex(columns=list(columns)).rename(columns=columns)

            with tab_matches:
                st.caption("실제 PDF 문구와 기준 문구를 비교합니다. 상세 좌표와 원본 파일명은 '근거·상세정보'에서 확인할 수 있습니다.")
                st.dataframe(
                    reviewer_table(p1_matches, match_columns),
                    use_container_width=True, hide_index=True,
                )
            with tab_rules:
                if p1_rules:
                    rule_file = st.selectbox(
                        "검수할 제품", all_files, format_func=shown_file, key="p1_rule_file"
                    )
                    relevant_rules = [
                        r for r in p1_rules if r["file"] == rule_file
                    ]
                    st.dataframe(
                        reviewer_table(relevant_rules, rule_columns),
                        use_container_width=True, hide_index=True,
                    )
                    st.caption("발견 횟수는 기준과 확정 매칭된 횟수이며, 서로 다른 문구 수는 중복 인쇄를 제외한 유형 수입니다. 조건 미확정은 REVIEW로 남습니다.")
            with tab_unknown:
                unknown = [
                    m for m in p1_matches if m["status"] == "UNREGISTERED"
                ]
                st.metric("정답 데이터 미등록 문구", len(unknown))
                if unknown:
                    st.dataframe(
                        reviewer_table(unknown, {
                            "제품": "제품", "page": "페이지",
                            "extracted": "미등록 국문",
                            "reason": "검토 사유",
                        }),
                        use_container_width=True, hide_index=True,
                    )
                else:
                    st.info("미등록 문구 없음. OCR 및 문장 연결 오류 여부는 별도 확인하세요.")
            with tab_evidence:
                st.caption("기본 목록에서 생략한 내부 ID·원장 행 번호·OCR 후보·PDF 좌표를 선택한 문구에 대해서만 보여줍니다.")
                if p1_matches:
                    pick = st.selectbox(
                        "상세 확인할 문구", range(len(p1_matches)),
                        format_func=lambda j: (
                            f'{shown_file(p1_matches[j]["file"])} · p.{p1_matches[j]["page"]}'
                            f' · {p1_matches[j]["status"]} · {p1_matches[j]["extracted"][:65]}'
                        ), key="p1_evidence_item"
                    )
                    entry = p1_matches[pick]
                    st.caption("원본 파일명: " + entry["file"])
                    st.write("**검수 화면 문구:**", readable_ocr_review(entry))
                    if entry.get("original_extracted") != entry["extracted"]:
                        st.write("**PDF 원본 추출 (수정 전):**", entry["original_extracted"])
                    elif entry.get("status") == "OCR_REVIEW":
                        st.write("**PDF 원본 추출 (OCR 미확정):**", entry["extracted"])
                    st.write("**기준 국문:**", entry["reference_korean"] or "(미등록)")
                    st.write("**기준 영문:**", entry["reference_english"] or "(미등록)")
                    st.write("**판정 근거:**", entry["reason"])
                    if entry.get("differences"):
                        st.write("**차이점:**", entry["differences"])
                    rectangles = [
                        pos["bbox"] for pos in entry.get("source_coordinates", [])
                        if pos.get("bbox")
                    ]
                    selected_file = next(
                        (item for item in files if item.name == entry["file"]), None
                    )
                    if selected_file and rectangles:
                        crop = render_selected_crop(
                            selected_file.getvalue(), int(entry["page"]),
                            {"rects": rectangles, "label": entry["extracted"],
                             "status": entry["status"]}
                        )
                        if crop is not None:
                            st.image(
                                crop, caption="PDF 원본 근거 (강조된 추출 위치)",
                                use_container_width=True,
                            )
                    elif not rectangles:
                        st.info("이 문구의 정확한 PDF 좌표가 없습니다. 원본 파일에서 직접 확인하세요.")
                    with st.expander("기술 상세정보 · OCR 및 원장 추적", expanded=False):
                        detail_fields = {
                            "line_indices": "원본 줄 인덱스",
                            "source_coordinates": "PDF 근거 좌표",
                            "ocr_candidates": "OCR 후보",
                            "phrase_id": "정답 문구 ID",
                            "rule_id": "규칙 ID",
                            "source_row": "원장 행 번호",
                            "candidates": "추가 매칭 후보",
                            "approval_status": "정답 데이터 승인 상태",
                        }
                        for field, title in detail_fields.items():
                            value = entry.get(field)
                            if value not in (None, "", []):
                                st.write(f"**{title}:**", value)
                else:
                    st.info("상세 확인할 추출 문구가 없습니다.")
            st.download_button(
                "문구 검수 보고서 ZIP 다운로드",
                export_p1(p1_matches, p1_rules, p1_summary),
                "artwork_p1_qa_report.zip", mime="application/zip",
                key="p1_download",
            )
        except Exception as p1_exc:
            st.error("기준 문구 검수 중 오류가 발생했습니다. 추출 문구는 아래에서 확인할 수 있습니다: " + str(p1_exc))

        st.subheader("PDF에서 찾은 전체 문구")
        st.caption("PDF에서 인식한 전체 문구입니다. 기준에 등록되지 않은 문구도 제외하지 않습니다.")
        groups_df = pd.DataFrame(grouped)
        group_view = pd.DataFrame(shown_records(grouped)).rename(columns={
            "page": "페이지", "type": "문구 유형",
            "paragraph": "추출 문구", "status": "확인 상태",
        })
        st.dataframe(group_view[["제품", "페이지", "문구 유형", "추출 문구", "확인 상태"]],
                     use_container_width=True, hide_index=True)
        with st.expander("원본 줄별 추출 결과 보기"):
            raw_view = pd.DataFrame(shown_records(rows)).rename(columns={
                "page": "페이지", "korean_text": "원본 줄",
                "status": "확인 상태", "ocr_candidate": "다시 읽은 문구",
            })
            st.dataframe(raw_view[["제품", "페이지", "원본 줄", "확인 상태", "다시 읽은 문구"]],
                         use_container_width=True, hide_index=True)
        st.subheader("PDF 문구 위치 확인")
        st.caption("문단·원본 줄·영문 제품명의 PDF 추출 좌표를 색깔 박스로 표시합니다. 항목 선택 시 해당 위치를 강조합니다.")
        view_files = sorted(set(
            [r["file"] for r in rows] + [r["file"] for r in identity_checks]
        ))
        if view_files:
            view_file = st.selectbox("제품 선택", view_files, format_func=shown_file, key="overlay_file")
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
                    group_view=display_mode == "문단별",
                    raw_summaries=summaries,
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
                            f"{i + 1}. [{boxes[i].get('display_label', boxes[i]['kind'])}] "
                            f"{boxes[i]['label'][:75]}"
                        ),
                        key="overlay_item"
                    )
                    picked = boxes[item_index]
                    st.write("**원본 추출 문구**")
                    st.write(picked.get("original_label", picked["label"]))
                    if picked.get("context_candidates"):
                        st.write("**주변 PDF 문구 (문장 연결 미확정)**")
                        st.write(" / ".join(picked["context_candidates"]))
                        st.caption("주변 실제 PDF 객체이며, 숫자와 문장을 확정 결합하거나 승인한 결과가 아닙니다.")
                    st.caption(f"출처: {picked['source']} · 상태: {picked['status']}")
                    if picked.get("display_label", "").startswith("수치 대조"):
                        st.error("수치 대조 필요: 원본 PDF의 숫자·단위와 OCR 후보를 확인하세요.")
                    elif picked.get("display_label", "").startswith("수치 포함"):
                        st.info("수치 포함 문구입니다. 숫자와 단위를 PDF 원본과 대조하세요. 오류로 판정된 상태는 아닙니다.")
                    if picked["source"] == "추출 문단":
                        related = next((
                            g for g in grouped
                            if g["file"] == view_file
                            and int(g["page"]) == int(view_page)
                            and g["paragraph"] == picked.get("original_label", picked["label"])
                        ), None)
                        if related and related.get("warnings"):
                            st.write("검토 사유:", related["warnings"])
                            st.info("읽기용 OCR 후보입니다. 승인된 원문이 아니므로 PDF와 대조하세요.")
                            st.write("OCR 후보:", related.get("ocr_candidates", []))
                        if related and related.get("numeric_peer_evidence"):
                            st.write("인접 숫자 객체 후보 (문장 연결 미확정):",
                                     related["numeric_peer_evidence"])
                        if related and related.get("type") == "문장 연결 확인":
                            st.warning("이 항목은 단어만 추출되어 숫자와 후속 문구를 자동 연결하지 못했습니다. 아래 확대 PDF에서 함께 확인하세요.")
                    if picked["source"] == "원본 줄" and picked.get("line_index") is not None:
                        original_line = rows[picked["line_index"]]
                        if original_line.get("ocr_candidate"):
                            st.info("읽기용 OCR 후보 (원본을 대체하지 않음):")
                            st.write(original_line["ocr_candidate"])
                            st.caption("PDF 원문과 후보가 다르면 사람이 원본을 확인해야 합니다.")
                    st.caption(f"표시 박스: {sum(len(b['rects']) for b in boxes)}개")
                else:
                    item_index = None
                    st.info("선택한 조건에 해당하는 추출 문구가 없습니다.")
            with right:
                uploaded_pdf = next(
                    (item for item in files if item.name == view_file), None
                )
                if uploaded_pdf:
                    if item_index is not None:
                        st.markdown("**선택한 문구 확대 보기**")
                        zoomed = render_selected_crop(
                            uploaded_pdf.getvalue(), view_page, boxes[item_index]
                        )
                        if zoomed is not None:
                            st.image(
                                zoomed,
                                caption="선택 문구의 실제 PDF 영역 · 노란 테두리는 근거 위치",
                                use_container_width=True,
                            )
                        else:
                            st.info("선택한 문구의 좌표가 없어 확대 미리보기를 표시할 수 없습니다.")
                    st.markdown("**전체 PDF 위치 확인**")
                    image = render_overlay(
                        uploaded_pdf.getvalue(), view_page, boxes,
                        selected=item_index, show_all=show_all
                    )
                    st.image(
                        image,
                        caption=f"{shown_file(view_file)} · {view_page}페이지 (원본 PDF 근거 위치)",
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

if master is not None:
    with st.expander("기준 데이터·관리자 정보 (문구·규칙·변수)", expanded=False):
        st.subheader("기준 문구·검수 규칙 관리")
        a, b, c, d = st.columns(4)
        a.metric("문구 수", len(master["phrases"]))
        b.metric("카테고리", len(set(p["category_id"] for p in master["phrases"])))
        c.metric("규칙 그룹", len(master["rules"]))
        d.metric("검토 이슈", len(master["validation_issues"]))
        st.markdown("**문구·규칙·변수·데이터 이슈**")
        with st.container(border=True):
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
            "기준 데이터 JSON", json.dumps(master, ensure_ascii=False, indent=2),
            file_name="artwork_rules_p0.json", mime="application/json"
        )
        st.caption("기준 문구 240개를 코드에서 자동 로딩합니다. D229 영문 오타는 수정했으며, 나머지 원문은 유지했습니다. 승인 상태는 별도 확인 대상입니다.")
