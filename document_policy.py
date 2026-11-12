"""Artwork release checks derived from documented correction scenarios.

These checks are independent of fuzzy reference matching. In particular,
identical *meaning* and approved *wording* are different axes of inspection.
Every hard failure needs explicit positive source evidence. Image-only marks,
unresolved applicability and OCR fragments remain REVIEW.
"""
import re
from collections import defaultdict

# Effective scope is explicit: this is the June 2026 request to standardize
# non-induction (NIH) Korean artwork. Do not reinterpret "ALL HOBS" in the
# reference workbook as equivalent to this exclusion variant.
NIH_OLD = re.compile(r"모든\s*열원\s*사용\s*가능\s*\(\s*인덕션\s*제외\s*\)")
NIH_NEW = re.compile(
    r"가스레인지\s*,?\s*핫플레이트\s*,?\s*하이라이트\s*사용\s*가능\s*"
    r"\(\s*인덕션\s*사용\s*불가\s*\)"
)
IH_KO = re.compile(r"인덕션\s*(?:포함|사용\s*가능)")
NIH_KO = re.compile(r"인덕션\s*(?:사용\s*불가|제외)")
IH_EN = re.compile(r"\bALL\s+HOBS\s*\+\s*INDUCTION\b", re.I)
NIH_EN = re.compile(r"\bALL\s+HOBS\s+EXCEPT\s+INDUCTION\b", re.I)
EDITION_KO = re.compile(r"Home\s+and\s+Garden\s+(20\d{2})\s*에디션", re.I)
EDITION_EN = re.compile(r"Home\s+and\s+Garden\s+(20\d{2})\s+edition", re.I)
DATA_KO = re.compile(r"(20\d{2})\s*기준")
DATA_EN = re.compile(r"(20\d{2})\s+data\b", re.I)
WARRANTY_KO = re.compile(r"(?<!\d)(\d{1,2})\s*년간?\s*품질\s*보증|품질\s*보증\s*(\d{1,2})\s*년")
WARRANTY_EN = re.compile(r"\b(?:guaranteed\s+for|warranty\s+(?:of|for))\s+(\d{1,2})\s+years?\b",re.I)
YEAR_EDITION_POLICY = {(2026, 2025)}
WORLD_KO = re.compile(r"세계\s*판매\s*1\s*위|세계판매\s*1위")
WORLD_EN = re.compile(r"\b(?:world\s+n[°ºo]?\s*1|world\s+no\.?\s*1)\b",re.I)
RECYCLE_GLASS_EXCLUSION = re.compile(r"유리\s*뚜껑\s*제외")


def _add(file, rule, category, verdict, finding, evidence, **detail):
    return dict(file=file,rule_id=rule,category=category,rule_type="DOCUMENT_POLICY",
                condition="",min_count=0,max_count=None,found_occurrences=len(evidence),
                distinct_variants=len(set(evidence)),matched_phrase_ids=[],
                review_candidates=[],applicability="APPLICABLE",status=verdict,
                finding=finding,source_reference="Documented correction / QA policy",
                evidence=evidence,**detail)


def _clean(value):
    return re.sub(r"\s+"," ",str(value or "")).strip()


def _texts_for_file(matches,summaries,filename):
    ko=[_clean(m.get("extracted")) for m in matches if m.get("file")==filename]
    native=[_clean(line.get("text")) for summary in summaries
            if summary.get("file")==filename
            for line in summary.get("raw_evidence",[])]
    return ko,native


def _joined_native(native):
    # Preserve raw line text and its page-separated evidence. The current
    # summarizer already keeps each file independent; do not mix products.
    return " ".join(native)


