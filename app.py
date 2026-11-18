import pandas as pd
import streamlit as st
import streamlit.components.v1 as components
from extractor import extract_pdf, export_zip
from layout import group_paragraphs, ensure_group_coverage, join_wrapped_storage_sentences, split_bullet_clauses
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
from document_policy import (evaluate_document_policy, compare_range_messages,
                             evaluate_bilingual_values, evaluate_recycling_exclusivity)
from policy_ui import render_policy_status
from numeric_citation import repair_korean_world_years
import io
import zipfile
import json
import fitz
import hashlib
import re
from difflib import SequenceMatcher

HOLE = "\ufffd"


def display_phrase(match):
    """Best printed text for the QA table. NEVER a status placeholder.

    Order: the reconstructed extracted text (OCR filled only verified glyph
    holes), then the native original. Remaining unreadable glyphs are shown
    as '□' at their exact position so the reviewer sees the real sentence.
    """
    for key in ("extracted", "original_extracted"):
        value = str(match.get(key) or "").strip()
        if value:
            return value.replace(HOLE, "□")
    return ""


st.set_page_config(page_title="아트웍 문구 검수", layout="wide")
st.title("아트웍 문구 검수")
st.caption("PDF를 업로드하면 제품정보와 문구를 확인하고 기준 문구와 다른 부분을 찾아줍니다.")
files = st.file_uploader("아트웍 PDF 업로드", type=["pdf"], accept_multiple_files=True)
# Results are keyed by file name, so the same PDF uploaded twice would be
# counted twice (e.g. two recycling sentences). Keep one copy per file name.
if files:
    _unique, _dropped = {}, []
    for _file in files:
        if _file.name in _unique:
            _dropped.append(_file.name)
        else:
            _unique[_file.name] = _file
    if _dropped:
        st.warning("같은 이름의 PDF가 중복으로 올라와 한 번만 검수합니다: "
                   + ", ".join(sorted(set(_dropped))))
    files = list(_unique.values())
master = None
try:
    @st.cache_data(show_spinner=False)
    def load_p0_master():
        return load_master()
    master = load_p0_master()
except Exception as exc:
    st.error("내장 검수 기준 로딩 실패: " + str(exc))

OCR_DPI = 350  # 실무자 화면에서는 숨기는 검증된 기본 OCR 해상도
@st.cache_data(show_spinner=False, max_entries=12)
def _cached_extract_content(pdf_bytes, dpi):
    # Keyed on PDF CONTENT only: the same artwork uploaded under another
    # file name is not OCR'd again.
    return extract_pdf(pdf_bytes, "__pdf__", dpi=dpi)


@st.cache_data(show_spinner=False, max_entries=32)
def cached_phrase_crops(pdf_bytes, requests):
    from phrase_crop import crop_data_uris
    return crop_data_uris(pdf_bytes, requests)


def required_overview(required_by_file, shown_file):
    """필수 문구 점검 요약표: 점검 항목 = 행, 제품 = 열, 칸 = O / X / 오류 / △."""
    symbols = {"OK": "O", "MISSING": "X", "FAIL": "오류", "REVIEW": "△"}
    columns, rows = [], {}
    for filename, checks in required_by_file.items():
        name = shown_file(filename)
        while name in columns:          # two uploads with the same product label
            name += " "
        columns.append(name)
        for check in checks:
            mark = symbols.get(check["status"], "△")
            if mark == "X" and check.get("category") in ("사용방법 QR", "품질 보증 / 사용법"):
                mark = "X*"
            rows.setdefault(check["label"], {})[name] = mark
    table = pd.DataFrame.from_dict(rows, orient="index")[columns]
    table.index.name = "점검 항목"
    colors = {"O": "color:#1a7f37;font-weight:600", "X": "color:#cf222e;font-weight:600",
              "X*": "color:#9a6700", "오류": "color:#cf222e;font-weight:700;background:#ffebe9",
              "△": "color:#9a6700;font-weight:600"}
    styled = table.style.map(lambda value: colors.get(value, ""))
    return styled.set_properties(**{"text-align": "center"})


