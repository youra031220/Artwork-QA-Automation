"""English artwork title and job-sheet cross-check against the PDF filename.

No AI guessing: a PASS requires matching, independently extracted on-artwork
brand/range and production-sheet product. Supporting marketing copy is shown
as evidence but not approved without a reference text.
"""
import re
from difflib import SequenceMatcher
import fitz
from product_parser import parse_product_pdf

RANGES = {
    "EXPERTISE RUBY": r"EXPERTISE[\s_-]+RUBY",
    "OPTI COOK": r"OPTI[\s_'-]*COOK",
}
PRODUCTS = {
    "WOK": "Wok",
    "FRYPAN": "Frypan",
    "PANCAKE": "Pancake",
}

def normalize(text):
    return re.sub(r"[^a-z0-9]", "", text.casefold())


def filename_reference(filename):
    name = filename.rsplit(".", 1)[0]
    range_name = None
    for label, pattern in RANGES.items():
        if re.search(pattern, name, re.I):
            range_name = label
            break
    product = None
    size = None
    for key, label in PRODUCTS.items():
        match = re.search(r"(?<![A-Za-z])" + key + r"[\s_-]*(\d{2})(?!\d)", name, re.I)
        if match:
            product = label
            size = match.group(1)
            break
    if not product:
        # Short production filenames, e.g. 'F. P.WOK28 - EXPERTISE RUBY'
        m = re.search(r"(?<![A-Za-z])(?:P\.?\s*)?(WOK|P)(\d{2})(?!\d)", name, re.I)
        if m:
            product = "Wok" if m.group(1).upper() == "WOK" else "Frypan"
            size = m.group(2)
    return {"range": range_name, "product": product, "size_cm": size}


def visible_lines(page):
    out = []
    for block in page.get_text("dict", flags=0)["blocks"]:
        for line in block.get("lines", []):
            if not line.get("spans"):
                continue
            raw = "".join(span["text"] for span in line["spans"]).strip()
            if not raw:
                continue
            x0,y0,x1,y1 = line["bbox"]
            out.append({
                "text": re.sub(r"\s+", " ", raw),
                "page": page.number + 1,
                "x0": round(x0, 1), "y0": round(y0, 1),
                "x1": round(x1, 1), "y1": round(y1, 1),
                "font_size": max(float(s["size"]) for s in line["spans"]),
                "direction": line.get("dir", (1, 0)),
            })
    return out


def _find_sheet_value(lines, label):
    """Find labelled GAMME/PRODUIT with value on same or next aligned line."""
    results = []
    regex = re.compile(r"^\s*" + re.escape(label) + r"\b\s*[:\-]?\s*(.*)", re.I)
    for i, item in enumerate(lines):
        m = regex.match(item["text"])
        if not m:
            continue
        value = m.group(1).strip()
        if not value:
            for other in lines:
                if other is item:
                    continue
                if abs(other["y0"] - item["y0"]) <= max(6, item["font_size"]):
                    if other["x0"] >= item["x1"] - 2 and other["x0"] < item["x1"] + 60:
                        value = other["text"].strip()
                        break
        if value:
            results.append((item, value))
    return results


def _check_range(expected, observed):
    if not expected:
        return "REVIEW"
    if not observed:
        return "REVIEW"
    # GAMME often includes 'G7' between the key and range.
    cleaned = re.sub(r"^\s*G\s*\d+\s+", "", observed, flags=re.I)
    return "OK" if normalize(expected) == normalize(cleaned) else "FAIL"


def _check_product(expected_type, size_cm, observed):
    if not expected_type or not size_cm or not observed:
        return "REVIEW"
    # Normalize only common production-sheet synonyms; do not alter printed text.
    text = observed.casefold()
    numbers = re.findall(r"\d+", text)
    if not numbers or numbers[0] != str(int(size_cm)):
        return "FAIL"
    synonyms = {
        "Wok": ("wok",),
        "Frypan": ("frypan", "frying pan", "fry pan", "poêle", "poele"),
        "Pancake": ("pancake", "crepe", "crêpe"),
    }
    return "OK" if any(word in text for word in synonyms[expected_type]) else "FAIL"


