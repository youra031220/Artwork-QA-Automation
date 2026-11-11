"""P1 rule evaluations with conservative evidence thresholds."""
from collections import Counter, defaultdict
import re

ACCEPTED = {"EXACT_MATCH", "NORMALIZED_MATCH"}
REVIEW_STATES = {"OCR_REVIEW", "NUMERIC_MISMATCH", "TEXT_MISMATCH", "AMBIGUOUS_MATCH"}


def _variant_key(match):
    # Same phrase repeated across artwork positions is one distinct variant.
    return match.get("phrase_id") or ""


def evaluate_rules(matches, master, filename, context=None):
    context = context or {}
    in_file = [m for m in matches if m.get("file") == filename]
    variants = master.get("variants", [])
    results = []
    for rule in master.get("rules", []):
        rule_id = rule["rule_id"]
        ids = {v["phrase_id"] for v in variants if v["rule_id"] == rule_id}
        related = [m for m in in_file if m.get("phrase_id") in ids]
        confirmed = [m for m in related if m["status"] in ACCEPTED]
        distinct = sorted(set(_variant_key(m) for m in confirmed))
        matched_count = len(confirmed)
        distinct_count = len(distinct)
        candidate = [m for m in related if m["status"] in REVIEW_STATES]
        kind = rule.get("rule_type", "OPTIONAL")
        count_min = rule.get("min_count", 0) or 0
        count_max = rule.get("max_count")
        status = "OK"
        finding = "기준 데이터의 문구로 확인됨"
        applicability = "APPLICABLE"
        if kind == "CONDITIONAL":
            # Source workbook contains a human-readable condition, not a
            # guaranteed executable logo/image predicate.
            applicability = "UNDETERMINED"
            status, finding = "REVIEW", "조건부 마크·제품 적용 조건 확인 필요"
        elif kind == "IF_PRESENT":
            applicability = "UNDETERMINED"
            status, finding = "REVIEW", "영문 존재 여부와 국문 동반 여부 확인 필요"
        elif kind == "ALL_REQUIRED":
            expected = ids
            missing = sorted(expected - set(distinct))
            if missing:
                status, finding = "REVIEW", "지정 문장 일부 미발견: " + ", ".join(missing)
            else:
                finding = "등록된 필수 문장이 모두 발견됨"
        elif kind in ("EXACTLY_ONE", "AT_LEAST_ONE"):
            if count_max is not None and distinct_count > count_max:
                status, finding = "FAIL", "서로 다른 변형이 허용 개수를 초과"
            elif distinct_count < count_min:
                status, finding = "REVIEW", "필수 문구 미발견 · 미등록/추출 누락 가능성 검토"
            elif candidate:
                status, finding = "REVIEW", "확정 매칭 외 추가 유사·손상 문구 확인 필요"
        elif candidate:
            status, finding = "REVIEW", "선택 문구의 유사 후보 확인 필요"
        results.append({
            "file": filename,
            "rule_id": rule_id,
            "category": rule.get("category", ""),
            "rule_type": kind,
            "condition": rule.get("condition_expression", ""),
            "min_count": count_min,
            "max_count": count_max,
            "found_occurrences": matched_count,
            "distinct_variants": distinct_count,
            "matched_phrase_ids": distinct,
            "review_candidates": [m["extracted"] for m in candidate],
            "applicability": applicability,
            "status": status,
            "finding": finding,
            "source_reference": rule.get("source_reference",""),
        })
    results.extend(_semantic_conflicts(in_file, filename))
    return results


def _semantic_conflicts(matches, filename):
    """Find hard contradictions independently of fuzzy reference matching."""
    results=[]
    texts=[m["extracted"] for m in matches]
    # PDF Korean sentences can include duplicate claims on the front and rear.
    # A clash requires two opposite explicit statements, never just "인덕션".
    positive=[t for t in texts if re.search(r"인덕션\s*(?:사용\s*)?가능|인덕션\s*포함",t)
              and not re.search(r"불가|제외",t)]
    negative=[t for t in texts if re.search(r"인덕션\s*(?:사용\s*)?불가|인덕션\s*제외",t)]
    if positive and negative:
        results.append({
            "file":filename, "rule_id":"P1-HEAT-CONFLICT", "category":"열원",
            "rule_type":"CONFLICT", "condition":"동일 아트웍에서 인덕션 가능/불가 상충 금지",
            "min_count":0,"max_count":1,"found_occurrences":len(positive)+len(negative),
            "distinct_variants":2, "matched_phrase_ids":[], "review_candidates":[],
            "applicability":"APPLICABLE","status":"FAIL",
            "finding":"인덕션 사용 가능·불가 문구 동시 발견",
            "source_reference":"P1 explicit Korean contradiction",
        })
    return results


def summarize_matches(matches, rules):
    files=sorted({m["file"] for m in matches}|{r["file"] for r in rules})
    summaries=[]
    for filename in files:
        mm=[m for m in matches if m["file"]==filename]
        rr=[r for r in rules if r["file"]==filename]
        counts=Counter(m["status"] for m in mm)
        rc=Counter(r["status"] for r in rr)
        summaries.append({
            "file":filename,
            "extracted_count":len(mm),
            "matched_count":counts["EXACT_MATCH"]+counts["NORMALIZED_MATCH"],
            "unregistered_count":counts["UNREGISTERED"],
            "ocr_review_count":counts["OCR_REVIEW"],
            "rule_ok":rc["OK"],"rule_review":rc["REVIEW"],"rule_fail":rc["FAIL"],
            "overall":"FAIL" if rc["FAIL"] else "REVIEW" if rc["REVIEW"] or any(
                k not in ACCEPTED for k in counts) else "OK",
        })
    return summaries
