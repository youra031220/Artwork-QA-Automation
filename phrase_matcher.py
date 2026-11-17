"""P1 conservative bilingual reference matching. Never changes extracted source text."""
import re
from difflib import SequenceMatcher

NUMBER = re.compile(r"\d+(?:[.,]\d+)?\s*(?:%|배|년|cm|mm|위|개|명|/|\b)")
DAMAGE = re.compile(r"\ufffd|�{1,}|(?<!\w)\d+\s*&")
POLARITY = ("불가", "가능", "제외", "포함", "없음", "있음", "미사용", "사용")


def normalize(text):
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    text = re.sub(r"(?<=\d)\s+(?=%|cm\b|mm\b|배\b|년\b|위\b)", "", text, flags=re.I)
    return text


def compact(text):
    return re.sub(r"\s+", "", normalize(text)).casefold()


def tokens(text):
    return [re.sub(r"\s+", "", x).casefold() for x in NUMBER.findall(text or "")]


def contradicts(a, b):
    na, nb = compact(a), compact(b)
    for left, right in (("가능", "불가"), ("포함", "제외"),
                        ("있음", "없음")):
        if (left in na and right in nb) or (right in na and left in nb):
            return True
    return False


def _variable_year_match(actual, expected):
    """Match each literal '202X' in an approved template independently.

    The template does not assert that the edition and sales years are equal.
    Preserve the observed values: a pattern match is not proof that this year's
    attribution is commercially approved.
    """
    expected_compact = compact(expected)
    if "202x" not in expected_compact:
        return None
    # Only the explicitly marked year is variable; all other characters,
    # numbers, punctuation, and wording remain literal.
    pattern = re.escape(expected_compact).replace("202x", r"(202\d)")
    found = re.fullmatch(pattern, compact(actual))
    return found.groups() if found else None


# Footnote reference marks: '(1)', '[1]', '¹' at the start or end of a phrase.
# They point to a separately printed footnote and are not claim numbers.
FOOTNOTE_MARK = re.compile(r"^\s*[\[(]\s*\d\s*[\])]\s*|\s*[\[(]\s*\d\s*[\])]\s*$|[¹²³]")


def strip_marks(text):
    return FOOTNOTE_MARK.sub("", str(text or "")).strip()


LEDGER_INSTRUCTION = re.compile(r"\s*\((?:Please|please|PLEASE)\b[^)]*\)")


def _reference_candidates(master):
    """Ledger rows for comparison. Editorial instructions written into a
    Korean cell (e.g. '(Please ensure you observe these line breaks)') are
    not printed copy, so they are left out of the comparison text only; the
    ledger itself is not modified."""
    variants = {v["phrase_id"]: v for v in master.get("variants", [])}
    output = []
    for p in master.get("phrases", []):
        if not p.get("korean_original"):
            continue
        cleaned = LEDGER_INSTRUCTION.sub("", p["korean_original"]).strip()
        output.append((dict(p, korean_original=cleaned) if cleaned != p["korean_original"] else p,
                       variants.get(p["phrase_id"], {})))
    return output


