"""Reviewer-facing display labels; never replace source filenames in exports or matching keys."""
TYPE_KO = {
    "SAUCEPAN": "편수냄비", "STEWPOT": "양수냄비", "FRYPAN": "프라이팬",
    "WOK": "볶음팬", "PANCAKE": "팬케이크팬", "SET": "세트",
}

def product_title(metadata):
    """Use PDF-derived details only. Missing values remain explicitly unknown."""
    name = str(metadata.get("range_name") or "").strip()
    if name.upper() in {"UNKNOWN", "NONE", "N/A"}:
        name = ""
    code = str(metadata.get("product_type_standard") or "").upper()
    kind = TYPE_KO.get(code, "")
    size = metadata.get("size_cm")
    size_text = f"{int(size)}cm" if isinstance(size, (float, int)) and size > 0 else ""
    parts = [x for x in (name, kind, size_text) if x]
    return " · ".join(parts) if parts else "제품정보 확인 필요"

def product_labels(metadata, filenames):
    """Keep products distinguishable even when their extracted names coincide."""
    by_file = {m["file"]: product_title(m) for m in metadata}
    titles = {file: by_file.get(file, "제품정보 확인 필요") for file in filenames}
    count = {}
    out = {}
    for file in sorted(titles):
        title = titles[file]
        count[title] = count.get(title, 0) + 1
        out[file] = f"{title} (파일 {count[title]})" if list(titles.values()).count(title) > 1 else title
    return out

def display_file_table(records, labels, file_key="file", label="제품"):
    """Return presentation copies. Source records remain untouched."""
    return [{label: labels.get(r.get(file_key), "제품정보 확인 필요"),
             **{k:v for k,v in r.items() if k != file_key}}
            for r in records]


def readable_ocr_review(match):
    """Presentation-only OCR hint; raw extracted bytes remain in the report.

    A damaged PDF line may contain an OCR candidate that is more legible than
    replacement glyphs. Only surface that candidate with a prominent warning
    and sufficient overlap with the actual readable Korean characters.
    """
    import re
    from difflib import SequenceMatcher
    original = str(match.get("extracted") or "")
    if "\ufffd" not in original:
        return original
    anchor = re.sub(r"[^가-힣]", "", original)
    candidates = match.get("ocr_candidates") or []
    best = ""
    score = 0
    for item in candidates:
        candidate = item.get("text", "") if isinstance(item, dict) else str(item)
        korean = re.sub(r"[^가-힣]", "", candidate)
        if len(korean) < 6 or len(korean) < len(anchor)*0.85:
            continue
        similarity = SequenceMatcher(None, anchor, korean).ratio()
        if similarity > score and similarity >= .78:
            best,score = candidate,similarity
    if best:
        return re.sub(r"\s+", " ", best).strip()
    # Preserve the actual sentence even when OCR has not resolved every glyph.
    return original.replace("\ufffd", "□")


def readable_group(group):
    """Same displayed wording for the review table and the PDF overlay."""
    row = {
        "extracted": group.get("paragraph", group.get("korean_text", "")),
        "status": "OCR_REVIEW" if (group.get("numeric_review")
                                     or "\ufffd" in group.get("paragraph", ""))
                  else "EXACT_MATCH",
        "ocr_candidates": group.get("ocr_candidates", []),
    }
    return readable_ocr_review(row)


def readable_row(row, parent=None):
    """Use parent group OCR-verified warranty numeral in line view too."""
    import re
    text = row.get("korean_text", "")
    if parent and parent.get("ocr_reconstructed"):
        whole = parent.get("paragraph", "")
        if re.search(r"[\ufffd□]{1,4}\s*년간", text):
            observed = re.search(r"(?<!\d)(\d{1,2})\s*년간", whole)
            if observed:
                text = re.sub(r"[\ufffd□]{1,4}\s*년간",
                              observed.group(1) + "년간", text, count=1)
    return readable_ocr_review({
        "status": "OCR_REVIEW" if "\ufffd" in text else "EXACT_MATCH",
        "extracted": text,
        "ocr_candidates": ([{"text": row["ocr_candidate"]}]
                           if row.get("ocr_candidate") else []),
    })


QA_STATUS_KO = {
    "EXACT_MATCH": "기준 문구 일치",
    "NORMALIZED_MATCH": "띄어쓰기·표기 일치",
    "VARIABLE_MATCH": "연도 변수 일치",
    "OCR_REVIEW": "원본 글자 확인 필요",
    "NUMERIC_MISMATCH": "숫자·단위 확인 필요",
    "TEXT_MISMATCH": "문구 차이 확인 필요",
    "UNREGISTERED": "기준 문구 미등록",
    "AMBIGUOUS_MATCH": "복수 기준 후보 확인",
}


def reviewer_status(code):
    return QA_STATUS_KO.get(code, code)