@st.cache_data(show_spinner=False, max_entries=6)
def cached_zoom_view(pdf_bytes, page, boxes_json, selected, show_all, caption):
    """High-resolution full page with boxes, as a click-to-zoom viewer."""
    import importlib, inspect
    import pdf_overlay
    import zoom_view
    if getattr(zoom_view, "VERSION", 1) < 4:
        importlib.reload(zoom_view)
    ZOOM_SIDE, zoom_html, viewer_height = zoom_view.ZOOM_SIDE, zoom_view.zoom_html, zoom_view.viewer_height
    # Streamlit Cloud keeps imported modules across a git update; pick up a
    # newer pdf_overlay without needing a manual reboot.
    if "max_side" not in inspect.signature(pdf_overlay.render_overlay).parameters:
        importlib.reload(pdf_overlay)
    image = pdf_overlay.render_overlay(pdf_bytes, page, json.loads(boxes_json),
                           selected=selected, show_all=show_all, max_side=ZOOM_SIDE)
    return zoom_html(image, caption), viewer_height(image.width, image.height)


def cached_extract_pdf(pdf_bytes, filename, dpi):
    import copy
    rows, info = copy.deepcopy(_cached_extract_content(pdf_bytes, dpi))
    for item in rows + info:
        item["file"] = filename
    return rows, info

signature = tuple((f.name, hashlib.sha256(f.getvalue()).hexdigest()) for f in (files or []))
if st.session_state.get("qa_signature") != signature:
    st.session_state.pop("qa_result", None)
    st.session_state["qa_signature"] = signature

if st.button("문구 검수 시작", type="primary", disabled=not files):
    rows, summaries, errors, identity_checks, product_metadata = [], [], [], [], []
    bar = st.progress(0, text="검수 준비 중")
    for index, file in enumerate(files):
        filename = file.name
        with st.status(f"{filename} · PDF 검수 진행 중", expanded=True) as run_status:
            try:
                st.write("1/3 PDF 문구 추출 및 OCR 처리 중")
                extracted, info = cached_extract_pdf(file.getvalue(), filename, OCR_DPI)
                rows.extend(extracted)
                summaries.extend(info)
                st.write("2/3 제품 식별 정보 확인 중")
                identity_checks.extend(check_product_identity(file.getvalue(), filename))
                st.write("3/3 제품 정보 분석 중")
                product_metadata.append(parse_product_pdf(file.getvalue(), filename))
                run_status.update(label=f"{filename} · 추출 완료", state="complete")
            except Exception as exc:
                errors.append(f"{filename}: {type(exc).__name__}: {exc}")
                run_status.update(label=f"{filename} · 처리 실패", state="error")
                st.error(errors[-1])
        bar.progress((index + 1) / len(files), text=f"{index + 1}/{len(files)} PDF 처리 완료")
    st.session_state["qa_result"] = {
        "rows": rows, "summaries": summaries,
        "errors": errors, "identity_checks": identity_checks, "product_metadata": product_metadata,
    }
    if rows:
        st.success(f"PDF 추출 완료 · 한국어 문구 {len(rows)}줄 · 결과표 생성 중")
    elif errors:
        st.error("PDF 추출 실패 · 위 오류 메시지를 확인하세요")
    else:
        st.warning("PDF 처리 완료 · 추출된 한국어 문구가 없습니다.")

