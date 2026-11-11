"""Source-grounded bilingual presence checks for embedded reference pairs.

Never claim a missing translation from a fuzzy English match or OCR text.
"""
import re
from phrase_matcher import compact

TRIGGER_MIN = 12

def _english_normalize(value):
    return re.sub(r"\s+", " ", str(value or "")).strip().casefold()

def evaluate_bilingual(master, matches, summaries, filename):
    raw = " ".join(
        line.get("text","") for summary in summaries
        if summary.get("file") == filename
        for line in summary.get("raw_evidence", [])
    )
    raw_norm = _english_normalize(raw)
    present_korean = {
        m.get("phrase_id") for m in matches
        if m.get("file")==filename
        and m.get("status") in ("EXACT_MATCH", "NORMALIZED_MATCH")
    }
    results=[]
    for phrase in master.get("phrases", []):
        english=phrase.get("english_original","").strip()
        korean=phrase.get("korean_original","").strip()
        if len(english)<TRIGGER_MIN or not korean:
            continue
        # Source strings are sometimes placeholders or alternate translations;
        # do not convert them into hard missing-Korean failures.
        if re.search(r"\b(?:Y\s*X|X\s*=|PLACEHOLDER)\b",english,re.I):
            continue
        en=_english_normalize(english)
        if en not in raw_norm:
            continue
        if phrase["phrase_id"] in present_korean:
            status="OK"
            finding="원장 영문과 대응 국문 모두 발견 (최종 승인 의미 아님)"
        else:
            status="REVIEW"
            finding="영문은 발견됐으나 해당 원장 국문이 확정 매칭되지 않음"
        results.append({
            "file":filename, "rule_id":"P1-BILINGUAL-"+phrase["phrase_id"],
            "category":phrase.get("category_id",""),
            "rule_type":"IF_PRESENT","condition":"영문 발견 시 대응 국문 대조",
            "min_count":0,"max_count":None,"found_occurrences":1,
            "distinct_variants":1,"matched_phrase_ids":[phrase["phrase_id"]] if status=="OK" else [],
            "review_candidates":[korean] if status=="REVIEW" else [],
            "applicability":"APPLICABLE","status":status,
            "finding":finding,"source_reference":str(phrase.get("source_sheet",""))+
            "!E"+str(phrase.get("source_row","")),
            "reference_english":english,"reference_korean":korean,
            "approval_status":phrase.get("approval_status","UNVERIFIED"),
        })
    return results