def evaluate_document_policy(matches, summaries, metadata, filename,
                             approved_year_pairs=None):
    """High-confidence policy checks for a single artwork PDF.

    Approved date pairs are configuration, not the universal arithmetic
    edition=data+1 assumption. Unknown year pairs are REVIEW until approved.
    """
    ko,native=_texts_for_file(matches,summaries,filename)
    ko_all=" ".join(ko)
    en_all=_joined_native(native)
    result=[]
    old=[x for x in ko if NIH_OLD.search(x)]
    new=[x for x in ko if NIH_NEW.search(x)]
    ih_ko=[x for x in ko if IH_KO.search(x) and not NIH_KO.search(x)]
    nih_ko=[x for x in ko if NIH_KO.search(x)]
    ih_en=IH_EN.findall(en_all)
    nih_en=NIH_EN.findall(en_all)
    if old:
        result.append(_add(filename,"DOC-NIH-LEGACY","사용가능 열원","FAIL",
            "이전 NIH 문구 사용. '가스레인지, 핫플레이트, 하이라이트 사용 가능 (인덕션 사용 불가)'로 수정 필요",
            old,corrected_text="가스레인지, 핫플레이트, 하이라이트 사용 가능 (인덕션 사용 불가)"))
    if old and new:
        result.append(_add(filename,"DOC-NIH-MIXED-WORDING","사용가능 열원","FAIL",
            "같은 열원 조건의 이전 표현과 변경 표현이 함께 존재",old+new))
    # An English confirmation of NIH does not contradict its previous Korean
    # wording: that's a *wording* error, not an induction semantic conflict.
    if (ih_ko or ih_en) and (nih_ko or nih_en):
        result.append(_add(filename,"DOC-IH-SEMANTIC-CONFLICT","사용가능 열원","FAIL",
            "인덕션 사용 가능·사용 불가 조건이 동일 아트웍에 함께 존재",
            ih_ko+nih_ko+ih_en+nih_en))
    elif nih_en and ih_ko:
        result.append(_add(filename,"DOC-IH-EN-KO-MISMATCH","사용가능 열원","FAIL",
            "영문은 인덕션 제외, 국문은 인덕션 가능",nih_en+ih_ko))
    elif ih_en and nih_ko:
        result.append(_add(filename,"DOC-IH-EN-KO-MISMATCH","사용가능 열원","FAIL",
            "영문은 인덕션 가능, 국문은 인덕션 불가",ih_en+nih_ko))
    # Edition year and source-data year are DIFFERENT named variables.
    # Source text may be in different blocks. Match any actual observed year
    # from each language, but never assume their relation without a policy.
    ko_world=" ".join(t for t in ko if "Euromonitor" in t or WORLD_KO.search(t))
    en_world=" ".join(t for t in native if "Euromonitor" in t or WORLD_EN.search(t)
                      or "Home and Garden" in t or "brand retail value" in t)
    ko_ed=set(map(int,EDITION_KO.findall(ko_world)))
    en_ed=set(map(int,EDITION_EN.findall(en_world)))
    ko_data=set(map(int,DATA_KO.findall(ko_world)))
    en_data=set(map(int,DATA_EN.findall(en_world)))
    if ko_ed and en_ed and ko_ed != en_ed:
        result.append(_add(filename,"DOC-WORLD-EDITION-LANG","세계 1위 출처","FAIL",
            f"영문 에디션 {sorted(en_ed)}년, 국문 에디션 {sorted(ko_ed)}년 불일치",
            [f"영문 {v} edition" for v in en_ed]+[f"국문 {v} 에디션" for v in ko_ed]))
    if ko_data and en_data and ko_data != en_data:
        result.append(_add(filename,"DOC-WORLD-DATA-LANG","세계 1위 출처","FAIL",
            f"영문 기준연도 {sorted(en_data)}년, 국문 기준연도 {sorted(ko_data)}년 불일치",
            [f"영문 {v} data" for v in en_data]+[f"국문 {v} 기준" for v in ko_data]))
    pairs=approved_year_pairs if approved_year_pairs is not None else YEAR_EDITION_POLICY
    # Check if both years were observed in Korean artwork, not merely English.
    if len(ko_ed)==1 and len(ko_data)==1 and not result_has_year_damage(result):
        pair=(next(iter(ko_ed)),next(iter(ko_data)))
        if pair not in pairs:
            result.append(_add(filename,"DOC-WORLD-YEAR-POLICY","세계 1위 출처","REVIEW",
                f"에디션 {pair[0]}년·매출 기준 {pair[1]}년의 적용 승인 여부 확인 필요",
                [f"{pair[0]} 에디션",f"{pair[1]} 기준"]))
    # Explicit warranty cross-language numeral mismatch. Multiple ranges
    # (whole product vs stainless material) require scope review.
    ko_years={int(a or b) for t in ko for a,b in WARRANTY_KO.findall(t)}
    en_years={int(y) for y in WARRANTY_EN.findall(en_all)}
    if len(ko_years)==1 and len(en_years)==1 and ko_years != en_years:
        result.append(_add(filename,"DOC-WARRANTY-LANGUAGE","품질 보증","FAIL",
            f"국문 품질보증 {next(iter(ko_years))}년, 영문 보증 {next(iter(en_years))}년 불일치",
            [f"국문 {next(iter(ko_years))}년",f"영문 {next(iter(en_years))}년"]))
    elif len(ko_years)>1 or len(en_years)>1:
        result.append(_add(filename,"DOC-WARRANTY-SCOPE","품질 보증","REVIEW",
            "여러 보증기간 발견. 제품 전체와 부품별 보증기간 적용 범위를 확인",
            [f"국문 {y}년" for y in ko_years]+[f"영문 {y}년" for y in en_years]))
    item=next((m for m in metadata if m.get("file")==filename),{})
    # A lid presence alone does not prove glass. Unknown or misidentified
    # image marks MUST NOT become automatic hard failures.
    if item.get("lid_material") in ("glass","GLASS"):
        if "적절한 분리배출" in ko_all and not RECYCLE_GLASS_EXCLUSION.search(ko_all):
            result.append(_add(filename,"DOC-RECYCLE-GLASS","재활용","REVIEW",
                "유리 뚜껑 제품: 분리배출 안내의 '(유리뚜껑 제외)' 적용 여부 확인",
                ["적절한 분리배출"]))
    return result