def _one(row, master):
    actual = row.get("paragraph", row.get("korean_text", ""))
    filename, page = row.get("file", ""), row.get("page", 0)
    base = dict(file=filename, page=page, extracted=actual,
                line_indices=row.get("line_indices", []),
                source_coordinates=row.get("source_coordinates", []),
                ocr_candidates=row.get("ocr_candidates", []),
                numeric_review=bool(row.get("numeric_review")),
                original_extracted=row.get("original_paragraph", actual),
                ocr_reconstructed=bool(row.get("ocr_reconstructed")),
                region_ocr=bool(row.get("region_ocr")),
                text_source=row.get("text_source", "native_pdf"),
                phrase_id="", rule_id="", category="미분류", reference_korean="",
                reference_english="", source_row=None, approval_status="",
                differences="", reason="", candidates=[])
    refs = _reference_candidates(master)
    if not actual.strip():
        return dict(base, status="UNREGISTERED", reason="빈 문구")
    exact = [(p,v) for p,v in refs if actual == p["korean_original"]]
    # Only terminal punctuation and whitespace are cosmetic. A missing
    # full-stop at the end of printed QR instructions is not a mistranslation.
    def orthographic(value):
        return compact(strip_marks(value)).rstrip(".。")
    norm = [(p,v) for p,v in refs if orthographic(actual) == orthographic(p["korean_original"])]
    matches = exact or norm
    alternates = []
    if matches:
        if len({p["phrase_id"] for p,v in matches}) > 1:
            # Rows with the SAME Korean text, category and rule are one
            # Korean answer registered twice (e.g. English singular/plural
            # variants). That is not an ambiguity for the Korean check.
            # Rows that differ in category or rule stay ambiguous.
            keys = {(compact(p["korean_original"]), p["category_id"], v.get("rule_id", ""))
                    for p,v in matches}
            if len(keys) > 1:
                return dict(base, status="AMBIGUOUS_MATCH", candidates=[
                    p["phrase_id"] for p,v in matches],
                    reason="복수의 정답 행에 동일 문구가 존재")
            alternates = [{"phrase_id": p["phrase_id"],
                           "reference_english": p.get("english_original", ""),
                           "source_row": p.get("source_row")} for p,v in matches]
        p,v = matches[0]
        status = ("OCR_REVIEW" if row.get("numeric_review") or DAMAGE.search(actual)
                  else "EXACT_MATCH" if exact else "NORMALIZED_MATCH")
        return dict(base, status=status, phrase_id=p["phrase_id"],
                    rule_id=v.get("rule_id", ""), category=p["category_id"],
                    reference_korean=p["korean_original"],
                    reference_english=p.get("english_original",""),
                    approval_status=p.get("approval_status","UNVERIFIED"),
                    source_row=p.get("source_row"),
                    candidates=[a["phrase_id"] for a in alternates],
                    alternates=alternates,
                    differences=("원장 동일 국문 중복 등록: " + ", ".join(
                        a["phrase_id"] for a in alternates)) if alternates else (
                        "각주 기호 표기 차이: 원장 '" + FOOTNOTE_MARK.search(p["korean_original"]).group().strip() + "'"
                        if not exact and FOOTNOTE_MARK.search(p["korean_original"])
                        and not FOOTNOTE_MARK.search(actual) else ""),
                    reason=("원문 손상·숫자 대조 필요" if status=="OCR_REVIEW"
                            else "기준 문구와 일치 (최종 승인 의미 아님)"))
    # Workbook's Y is a range-specific multiplier placeholder. Identify the
    # reference but do not claim it is approved before range validation.
    variable_refs=[]
    for p,v in refs:
        expected=p["korean_original"]
        if "Y배" not in expected and "Y 배" not in expected:
            continue
        pattern=re.escape(compact(expected))
        pattern=pattern.replace("y배", r"(?P<multiplier>\d{1,2})배")
        match=re.fullmatch(pattern,compact(actual))
        if match:
            variable_refs.append((p,v,match.group("multiplier")))
    if variable_refs:
        p,v,value=variable_refs[0]
        return dict(base,status="OCR_REVIEW" if row.get("numeric_review") else "TEXT_MISMATCH",
                    phrase_id=p["phrase_id"],rule_id=v.get("rule_id",""),
                    category=p["category_id"],source_row=p.get("source_row"),
                    approval_status=p.get("approval_status","UNVERIFIED"),
                    reference_korean=p["korean_original"],
                    reference_english=p.get("english_original",""),
                    differences="Y="+value,
                    reason="정답 데이터의 Y배 변수 후보: 레인지별 승인 배수 검토 필요")
    # Permit a reference substring inside a longer physically grouped line.
    # Never accept a bare one-word anchor or a tiny fragment as a match.
    contains=[(p,v) for p,v in refs if len(compact(p["korean_original"])) >= 12
              and compact(p["korean_original"]) in compact(actual)]
    if contains:
        p,v=max(contains,key=lambda pair:len(pair[0]["korean_original"]))
        # A longer ledger sentence that covers the WHOLE extracted text (only
        # damaged glyphs / a variable differ) is the better reference than a
        # short clause that happens to be contained in it.
        whole=[(SequenceMatcher(None,compact(actual),compact(q["korean_original"])).ratio(),q,w)
               for q,w in refs if len(compact(q["korean_original"]))>len(compact(p["korean_original"]))]
        whole=[t for t in whole if t[0]>=.85]
        if whole:
            score,q,w=max(whole,key=lambda t:t[0])
            damaged=bool(row.get("numeric_review") or DAMAGE.search(actual))
            return dict(base,status="OCR_REVIEW" if damaged else "TEXT_MISMATCH",
                        phrase_id=q["phrase_id"],rule_id=w.get("rule_id",""),
                        category=q["category_id"],source_row=q.get("source_row"),
                        reference_korean=q["korean_original"],
                        reference_english=q.get("english_original",""),
                        approval_status=q.get("approval_status","UNVERIFIED"),
                        differences="OCR 글자 손상 · 원본 확인" if damaged else "문자·숫자 차이 검토 필요",
                        reason=("원본 일부 글자·숫자 판독 불가 · 원본 확인 필요" if damaged
                                else "기준 문구와 일부 다름 · 차이 확인 필요"))
        damaged = bool(row.get("numeric_review") or DAMAGE.search(actual))
        # The workbook phrase may be only one clause of a longer printed
        # statement.  Do not mark the entire statement as approved.
        extra = compact(actual).replace(compact(p["korean_original"]), "", 1)
        if extra and not re.fullmatch(r"[.,:;()·•\\-]*", extra):
            return dict(base, status="OCR_REVIEW" if damaged else "TEXT_MISMATCH",
                        phrase_id=p["phrase_id"], rule_id=v.get("rule_id",""),
                        category=p["category_id"],
                        reference_korean=p["korean_original"],
                        reference_english=p.get("english_original",""),
                        approval_status=p.get("approval_status","UNVERIFIED"),
                        source_row=p.get("source_row"),
                        differences="원장 문구 외 추가 인쇄 내용 존재",
                        reason="부분 문구만 일치 · 추가 문장을 별도로 대조해야 함")
        return dict(base, status="OCR_REVIEW" if damaged else "NORMALIZED_MATCH",
                    phrase_id=p["phrase_id"], rule_id=v.get("rule_id",""),
                    category=p["category_id"], reference_korean=p["korean_original"],
                    reference_english=p.get("english_original",""),
                    approval_status=p.get("approval_status","UNVERIFIED"),
                    source_row=p.get("source_row"),
                    differences="원본 일부 글자·숫자 판독 불가" if damaged else "",
                    reason=("기준 문구 일부 일치 · 나머지 손상된 원문 확인 필요"
                            if damaged else "긴 추출 문구에 기준 문구가 포함됨"))
    # '202X' is a per-occurrence year placeholder, not a literal number.
    # This must run before fuzzy/numeric mismatch detection.
    year_matches = [(p,v,values) for p,v in refs
                    if (values := _variable_year_match(actual,p["korean_original"])) is not None]
    if year_matches:
        unique = {p["phrase_id"] for p,v,values in year_matches}
        if len(unique)>1:
            return dict(base, status="AMBIGUOUS_MATCH",
                        candidates=sorted(unique),
                        reason="연도 변수 패턴에 일치하는 복수 기준 문구")
        p,v,values=year_matches[0]
        return dict(base,
                    status="OCR_REVIEW" if row.get("numeric_review") or DAMAGE.search(actual)
                    else "VARIABLE_MATCH",
                    phrase_id=p["phrase_id"],rule_id=v.get("rule_id",""),
                    category=p["category_id"],source_row=p.get("source_row"),
                    approval_status=p.get("approval_status","UNVERIFIED"),
                    reference_korean=p["korean_original"],
                    reference_english=p.get("english_original",""),
                    differences="연도 변수: " + ", ".join(values),
                    reason="202X 연도 변수 패턴 일치 · 에디션/매출 기준연도 적합성은 별도 확인")
    # Fuzzy hits only suggest a reference. No automatic approval or rule count.
    scored=[]
    for p,v in refs:
        expected=p["korean_original"]
        if len(compact(expected)) < 8 or len(compact(actual)) < 8:
            continue
        similarity=SequenceMatcher(None,compact(actual),compact(expected)).ratio()
        if similarity>=.78:
            scored.append((similarity,p,v))
    scored.sort(key=lambda t:t[0], reverse=True)
    if not scored:
        return dict(base,status="OCR_REVIEW" if row.get("numeric_review") or DAMAGE.search(actual) else "UNREGISTERED",
                    reason=("글자·숫자 손상으로 정답 대조 보류 · PDF 원본 확인" if row.get("numeric_review") or DAMAGE.search(actual) else "기준 데이터에서 일치 문구 미발견"))
    score,p,v=scored[0]
    others=[x[1]["phrase_id"] for x in scored if x[0]>=score-.02]
    mismatch = (tokens(strip_marks(actual))!=tokens(strip_marks(p["korean_original"]))
                or bool(DAMAGE.search(actual)))
    status=("OCR_REVIEW" if row.get("numeric_review") or DAMAGE.search(actual)
            else "NUMERIC_MISMATCH" if mismatch
            else "TEXT_MISMATCH")
    if not mismatch and contradicts(actual,p["korean_original"]):
        status="TEXT_MISMATCH"
    if len(others)>1:
        status="AMBIGUOUS_MATCH"
    actual_numbers, expected_numbers = tokens(strip_marks(actual)), tokens(strip_marks(p["korean_original"]))
    added_only = (mismatch and not DAMAGE.search(actual)
                  and set(expected_numbers) <= set(actual_numbers))
    numeric_value = re.compile(r"\d{1,4}\s*/\s*\d{1,4}|\d+(?:[.,]\d+)?\s*(?:%|년|배|개|위|cm|mm)?")
    expected_compact = compact(p["korean_original"])
    added = sorted({re.sub(r"\s+", "", m.group()) for m in numeric_value.finditer(actual)
                    if re.sub(r"\s+", "", m.group()).casefold() not in expected_compact})
    if row.get("numeric_review") or DAMAGE.search(actual):
        differences = "OCR 글자 손상 · 원본 확인"
        reason = "가장 유사한 정답 후보. 자동 승인/발견 집계 제외"
    elif added_only:
        # e.g. PDF '18/10 스테인리스 스틸 - 10년 품질보증' vs ledger
        # '스테인리스 스틸 10년 품질보증': every ledger number is printed and
        # the PDF ADDS a value. This is not a wrong number.
        differences = "원장에 없는 수치 추가: " + ", ".join(added)
        reason = ("원장 수치는 모두 일치 · PDF에 원장 미등록 수치(" + ", ".join(added)
                  + ") 추가 인쇄 · 원장 등록 여부 확인 필요")
    elif mismatch:
        printed = ", ".join(tokens(strip_marks(actual))) or "없음"
        ledger = ", ".join(tokens(strip_marks(p["korean_original"]))) or "없음"
        differences = f"숫자·단위 불일치 (PDF {printed} / 원장 {ledger})"
        reason = (f"원장과 다른 수치 · PDF {printed} / 원장 {ledger} · "
                  "원장 미등록 구성이면 원장 등록 필요")
    else:
        differences = "문자·의미 검토 필요"
        reason = "가장 유사한 정답 후보. 자동 승인/발견 집계 제외"
    return dict(base,status=status,phrase_id=p["phrase_id"],
                rule_id=v.get("rule_id",""),category=p["category_id"],
                source_row=p.get("source_row"),
                reference_korean=p["korean_original"],
                reference_english=p.get("english_original",""),
                approval_status=p.get("approval_status","UNVERIFIED"),
                differences=differences,
                reason=reason,
                candidates=others)


def match_phrases(groups, master):
    """Every extracted group receives exactly one result, even unregistered."""
    return [_one(row,master) for row in groups]
