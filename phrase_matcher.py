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


def _reference_candidates(master):
    variants = {v["phrase_id"]: v for v in master.get("variants", [])}
    return [(p, variants.get(p["phrase_id"], {})) for p in master.get("phrases", [])
            if p.get("korean_original")]


def _one(row, master):
    actual = row.get("paragraph", row.get("korean_text", ""))
    filename, page = row.get("file", ""), row.get("page", 0)
    base = dict(file=filename, page=page, extracted=actual,
                line_indices=row.get("line_indices", []),
                source_coordinates=row.get("source_coordinates", []),
                ocr_candidates=row.get("ocr_candidates", []),
                numeric_review=bool(row.get("numeric_review")),
                phrase_id="", rule_id="", category="미분류", reference_korean="",
                reference_english="", source_row=None, approval_status="",
                differences="", reason="", candidates=[])
    refs = _reference_candidates(master)
    if not actual.strip():
        return dict(base, status="UNREGISTERED", reason="빈 문구")
    exact = [(p,v) for p,v in refs if actual == p["korean_original"]]
    norm = [(p,v) for p,v in refs if compact(actual) == compact(p["korean_original"])]
    matches = exact or norm
    if matches:
        if len({p["phrase_id"] for p,v in matches}) > 1:
            return dict(base, status="AMBIGUOUS_MATCH", candidates=[
                p["phrase_id"] for p,v in matches],
                reason="복수의 정답 행에 동일 문구가 존재")
        p,v = matches[0]
        status = ("OCR_REVIEW" if row.get("numeric_review") or DAMAGE.search(actual)
                  else "EXACT_MATCH" if exact else "NORMALIZED_MATCH")
        return dict(base, status=status, phrase_id=p["phrase_id"],
                    rule_id=v.get("rule_id", ""), category=p["category_id"],
                    reference_korean=p["korean_original"],
                    reference_english=p.get("english_original",""),
                    approval_status=p.get("approval_status","UNVERIFIED"),
                    source_row=p.get("source_row"),
                    reason=("원문 손상·숫자 대조 필요" if status=="OCR_REVIEW"
                            else "기준 문구와 일치 (최종 승인 의미 아님)"))
    # Permit a reference substring inside a longer physically grouped line.
    # Never accept a bare one-word anchor or a tiny fragment as a match.
    contains=[(p,v) for p,v in refs if len(compact(p["korean_original"])) >= 12
              and compact(p["korean_original"]) in compact(actual)]
    if contains:
        p,v=max(contains,key=lambda pair:len(pair[0]["korean_original"]))
        return dict(base, status="NORMALIZED_MATCH" if not row.get("numeric_review") else "OCR_REVIEW",
                    phrase_id=p["phrase_id"], rule_id=v.get("rule_id",""),
                    category=p["category_id"], reference_korean=p["korean_original"],
                    reference_english=p.get("english_original",""),
                    approval_status=p.get("approval_status","UNVERIFIED"),
                    source_row=p.get("source_row"), reason="긴 추출 문구에 기준 문구가 포함됨")
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
                    reason="기준 데이터에서 일치 문구 미발견")
    score,p,v=scored[0]
    others=[x[1]["phrase_id"] for x in scored if x[0]>=score-.02]
    mismatch = (tokens(actual)!=tokens(p["korean_original"])
                or bool(DAMAGE.search(actual)))
    status=("OCR_REVIEW" if row.get("numeric_review") or DAMAGE.search(actual)
            else "NUMERIC_MISMATCH" if mismatch
            else "TEXT_MISMATCH")
    if not mismatch and contradicts(actual,p["korean_original"]):
        status="TEXT_MISMATCH"
    if len(others)>1:
        status="AMBIGUOUS_MATCH"
    return dict(base,status=status,phrase_id=p["phrase_id"],
                rule_id=v.get("rule_id",""),category=p["category_id"],
                source_row=p.get("source_row"),
                reference_korean=p["korean_original"],
                reference_english=p.get("english_original",""),
                approval_status=p.get("approval_status","UNVERIFIED"),
                differences="숫자·단위 불일치" if mismatch else "문자·의미 검토 필요",
                reason="가장 유사한 정답 후보. 자동 승인/발견 집계 제외",
                candidates=others)


def match_phrases(groups, master):
    """Every extracted group receives exactly one result, even unregistered."""
    return [_one(row,master) for row in groups]
