"""Source-backed English counterparts for the Korean artwork review table.

Only strings visibly present in PDF native text count as extracted English.
The master English translation is never substituted for a missing extraction.
"""
import re

# Avoid claiming that an 'or ...' instruction in the reference workbook is
# one literally printed English sentence.
def _reference_english(text):
    text = str(text or "").strip()
    if not text:
        return ""
    text = re.split(r"\s+(?:or|또는)\s+", text, maxsplit=1, flags=re.I)[0]
    if re.search(r"[가-힣\u0e00-\u0e7f\u0400-\u052f]", text):
        return ""
    return text


def _pattern(value):
    """Keep words/numbers intact; permit printed hyphen-vs-space variants."""
    parts = re.split(r"[-\u2010-\u2015\s]+", value.strip())
    if len(parts) < 2:
        return None
    return re.compile(r"(?<![A-Za-z0-9])" +
                      r"[-\u2010-\u2015\s]+".join(re.escape(t) for t in parts)
                      + r"(?![A-Za-z0-9])", re.I)


def _adjacent(left, right):
    if not left.get("bbox") or not right.get("bbox"):
        return False
    a,b=left["bbox"],right["bbox"]
    if len(a)!=4 or len(b)!=4:
        return False
    same_column=abs(float(a[0])-float(b[0]))<=110
    line_gap=0 <= float(b[1])-float(a[1]) <= 45
    return same_column and line_gap


def find_english_counterpart(match, summaries):
    """Return exact English words observed in the same PDF, or empty string.

    Matching against the master is strictly a search query, never evidence.
    """
    english=_reference_english(match.get("reference_english", ""))
    pattern=_pattern(english)
    if pattern is None:
        return ""
    lines=[
        line for s in summaries
        if s.get("file")==match.get("file")
        for line in s.get("raw_evidence", [])
        if line.get("text") and int(s.get("page",0))==int(match.get("page",0))
    ]
    for line in lines:
        found=pattern.search(line["text"])
        if found:
            return found.group(0)
    # Some multi-line English sentences are split across successive PDF lines.
    # Require visible geometric adjacency; do not join distant page content.
    for i in range(len(lines)-1):
        if not _adjacent(lines[i],lines[i+1]):
            continue
        joined=lines[i]["text"].rstrip()+" "+lines[i+1]["text"].lstrip()
        found=pattern.search(joined)
        if found:
            return found.group(0)
    return ""


def build_reviewer_pairs(matches, summaries, display_text):
    """One bilingual display record for each Korean matching result."""
    output=[]
    for match in matches:
        output.append({
            "file": match.get("file",""),
            "category": match.get("category") or "미분류",
            "korean_extracted": display_text(match),
            "english_extracted": find_english_counterpart(match,summaries),
            "korean_reference": match.get("reference_korean") or "",
            "english_reference": match.get("reference_english") or "",
            "match": match,
        })
    return output
