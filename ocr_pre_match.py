"""Promote corroborated OCR readings before phrase matching.

Keep the native PDF text in original_paragraph and source coordinates.
Only repair Unicode replacement glyphs when a single OCR reading preserves
the Korean content. Numeric discrepancies remain in review.
"""
import re
from difflib import SequenceMatcher

BAD = re.compile(r"[\ufffd□]")
HANGUL = re.compile(r"[가-힣]")
NUMERIC_HOLE = re.compile(r"[\ufffd□]{1,5}\s*(?:%|/\s*[\ufffd□]|배|개|년|위)")
NUMBERS = re.compile(r"\d+(?:\s*/\s*\d+)?\s*(?:%|배|개|년|위)")


def prepare_ocr_groups(groups):
    output = []
    for group in groups:
        item = dict(group)
        original = str(item.get("paragraph", ""))
        if not BAD.search(original):
            output.append(item)
            continue
        anchor = "".join(HANGUL.findall(original))
        candidates = []
        for entry in item.get("ocr_candidates") or []:
            value = str(entry.get("text", "") if isinstance(entry, dict) else entry).strip()
            if BAD.search(value) or not value:
                continue
            observed = "".join(HANGUL.findall(value))
            if len(anchor) < 5 or len(observed) < len(anchor) * .85:
                continue
            if SequenceMatcher(None, anchor, observed).ratio() < .93:
                continue
            if NUMERIC_HOLE.search(original):
                # Numeric OCR cannot be treated as verified when several
                # numbers or units are missing or the reading is ambiguous.
                if not NUMBERS.search(value):
                    continue
            candidates.append(value)
        unique = {re.sub(r"\s+", "", c) for c in candidates}
        if len(unique) != 1:
            output.append(item)
            continue
        candidate = candidates[0]
        # A clean OCR transcription with the same readable Korean content
        # can resolve corrupted whitespace, but never auto-approve an
        # independently damaged numeric assertion.
        numeric_damaged = bool(NUMERIC_HOLE.search(original))
        item["original_paragraph"] = item.get("original_paragraph", original)
        item["paragraph"] = candidate
        item["ocr_reconstructed"] = True
        item["ocr_pre_match"] = True
        if not numeric_damaged and not item.get("numeric_review"):
            item["numeric_review"] = False
            item["status"] = "OCR 글자 재검증 · 기준 대조 가능"
        output.append(item)
    return output