timing_renderer = None
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
    for page_info in summaries:
        for warning in page_info.get("ocr_warnings") or []:
            st.warning(f"{shown_file(page_info['file'])} p.{page_info['page']} · {warning}")
    # 처리 시간 · OCR 호출 기록: reference only, rendered at the very bottom.
    def render_timing():
        with st.expander("처리 시간 · OCR 호출 기록", expanded=False):
            timing_rows = []
            for page_info in summaries:
                stats = page_info.get("ocr_stats") or {}
                batch = stats.get("batch") or {}
                image_batch = stats.get("table_reread") or {}
                fallback = stats.get("fallback") or {}
                badge = stats.get("badge") or {}
                line_reread = stats.get("line_reread") or {}
                timing_rows.append({
                    "제품": shown_file(page_info["file"]), "페이지": page_info["page"],
                    "제외한 한글표시사항 표": stats.get("label_tables", 0),
                    "손상 문구 줄": stats.get("damaged_lines", 0),
                    "이미지·벡터 후보 영역": stats.get("regions", 0),
                    "이미지·벡터에서 찾은 한국어 행": stats.get("region_rows", 0),
                    "OCR 프로세스 호출": (batch.get("calls", 0) + image_batch.get("calls", 0)
                                        + badge.get("calls", 0) + line_reread.get("calls", 0)
                                        + fallback.get("calls", 0)),
                    "일괄 OCR(손상 문구+이미지·벡터) 초": batch.get("seconds", 0),
                    "한국어 표 영역 단독 재판독 초": image_batch.get("seconds", 0),
                    "이미지 배지 OCR 초": badge.get("seconds", 0),
                    "표 행 재판독 초": line_reread.get("seconds", 0),
                    "개별 재판독 호출": fallback.get("calls", 0),
                    "개별 재판독 초": fallback.get("seconds", 0),
                    "렌더링 초": stats.get("render_seconds", 0),
                    "PDF 추출 전체 초": stats.get("total_seconds", 0),
                })
            if timing_rows:
                st.dataframe(pd.DataFrame(timing_rows), use_container_width=True, hide_index=True)
            st.caption("OCR 해상도 350 DPI. 같은 PDF 내용을 다시 검수하면 저장된 추출 결과를 재사용합니다. "
                       "한글표시사항(제조자·원산지·수입원·주소·품질보증기간·주의사항 등 법정 표시) 표는 "
                       "표 구조로 자동 인식해 문구 검수와 OCR 대상에서 제외합니다.")
    timing_renderer = render_timing
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

    # 포장 제품명 일치 여부(OK/REVIEW/FAIL) 화면은 제거. 근거 데이터는 ZIP과
    # PDF 위치 확인 화면(제품명 박스)에서만 사용한다.
    checks_df = pd.DataFrame(identity_checks) if identity_checks else None

    if rows:
        df = pd.DataFrame(rows)
        st.metric("업로드한 제품", len({r["file"] for r in rows}))
        # Per-product 추출 문구 / 확인 필요 문구 counts, filled once the result
        # table is built (same numbers as "추출 문구 N개 · 확인 필요 N개").
        count_slot = st.empty()
        mark_messages_by_file = {}   # 마크 체크리스트, also shown beside the PDF view
        grouped = group_paragraphs(rows, raw_summaries=summaries)
        # OCR has already been performed once on damaged native text by
        # extract_pdf(). Do not run four more PDF raster OCR passes here.
        # Preserve uncertain glyphs for manual verification instead.
        grouped = ensure_group_coverage(grouped, rows)
        grouped = split_bullet_clauses(join_wrapped_storage_sentences(grouped))
        st.subheader("전체 문구 및 검수 결과")
        st.caption("제품별로 모든 한국어 문구를 확인합니다. 여러 줄로 인쇄된 한 문장은 하나로 묶어 표시합니다. 마지막 열은 문구가 인쇄된 PDF 원본 부분이며, 빨간 테두리가 추출 위치입니다.")
        groups_df = pd.DataFrame(grouped)  # Preserve full source in existing ZIP.
        try:
            p1_master = load_p0_master()
            # Reconcile OCR before matching, not only while rendering the table.
            # Keep original PDF evidence and mark only genuinely corroborated
            # readings as eligible for an exact reference comparison.
            # OCR is applied per physical line inside extract_pdf (only the
            # unreadable glyph holes are filled, native letters are kept),
            # then lines are joined into sentences. No whole-sentence OCR
            # substitution happens here.
            matched_groups = join_wrapped_storage_sentences(grouped)
            p1_matches = match_phrases(matched_groups, p1_master)
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
                p1_rules.extend(evaluate_bilingual_values(
                    p1_matches, summaries, filename))
                p1_rules.extend(evaluate_recycling_exclusivity(
                    p1_matches, product_metadata, filename))
            p1_rules.extend(compare_range_messages(p1_matches, product_metadata))
            # Text-only visual checklist. This does not run any image
            # recognition and never asserts that a logo is present/absent.
            # 필수 문구 점검: 엑셀 원장 '필수 조건 여부' 기준 발견 / 발견 실패 / 오류.
            import importlib
            import required_check
            if getattr(required_check, "VERSION", 1) < 2:
                importlib.reload(required_check)
            check_required = required_check.check_file
            st.subheader("필수 문구 점검")
            st.caption("엑셀 원장의 '필수 조건 여부' 기준입니다. 원장 문장이 PDF에서 읽은 한국어 문구에 있으면 발견, "
                       "없으면 발견 실패, 하나만 있어야 하는데 2개 이상이면 오류로 표시합니다. "
                       "조건부 필수(재활용·세계 1위)는 아래 마크 체크리스트에서 확인합니다.")
            required_by_file = {
                filename: check_required([m for m in p1_matches if m.get("file") == filename], p1_master)
                for filename in all_files}
            if st.checkbox("한눈에 보기", key="required_overview",
                           help="점검 항목을 행, 제품을 열로 놓고 O/X로 요약합니다."):
                st.dataframe(required_overview(required_by_file, shown_file),
                             use_container_width=True)
                st.caption("O 발견 · X 발견 실패 · 오류 하나만 있어야 하는데 2개 이상 · △ 원장 문구는 없지만 비슷하거나 원장에 없는 문구가 있어 확인 필요(예: 원장 미등록 키 메세지). "
                           "X* = 슬리브 제품만 필수인 항목(사용방법 QR·품질보증)이라 박스 포장이면 정상입니다. "
                           "어떤 문구가 발견됐는지는 체크를 끄면 제품별로 볼 수 있습니다.")
            else:
                for filename in all_files:
                    checks = required_by_file[filename]
                    bad = sum(c["status"] in ("MISSING", "FAIL") for c in checks)
                    review = sum(c["status"] == "REVIEW" for c in checks)
                    title = shown_file(filename) + (
                        f" · 발견 실패·오류 {bad}건" if bad else "") + (
                        f" · 확인 필요 {review}건" if review else "") + (
                        "" if bad or review else " · 모두 발견")
                    with st.expander(title, expanded=bool(bad or review)):
                        for check in checks:
                            st.write(check["message"])
            st.subheader("마크·QR 확인 필요 체크리스트")
            st.caption("엑셀 원장·회의 기준으로 확인할 마크를 안내합니다. 이미지 자동 검출은 하지 않으며, 실제 존재 여부는 PDF를 보고 확인하세요.")
            for filename in all_files:
                raw = " ".join(
                    str(e.get("text", ""))
                    for page in summaries if page.get("file") == filename
                    for e in page.get("raw_evidence", []))
                phrases = " ".join(
                    str(m.get(k, "")) for m in p1_matches
                    if m.get("file") == filename
                    for k in ("extracted", "reference_korean", "reference_english"))
                # Only extracted material can trigger a visual checklist.
                # Reference phrases are intentionally excluded.
                observed = raw + " " + " ".join(
                    str(m.get("extracted", "")) for m in p1_matches
                    if m.get("file") == filename)
                meta = next((m for m in product_metadata if m.get("file")==filename), {})
                country = str(meta.get("manufacturing_country", "")).upper()
                messages = []
                import re
                # Include confirmed heat-source category matches as evidence.
                # Never use reference-only text to infer a PDF claim.
                heat_matches = [m for m in p1_matches
                    if m.get("file")==filename and
                    ("열원" in str(m.get("category","")) or
                     "INDUCTION" in str(m.get("extracted","")).upper())]
                observed += " " + " ".join(
                    str(m.get("extracted","")) for m in heat_matches)
                no_induction = bool(re.search(
                    r"ALL\s+HOBS\s+EXCEPT\s+INDUCTION|인덕션\s*사용\s*불가", observed,re.I))
                yes_induction = bool(re.search(
                    r"ALL\s+HOBS\s*\+\s*INDUCTION|인덕션\s*포함\s*모든\s*열원", observed,re.I))
                if yes_induction and no_induction:
                    messages.append("⚠️ 인덕션 사용 가능·불가 문구가 함께 발견됨 — 문구 충돌 확인")
                elif no_induction:
                    messages.append("✓ 인덕션 사용 불가 문구 확인 — IH 인덕션 마크는 필요하지 않음")
                elif yes_induction:
                    messages.append("□ 인덕션 사용 가능 문구 확인 — 원형 IH 인덕션 마크가 실제 있는지 확인 필요")
                else:
                    messages.append("□ 열원 문구 확인 불가 — 인덕션 적용 여부부터 확인")
                if country=="FRANCE":
                    messages.append("□ 제조국 FRANCE — FABRIQUÉ EN FRANCE / Made in France 배지 확인 필요")
                elif country:
                    messages.append("✓ 제조국 "+country+" — Made in France 배지 필수 대상 아님")
                else:
                    messages.append("□ 제조국 미확인 — Made in France 배지 적용 여부 확인")
                # 재활용 문구 ↔ 유리뚜껑 조건 (원장 P200/P201). Lid evidence is
                # only text read from this PDF plus the product ticket.
                from recycling_rule import judge as judge_recycling
                lid_source = observed + " " + str(meta.get("product_type_raw", ""))
                recycling = judge_recycling(
                    lid_source, [m for m in p1_matches if m.get("file") == filename])
                messages.append(recycling["message"])
                if recycling["status"] == "FAIL":
                    p1_rules.append({"file": filename, "rule_id": "DOC-RECYCLING-LID",
                                     "status": "FAIL", "category": "재활용 가능",
                                     "finding": recycling["finding"]})
                # Each item states what was FOUND in the PDF text, then the
                # mark/QR check that a person still has to do.
                world_ko = bool(re.search(r"세계\s*판매\s*1\s*위|에디션[^/]{0,40}기준", observed))
                world_en = bool(re.search(
                    r"world\s*N[°ºo]?\s*1|N[°ºo]\s*1\s+in\s+cookware|"
                    r"Euromonitor[^/]{0,80}edition", observed, re.I))
                if world_ko and world_en:
                    messages.append("□ 세계 1위 각주 국·영문 문구 발견 — Tefal WORLD N°1 로고 확인 필요")
                elif world_ko or world_en:
                    found, missing = ("국문", "영문") if world_ko else ("영문", "국문")
                    messages.append(f"⚠️ 세계 1위 각주 {found} 문구만 발견 ({missing} 미발견) — "
                                    f"WORLD N°1 로고와 {missing} 각주 확인 필요")
                else:
                    messages.append("— 세계 1위 각주 문구 미발견 — WORLD N°1 로고 유무 확인 필요 "
                                    "(로고가 있으면 각주 누락)")
                usage_qr = bool(re.search(r"QR\s*코드|사용\s*방법[^.]{0,30}QR|QR[^.]{0,30}사용\s*방법", observed))
                if usage_qr:
                    messages.append("□ 사용방법 QR 안내 문구 발견 — QR 확인 필요")
                else:
                    messages.append("— 사용방법 QR 안내 문구 미발견 — 슬리브 적용 제품인지 확인 필요 "
                                    "(적용 제품이면 QR·안내 문구 누락)")
                commitments = bool(re.search(
                    r"COMMITMENTS|ENGAGEMENTS|COMPROMISOS|ZOBOWI[ĄA]ZANIA|TAAHH[ÜU]TLER",
                    observed, re.I))
                if commitments:
                    messages.append("□ Tefal Commitments 문구 발견 (COMMITMENTS / ENGAGEMENTS) — QR·로고 확인 필요")
                else:
                    messages.append("— Tefal Commitments 문구 미발견 — 적용 대상 제품인지 확인 필요 "
                                    "(적용 대상이면 QR·로고 누락)")
                mark_messages_by_file[filename] = messages
                with st.expander(shown_file(filename)+" · 마크 확인 항목",expanded=True):
                    for message in messages:
                        st.write(message)
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
            excluded_by_file = {filename: [] for filename in all_files}
            shown_by_file = {filename: [] for filename in all_files}
            for match in p1_matches:
                phrase = display_phrase(match)
                english = find_english_counterpart(match, summaries)
                # Same Korean registered twice (English variants): show the
                # ledger English that the PDF actually prints.
                for alternate in match.get("alternates") or []:
                    trial = find_english_counterpart(
                        dict(match, reference_english=alternate["reference_english"]), summaries)
                    if trial and len(trial) > len(english or ""):
                        english = trial
                        match["reference_english"] = alternate["reference_english"]
                        match["phrase_id"] = alternate["phrase_id"]
                unreadable = "□" in phrase
                has_number = bool(numeric_tokens(phrase) or match.get("numeric_review"))
                is_uncertain = match["status"] in ("OCR_REVIEW", "NUMERIC_MISMATCH",
                    "TEXT_MISMATCH", "AMBIGUOUS_MATCH", "UNREGISTERED")
                issue = ""
                if match.get("region_ocr"):
                    issue = "텍스트 레이어 없음 · 이미지/벡터 영역 OCR 판독 · 원본 PDF 확인 필요"
                elif unreadable:
                    issue = ("OCR 숫자 판독 불확실 · 원본 PDF 확인 필요"
                             if re.search(r"□+\s*(?:%|개|배|년|위|/)", phrase)
                             else "OCR 글자 판독 불확실(□) · 원본 PDF 확인 필요")
                    excluded_by_file[match["file"]].append(phrase)
                elif match["status"] == "OCR_REVIEW":
                    issue = "원본 글자·숫자 확인 필요"
                elif is_uncertain:
                    issue = match.get("reason") or "기준 문구 확인 필요"
                # Glyphs restored by verified OCR (spaces, or digits read the
                # same by independent passes) are not reported as an issue.
                needs_review = bool(is_uncertain or unreadable or match.get("region_ocr"))
                verdict, reviewer_issue = render_policy_status(
                    match, p1_rules,
                    "확인 필요" if needs_review else reviewer_status(match["status"]),
                    issue)
                shown_by_file[match["file"]].append({
                    "국문 추출 문구": phrase,
                    "영문 추출 문구": english,
                    "문구 카테고리": match.get("category") or "미분류",
                    "문구 유형": "수치 포함" if has_number else "일반 문구",
                    "대조 결과": verdict,
                    "기준 국문": match.get("reference_korean", ""),
                    "기준 영문": match.get("reference_english", ""),
                    "확인할 사항": reviewer_issue,
                })
            counts = [{"제품": shown_file(filename),
                       "추출 문구": len(shown_by_file[filename]),
                       "확인 필요 문구": sum(bool(r["확인할 사항"]) for r in shown_by_file[filename])}
                      for filename in all_files]
            with count_slot.container():
                if len(counts) == 1:
                    left, right = st.columns(2)
                    left.metric("추출 문구", counts[0]["추출 문구"])
                    right.metric("확인 필요 문구", counts[0]["확인 필요 문구"])
                else:
                    st.dataframe(pd.DataFrame(counts), use_container_width=True, hide_index=True)
            # PDF 원본 column: crop of each phrase's printed source lines.
            uploaded_bytes = {f.name: f.getvalue() for f in (files or [])}
            for filename in all_files:
                pdf_bytes = uploaded_bytes.get(filename)
                file_matches = [m for m in p1_matches if m["file"] == filename]
                if not pdf_bytes or not file_matches:
                    continue
                requests = []
                for match in file_matches:
                    coordinates = [c for c in match.get("source_coordinates") or []
                                   if len(c.get("bbox") or []) == 4]
                    page_no = (coordinates[0].get("page") if coordinates else None) or match.get("page") or 1
                    boxes = tuple(tuple(float(v) for v in c["bbox"]) for c in coordinates
                                  if (c.get("page") or page_no) == page_no)
                    first = next((i for i in match.get("line_indices") or []
                                  if isinstance(i, int) and 0 <= i < len(rows)), None)
                    turn = 0
                    if first is not None:
                        dx = float(rows[first].get("dir_x", 1) or 0)
                        dy = float(rows[first].get("dir_y", 0) or 0)
                        turn = 180 if dx < -.8 else 90 if dy > .8 else 270 if dy < -.8 else 0
                    requests.append((int(page_no), boxes, turn))
                images = cached_phrase_crops(pdf_bytes, tuple(requests))
                for record, image in zip(shown_by_file[filename], images):
                    record["PDF 원본 이미지"] = image
            for filename in all_files:
                product_rows = shown_by_file[filename]
                st.markdown(f"#### {shown_file(filename)}")
                if product_rows:
                    st.markdown(reviewer_html_table(product_rows), unsafe_allow_html=True)
                    needing_review = sum(bool(row["확인할 사항"]) for row in product_rows)
                    st.caption(f"추출 문구 {len(product_rows)}개 · 확인 필요 {needing_review}개")
                else:
                    st.info("이 제품에서 추출된 문구가 없습니다.")
                if excluded_by_file[filename]:
                    st.warning(
                        f"판독할 수 없는 글자(□)가 남은 문구 {len(excluded_by_file[filename])}개를 "
                        "원문 그대로 검수표에 확인 필요로 표시했습니다. PDF 원본 확인이 필요합니다."
                    )
                    with st.expander("판독 불확실 글자(□) 포함 문구 · 원본 확인 필요"):
                        for issue in excluded_by_file[filename]:
                            st.write(issue)
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
                # Same mark checklist as above, next to the PDF so the marks
                # can be checked against the page while looking at it.
                if mark_messages_by_file.get(view_file):
                    st.markdown("**마크·QR 확인 필요 체크리스트**")
                    with st.container(border=True):
                        for message in mark_messages_by_file[view_file]:
                            st.write(message)
                    st.caption("오른쪽 전체 PDF를 클릭·휠로 확대해 마크를 확인하세요.")
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
                    zoom_page, zoom_height = cached_zoom_view(
                        uploaded_pdf.getvalue(), view_page, json.dumps(boxes, ensure_ascii=False, default=str),
                        item_index, show_all,
                        f"{shown_file(view_file)} · {view_page}페이지 (원본 PDF 근거 위치)")
                    components.html(zoom_page, height=zoom_height + 40, scrolling=False)
                    st.caption("PDF 전체 페이지를 표시합니다. 선택된 항목은 노란색으로 강조됩니다. "
                               "클릭할 때마다 그 지점이 확대됩니다.")

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

if timing_renderer is not None:
    timing_renderer()
