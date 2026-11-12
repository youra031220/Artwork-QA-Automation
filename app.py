import pandas as pd
import streamlit as st
from extractor import extract_pdf, export_zip
from layout import group_paragraphs, ensure_group_coverage
from ocr_review import combine_damaged_coating, combine_damaged_attribution, recover_damaged_warranty
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
from ui_labels import product_labels, display_file_table, readable_ocr_review, reviewer_status
from reviewer_table import reviewer_html_table
from english_pairing import find_english_counterpart
from document_policy import evaluate_document_policy, compare_range_messages
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
signature = tuple((f.name, hashlib.sha256(f.getvalue()).hexdigest()) for f in (files or []))
if st.session_state.get("qa_signature") != signature:
    st.session_state.pop("qa_result", None)
    st.session_state["qa_signature"] = signature

if st.button("문구 검수 시작", type="primary", disabled=not files):
    rows, summaries, errors, identity_checks, product_metadata = [], [], [], [], []
    bar = st.progress(0)
    for index, file in enumerate(files):
        try:
            extracted, info = extract_pdf(file.getvalue(), file.name, dpi=OCR_DPI)
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
        basic_info = [{
            "제품": shown_file(item["file"]),
            "제품유형": item.get("product_type_raw") or "확인 필요",
            "제품코드": item.get("cmmf") or "확인 필요",
            "제조국": item.get("manufacturing_country") or "확인 필요",
            "확인 상태": "검토 필요" if item.get("parse_status") == "REVIEW" else "추출 완료",
        } for item in product_metadata]
        st.dataframe(pd.DataFrame(basic_info), use_container_width=True, hide_index=True)
        st.caption("제품명은 PDF에서 읽은 레인지명·제품유형·크기로 표시합니다. 추출 성공은 최종 검수 승인을 뜻하지 않습니다.")

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
        a.metric("PDF 한국어 원본 줄", len(rows))
        b.metric("업로드한 제품", len({r["file"] for r in rows}))
        c.metric("추가 확인 항목", int((df["status"] != "원본 추출 정상").sum()))
        grouped = group_paragraphs(rows, raw_summaries=summaries)
        # Re-read tightly grouped Korean claims only when native Unicode is
        # visibly corrupted. Preserve every original extracted line in rows.
        grouped = combine_damaged_coating(
            grouped, rows, {f.name: f.getvalue() for f in files}, dpi=OCR_DPI
        )
        grouped = combine_damaged_attribution(
            grouped, {f.name: f.getvalue() for f in files}, dpi=OCR_DPI
        )
        grouped = recover_damaged_warranty(
            grouped, {f.name: f.getvalue() for f in files}, dpi=OCR_DPI
        )
        grouped = ensure_group_coverage(grouped, rows)
        st.subheader("전체 문구 및 검수 결과")
        st.caption("제품별로 모든 한국어 문구를 확인합니다. 여러 줄로 인쇄된 한 문장은 하나로 묶어 표시하며, 확인할 사항은 마지막 열에 표시됩니다.")
        groups_df = pd.DataFrame(grouped)  # Preserve full source in existing ZIP.
        try:
            p1_master = load_p0_master()
            p1_matches = match_phrases(grouped, p1_master)
            all_files = sorted({g["file"] for g in grouped} | {m["file"] for m in product_metadata})
            p1_rules = [
                result for filename in all_files
                for result in evaluate_rules(p1_matches, p1_master, filename,
                    context={"raw_pdf_text": " ".join(
                        evidence.get("text", "")
                        for page in summaries if page.get("file") == filename
                        for evidence in page.get("raw_evidence", []))})
            ]
            p1_rules.extend(evaluate_conditions(product_metadata, p1_matches, summaries))
            for filename in all_files:
                p1_rules.extend(evaluate_bilingual(p1_master, p1_matches, summaries, filename))
            p1_rules.extend(inspect_symbols(summaries, product_metadata))
            for filename in all_files:
                p1_rules.extend(evaluate_document_policy(
                    p1_matches, summaries, product_metadata, filename))
            p1_rules.extend(compare_range_messages(p1_matches, product_metadata))
            p1_summary = summarize_matches(p1_matches, p1_rules)
            # Focus reviewer attention on action items; preserve the full
            # evidence and rule details in the existing report download.
            blocking = [r for r in p1_rules
                        if r.get("status") == "FAIL" and (
                            str(r.get("rule_id", "")).startswith("DOC-") or
                            r.get("rule_id") == "P1-HEAT-CONFLICT")]
            if blocking:
                st.subheader("수정이 필요한 항목")
                for filename in all_files:
                    for finding in blocking:
                        if finding.get("file") == filename:
                            st.error(f"{shown_file(filename)} · "
                                     f"{finding.get('category', '문구')} — "
                                     f"{finding.get('finding', '')}")

            from extractor import numeric_tokens
            shown_by_file = {filename: [] for filename in all_files}
            for match in p1_matches:
                phrase = readable_ocr_review(match)
                has_number = bool(numeric_tokens(phrase) or match.get("numeric_review"))
                is_uncertain = match["status"] in ("OCR_REVIEW", "NUMERIC_MISMATCH",
                    "TEXT_MISMATCH", "AMBIGUOUS_MATCH", "UNREGISTERED")
                # Do not erase the QA risk even if the re-read phrase looks clean.
                issue = ""
                if match["status"] == "OCR_REVIEW":
                    issue = "원본 글자·숫자 확인 필요"
                elif is_uncertain:
                    issue = match.get("reason") or "기준 문구 확인 필요"
                if match.get("ocr_reconstructed") and not issue:
                    issue = "원본 문구 확인 필요"
                shown_by_file[match["file"]].append({
                    "국문 추출 문구": phrase,
                    "영문 추출 문구": find_english_counterpart(match, summaries),
                    "문구 카테고리": match.get("category") or "미분류",
                    "문구 유형": "수치 포함" if has_number else "일반 문구",
                    "대조 결과": ("확인 필요" if is_uncertain else reviewer_status(match["status"])),
                    "기준 국문": match.get("reference_korean", ""),
                    "기준 영문": match.get("reference_english", ""),
                    "확인할 사항": issue,
                })
            for filename in all_files:
                product_rows = shown_by_file[filename]
                st.markdown(f"#### {shown_file(filename)}")
                if product_rows:
                    st.markdown(reviewer_html_table(product_rows), unsafe_allow_html=True)
                    needing_review = sum(bool(row["확인할 사항"]) for row in product_rows)
                    st.caption(f"추출 문구 {len(product_rows)}개 · 확인 필요 {needing_review}개")
                else:
                    st.info("이 제품에서 추출된 문구가 없습니다.")
            st.download_button("문구 검수 보고서 ZIP 다운로드",
                export_p1(p1_matches, p1_rules, p1_summary),
                "artwork_p1_qa_report.zip", mime="application/zip", key="p1_download")
        except Exception as p1_exc:
            st.error("문구 검수 중 오류가 발생했습니다: " + str(p1_exc))
        st.subheader("PDF 문구 위치 확인")
        st.caption("한국어·영문·숫자·제품명 위치를 표시합니다. 문구를 선택하면 원본 위치가 확대됩니다.")
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
                    st.caption("문구는 오른쪽 PDF 확대 이미지에서 직접 확인할 수 있습니다.")


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
