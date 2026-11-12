"""Project confirmed document-policy findings into the reviewer phrase table.

A document-level FAIL is displayed beside the corresponding source phrase
without overwriting extraction/matching records or editing PDF text.
"""
import re


def phrase_policy_findings(match,results):
    phrase=str(match.get("extracted") or "")
    if not phrase:
        return []
    flags=[]
    for result in results:
        if result.get("file")!=match.get("file") or result.get("status")!="FAIL":
            continue
        code=result.get("rule_id","")
        relevant=False
        if code in ("DOC-NIH-LEGACY","DOC-NIH-MIXED-WORDING"):
            relevant=bool(re.search(r"모든\s*열원\s*사용\s*가능\s*\(\s*인덕션\s*제외\s*\)",phrase))
        elif code in ("DOC-IH-SEMANTIC-CONFLICT","P1-HEAT-CONFLICT",
                      "DOC-IH-EN-KO-MISMATCH"):
            relevant="인덕션" in phrase
        elif code.startswith("DOC-WORLD-"):
            relevant="Euromonitor" in phrase or ("Home and Garden" in phrase and "에디션" in phrase)
        elif code=="DOC-WARRANTY-LANGUAGE":
            relevant="보증" in phrase
        elif code in ("DOC-BILINGUAL-PERCENT","DOC-BILINGUAL-MULTIPLIER"):
            relevant=any(str(e)==phrase for e in result.get("evidence",[]))
        if relevant:
            flags.append(result)
    return flags


def render_policy_status(match,findings,default_status,default_issue):
    """Return a compact human status and the actionable reviewer reason."""
    relevant=phrase_policy_findings(match,findings)
    if not relevant:
        return default_status,default_issue
    reasons=list(dict.fromkeys(str(r.get("finding","")) for r in relevant if r.get("finding")))
    return "수정 필요", " / ".join(reasons)