def _title_candidate(lines, reference, job_box):
    """Locate the actual package range title, never a production ticket label.

    When an internal job-sheet suffix (e.g. UNCOATED) is not on the front,
    identify the printed shorter title but return REVIEW rather than OK.
    """
    normalized = normalize(reference)
    if not normalized:
        return None
    rejected = re.compile(
        r"^(?:NOM GAMME|GAMME|DESCRIPTION|PRODUIT|CLIENT|DOSSIER|"
        r"ECHELLE|ÉCHELLE|CMMF|MADE IN|FABRIQU)", re.I
    )
    candidates = []
    for line in lines:
        value = normalize(line["text"])
        if not value or rejected.match(line["text"]):
            continue
        if job_box and line["page"] == job_box["page"]:
            coords = (line["x0"], line["y0"], line["x1"], line["y1"])
            if (abs(coords[0] - job_box["bbox"][0]) < 5
                    and abs(coords[1] - job_box["bbox"][1]) < 5):
                continue
        ratio = SequenceMatcher(None, normalized, value).ratio()
        # A shortened front range title is evidence, not an exact match.
        if ratio < .62 and not (len(value) >= 8 and
                                (value in normalized or normalized in value)):
            continue
        if line["font_size"] < 7 or line["direction"][0] <= .5:
            continue
        is_exact = value == normalized
        subset = len(value) >= 8 and value in normalized
        candidates.append((
            200 if is_exact else 100 if subset else 0,
            ratio, line["font_size"], line
        ))
    if not candidates:
        return None
    candidates.sort(key=lambda c: (c[0], c[1], c[2]), reverse=True)
    return candidates[0][3]


def check_product_identity(pdf_bytes, filename):
    """Cross-check printed front title against independent work-info metadata.

    Use the same geometry-aware parsing as product metadata, not a global
    'GAMME' regex that might match French legal disclaimers.
    """
    ref = filename_reference(filename)
    metadata = parse_product_pdf(pdf_bytes, filename)
    gamme = metadata.get("range_name") or ""
    produit = metadata.get("product_type_raw") or ""
    sheet_range_ev = (metadata.get("evidence", {}).get("range_name") or [None])[0]
    sheet_prod_ev = (metadata.get("evidence", {}).get("product_type_raw") or [None])[0]
    results = []
    with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
        for page in doc:
            lines = visible_lines(page)
            title = _title_candidate(lines, gamme, sheet_range_ev) if page.number == 0 else None
            if not gamme or title is None:
                primary = "REVIEW"
            elif normalize(title["text"]) == normalize(gamme):
                primary = "OK"
            elif normalize(title["text"]) in normalize(gamme):
                # e.g. job info ESSENTIAL START UNCOATED / printed ESSENTIAL START
                primary = "REVIEW"
            else:
                primary = "FAIL"
            product_status = _check_product(ref["product"], ref["size_cm"], produit)
            comparisons = [
                ("패키지 전면 영문 제품명", title["text"] if title else "",
                 primary, title, True, "패키지 전면 큰 제목"),
                ("작업정보 GAMME", gamme, primary, sheet_range_ev, True, "작업정보 GAMME"),
                ("작업정보 PRODUIT (참고)", produit, product_status,
                 sheet_prod_ev, False, "작업정보 PRODUIT"),
            ]
            for field, actual, status, evidence, is_primary, location in comparisons:
                if is_primary and status == "REVIEW" and gamme and title:
                    note = "전면 표기와 제작정보 간 수식어/철자 차이: 승인된 표기 기준 확인 필요"
                elif is_primary:
                    note = "PDF 전면과 작업정보의 직접 대조; 파일명은 판정에서 제외"
                else:
                    note = "파일명은 참고용이며 주 판정에 미반영"
                if evidence and "bbox" in evidence:
                    x0, y0, x1, y1 = evidence["bbox"]
                elif evidence:
                    x0, y0, x1, y1 = (
                        evidence["x0"], evidence["y0"],
                        evidence["x1"], evidence["y1"]
                    )
                else:
                    x0 = y0 = x1 = y1 = None
                results.append({
                    "file": filename, "page": page.number + 1,
                    "check": field, "expected_from_filename": (
                        ref["range"] or "파일명 기준 없음"),
                    "comparison_reference": (
                        gamme if "패키지 전면" in field else
                        (title["text"] if title else "확인 필요")
                        if "GAMME" in field else
                        (f'{ref["product"]} {ref["size_cm"]} cm'
                         if ref["product"] and ref["size_cm"] else "파일명 기준 없음")
                    ),
                    "extracted": actual or "미검출", "status": status,
                    "is_primary": is_primary, "context": "", "note": note,
                    "x0": x0, "y0": y0, "x1": x1, "y1": y1,
                    "location": location,
                })
    return results
