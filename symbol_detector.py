"""Candidate emblem/image anchors; absence is never equated with no logo.

Without curated templates and region calibration this module yields REVIEW
rather than reporting false visual OK/FAIL decisions.
"""
import re

ANCHORS = {
    "WORLD_NO1": re.compile(r"WORLD\s*(?:N\s*[°ºo]?\s*1|NO\.?\s*1)|세계판매\s*1위",re.I),
    "RECYCLING": re.compile(r"RECYCLABLE|RECYCLING|재활용\s*가능|적절한\s*분리배출",re.I),
    "MADE_IN_FRANCE": re.compile(r"MADE\s+IN\s+FRANCE",re.I),
}

def inspect_symbols(summaries, metadata):
    output=[]
    for meta in metadata:
        filename=meta["file"]
        raw=[line for s in summaries if s.get("file")==filename
             for line in s.get("raw_evidence",[])]
        for code,pattern in ANCHORS.items():
            anchors=[{"text":line.get("text",""),
                      "bbox":line.get("bbox"),"id":line.get("id")}
                     for line in raw if pattern.search(line.get("text",""))]
            if code=="MADE_IN_FRANCE" and meta.get("manufacturing_country")!="FRANCE":
                continue
            output.append({
                "file":filename,"rule_id":"P1-IMAGE-"+code,
                "category":"이미지·마크","rule_type":"IMAGE_REVIEW",
                "condition":"텍스트 앵커는 시각 엠블럼 존재를 증명하지 않음",
                "min_count":0,"max_count":None,
                "found_occurrences":len(anchors),
                "distinct_variants":int(bool(anchors)),
                "matched_phrase_ids":[],"review_candidates":[],
                "applicability":"UNDETERMINED","status":"REVIEW",
                "finding":("관련 텍스트 후보 발견 · 실제 마크 위치/존재 육안 검증 필요"
                           if anchors else "이미지 마크 자동 인식 미검증 · 수동 확인 필요"),
                "source_reference":"PDF native text anchors",
                "anchor_evidence":anchors,
            })
    return output
