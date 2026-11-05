"""English artwork title and job-sheet cross-check against the PDF filename.

No AI guessing: a PASS requires matching, independently extracted on-artwork
brand/range and production-sheet product. Supporting marketing copy is shown
as evidence but not approved without a reference text.
"""
import re
from difflib import SequenceMatcher
import fitz

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


def check_product_identity(pdf_bytes, filename):
    ref = filename_reference(filename)
    results = []
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    try:
        for page in doc:
            lines = visible_lines(page)
            sheet_range = _find_sheet_value(lines, "GAMME")
            sheet_product = _find_sheet_value(lines, "PRODUIT")
            gamme = sheet_range[0][1] if sheet_range else ""
            produit = sheet_product[0][1] if sheet_product else ""
            gamme_status = _check_range(ref["range"], gamme)
            produit_status = _check_product(ref["product"], ref["size_cm"], produit)

            # The title printed in the marketing artwork is distinct from the
            # small-font job sheet. Check the headline itself, not just GAMME.
            expected = normalize(ref["range"] or "")
            title_candidates = [
                x for x in lines
                if x["font_size"] >= 12 and
                not re.match(r"^(?:GAMME|PRODUIT|CLIENT|DOSSIER)\b", x["text"], re.I) and
                x["direction"][0] > 0.8 and
                (expected and (
                    expected in normalize(x["text"]) or
                    SequenceMatcher(None, expected, normalize(x["text"])).ratio() >= .78
                ))
            ]
            title_candidates.sort(
                key=lambda x: (
                    normalize(x["text"]) != expected,
                    -x["font_size"],
                    x["y0"],
                )
            )
            title = title_candidates[0] if title_candidates else None
            title_status = "OK" if title and normalize(title["text"]) == expected else (
                "FAIL" if title else "REVIEW"
            )
            # Capture neighboring lines as *context*, without pretending that
            # filename comparison validates marketing tagline spelling.
            context = []
            if title:
                nearby = [
                    x for x in lines if x is not title and
                    abs(x["x0"] - title["x0"]) <= max(35, title["font_size"] * 3) and
                    0 < x["y0"] - title["y0"] <= max(70, title["font_size"] * 3) and
                    x["direction"][0] > .8 and x["font_size"] >= title["font_size"] * .7
                ]
                nearby.sort(key=lambda x: x["y0"])
                context = [x["text"] for x in nearby[:2]]

            for field, actual, status, position in [
                ("패키지 전면 영문 제품명", title["text"] if title else "", title_status, title),
                ("작업정보 GAMME", gamme, gamme_status, sheet_range[0][0] if sheet_range else None),
                ("작업정보 PRODUIT", produit, produit_status, sheet_product[0][0] if sheet_product else None),
            ]:
                expected_value = (
                    ref["range"] if field != "작업정보 PRODUIT"
                    else (f'{ref["product"]} {ref["size_cm"]} cm'
                          if ref["product"] and ref["size_cm"] else "")
                )
                results.append({
                    "file": filename, "page": page.number + 1, "check": field,
                    "expected_from_filename": expected_value or "파일명에서 식별 불가",
                    "extracted": actual or "미검출", "status": status,
                    "context": " / ".join(context) if field == "패키지 전면 영문 제품명" else "",
                    "note": ("주변 카피는 추출만 함; 승인 원문 미제공으로 철자 판정 불가"
                             if field == "패키지 전면 영문 제품명" else ""),
                    "x0": position["x0"] if position else None,
                    "y0": position["y0"] if position else None,
                    "x1": position["x1"] if position else None,
                    "y1": position["y1"] if position else None,
                    "location": ("패키지 전면 큰 제목" if field == "패키지 전면 영문 제품명"
                                 else "우측 작업정보 " + field.split()[-1]),
                })
    finally:
        doc.close()
    return results