def result_has_year_damage(results):
    return any(x["rule_id"] in ("DOC-WORLD-EDITION-LANG","DOC-WORLD-DATA-LANG")
               for x in results)



def evaluate_bilingual_values(matches,summaries,filename):
    """Compare source-backed bilingual claim values, never workbook defaults.

    Only percentages and performance multipliers with explicit units qualify;
    cookware dimensions, reference footnote numbers, 18/10 steel grade and
    date citations must not be conflated with promotional percentages.
    """
    from english_pairing import find_english_counterpart
    results=[]
    for match in matches:
        if match.get("file")!=filename:
            continue
        ko=str(match.get("extracted") or "")
        en=find_english_counterpart(match,summaries)
        if not en:
            continue
        ko_multiplier=re.search(r"최대\s*(\d+(?:\.\d+)?)\s*배",ko)
        en_multiplier=re.search(r"\bUP\s+TO\s+(\d+(?:\.\d+)?)\s*[Xx]\b",en,re.I)
        if ko_multiplier and en_multiplier and float(ko_multiplier.group(1))!=float(en_multiplier.group(1)):
            results.append(_add(filename,"DOC-BILINGUAL-MULTIPLIER","성능 수치","FAIL",
                f"영문 {en_multiplier.group(1)}배, 국문 {ko_multiplier.group(1)}배 성능 수치 불일치",
                [ko,en]))
        ko_pct=re.search(r"(?<!\d)(\d{1,3}(?:\.\d+)?)\s*%",ko)
        en_pct=re.search(r"(?<!\d)(\d{1,3}(?:\.\d+)?)\s*%",en)
        if ko_pct and en_pct and float(ko_pct.group(1))!=float(en_pct.group(1)):
            results.append(_add(filename,"DOC-BILINGUAL-PERCENT","성능 수치","FAIL",
                f"영문 {en_pct.group(1)}%, 국문 {ko_pct.group(1)}% 불일치",
                [ko,en]))
    return results


def evaluate_recycling_exclusivity(matches,metadata,filename):
    """Check two distinct printing variants, without mistaking overlap for
    two variants inside ONE long recycling paragraph."""
    variants=[]
    for match in matches:
        if match.get("file")!=filename:
            continue
        text=str(match.get("extracted") or "")
        if not ("재활용" in text or "분리배출" in text):
            continue
        variants.append((text,bool(RECYCLE_GLASS_EXCLUSION.search(text))))
    if not variants or len({flag for _,flag in variants})<2:
        return []
    return [_add(filename,"DOC-RECYCLE-MIXED","재활용","REVIEW",
        "일반 재활용 안내와 유리뚜껑 제외 버전이 함께 발견됨. 동일 안내의 대체 문구인지 확인 필요",
        [v for v,_ in variants])]

def compare_range_messages(matches,metadata):
    """Cross-file check: only confirmed range names and explicit key-message
    classifications. Unknown range or unregistered key-message is not FAIL.
    """
    by_file={x["file"]:x for x in metadata if x.get("range_name")}
    grouped=defaultdict(lambda:defaultdict(set))
    for m in matches:
        meta=by_file.get(m.get("file"))
        if not meta:
            continue
        category=str(m.get("category") or "")
        if not re.search(r"키\s*메시지|키\s*메세지",category):
            continue
        if m.get("status") not in {"EXACT_MATCH","NORMALIZED_MATCH","VARIABLE_MATCH"}:
            continue
        normalized=re.sub(r"\s+","",m.get("reference_korean") or m.get("extracted") or "")
        if normalized:
            grouped[_clean(meta["range_name"]).casefold()][m["file"]].add(normalized)
    output=[]
    for range_name,files in grouped.items():
        if len(files)<2:
            continue
        distinct={next(iter(v)) for v in files.values() if len(v)==1}
        if len(distinct)>1 and all(len(v)==1 for v in files.values()):
            for filename,claims in files.items():
                output.append(_add(filename,"DOC-RANGE-KEY-MESSAGE","키 메시지","REVIEW",
                    f"같은 레인지({range_name})의 다른 제품과 키 메시지가 다름",
                    list(claims)))
    return output
