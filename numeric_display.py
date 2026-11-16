"""Select legible Korean numeric text for the main QA results.

The extractor has already run targeted OCR on damaged native PDF glyphs.
Only candidates with matching surrounding Korean words and numeric units
can replace damaged native text. Otherwise exclude from the clean table
and preserve the original in the downloadable evidence.
"""
import re

BAD = re.compile(r"[\ufffd□]{1,}")
NUMERIC_DAMAGE = re.compile(
    r"[\ufffd□]{1,6}\s*(?:%|/\s*[\ufffd□]{1,6}|배|개|년|위)|"
    r"(?:최대|수납|스테인리스|세계판매)[^\n]{0,60}[\ufffd□]")
DIGIT = re.compile(r"\d+(?:\s*/\s*\d+)?\s*(?:%|배|개|년|위)")
KOREAN = re.compile(r"[가-힣]{2,}")


def _normal(text):
    return re.sub(r"\s+", "", str(text or "")).replace("□", "�")


def _candidate_values(match):
    result = []
    for candidate in match.get("ocr_candidates") or []:
        if isinstance(candidate, dict):
            text = candidate.get("text", "")
        else:
            text = str(candidate)
        if text:
            result.append(text)
    return result


def clean_numeric_reading(match):
    """Return (readable phrase, exclusion reason or None).

    Only one uniquely supported same-language OCR candidate can be promoted.
    Missing OCR, competing numeric readings and damaged OCR are withheld.
    """
    original = str(match.get("extracted") or "")
    if not NUMERIC_DAMAGE.search(original):
        return original, None
    candidates = []
    original_words = KOREAN.findall(original)
    for candidate in _candidate_values(match):
        if BAD.search(candidate) or not DIGIT.search(candidate):
            continue
        candidate_words = KOREAN.findall(candidate)
        # Need overlapping Korean text to prevent borrowing numbers from a
        # neighboring English/French or unrelated Korean printed caption.
        overlap = [word for word in original_words if
                   any(word in other or other in word
                       for other in candidate_words)]
        if not overlap:
            continue
        # Candidate must preserve the intact Korean numeric-unit context.
        native_units = re.findall(r"[\ufffd□]{1,6}\s*(%|배|개|년|위)", original)
        if native_units and not all(re.search(r"\d+\s*"+re.escape(u), candidate)
                                    for u in native_units):
            continue
        candidates.append(candidate.strip())
    distinct = {_normal(c) for c in candidates}
    if len(distinct) == 1:
        chosen = candidates[0]
        # Do not pretend a partly recovered phrase is a verified full
        # transcription; only accept candidates that preserve all readable
        # Korean anchors, with modest tolerance for OCR spacing.
        anchors = [w for w in original_words if len(w) >= 3]
        if all(any(w in cw or cw in w for cw in KOREAN.findall(chosen))
               for w in anchors):
            return chosen, None
    return "", "OCR 숫자 판독 불확실 · 원본 PDF 숫자 확인 필요"
