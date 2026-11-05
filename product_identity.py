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
    """Main QA: compare two independent regions IN the PDF.

    Filename and PRODUIT are supplementary; neither can make front/GAMME
    agreement pass or fail. Uncertain headline extraction is REVIEW.
    """
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

            # G7 is an internal group/version prefix, not part of the
            # range's printable brand name.
            range_text = re.sub(r"^\s*G\s*\d+\s+", "", gamme, flags=re.I).strip()
            expected = normalize(range_text)
            candidates = [
                item for item in lines
                if expected and item["font_size"] >= 12
                and item["direction"][0] > .8
                and not re.match(
                    r"^(?:GAMME|PRODUIT|CLIENT|DOSSIER|ECHELLE|ÉCHELLE)\b",
                    item["text"], re.I
                )
                and SequenceMatcher(None, expected, normalize(item["text"])).ratio() >= .72
            ]
            # Prefer the large, actual front-of-pack heading rather than
            # incidental mentions in a different part of the dieline.
            candidates.sort(key=lambda item: (
                normalize(item["text"]) != expected,
                -item["font_size"],
                item["x0"],
                item["y0"],
            ))
            title = candidates[0] if candidates else None

            if not gamme or not title:
                primary_status = "REVIEW"
            elif normalize(title["text"]) == expected:
                primary_status = "OK"
            else:
                primary_status = "FAIL"

            context = []
            if title:
                nearby = [
                    item for item in lines if item is not title
                    and abs(item["x0"] - title["x0"]) <= max(35, title["font_size"] * 3)
                    and 0 < item["y0"] - title["y0"] <= max(70, title["font_size"] * 3)
                    and item["direction"][0] > .8
                    and item["font_size"] >= title["font_size"] * .7
                ]
                nearby.sort(key=lambda item: item["y0"])
                context = [item["text"] for item in nearby[:2]]

            produit_status = _check_product(ref["product"], ref["size_cm"], produit)
            comparison = [
                ("패키지 전면 영문 제품명", title["text"] if title else "",
                 primary_status, title, True),
                ("작업정보 GAMME", gamme, primary_status,
                 sheet_range[0][0] if sheet_range else None, True),
                ("작업정보 PRODUIT (참고)", produit, produit_status,
                 sheet_product[0][0] if sheet_product else None, False),
            ]
            for field, actual, status, position, is_primary in comparison:
                filename_hint = (
                    ref["range"] if "PRODUIT" not in field else
                    f'{ref["product"]} {ref["size_cm"]} cm'
                    if ref["product"] and ref["size_cm"] else ""
                )
                results.append({
                    "file": filename,
                    "page": page.number + 1,
                    "check": field,
                    "expected_from_filename": filename_hint or "파일명 기준 없음",
                    "comparison_reference": (
                        range_text if "패키지 전면" in field else
                        title["text"] if "GAMME" in field and title else
                        filename_hint
                    ) or "확인 필요",
                    "extracted": actual or "미검출",
                    "status": status,
                    "is_primary": is_primary,
                    "context": " / ".join(context) if "패키지 전면" in field else "",
                    "note": (
                        "주변 광고 문구는 추출만 하며 승인 문구와의 일치 여부는 미판정"
                        if "패키지 전면" in field else
                        "제품 종류·규격은 파일명과 참고 비교, 종합 판정에는 미반영"
                        if "PRODUIT" in field else
                        "GAMME에서 G7 등의 내부 코드 제외 후 전면 제목과 비교"
                    ),
                    "x0": position["x0"] if position else None,
                    "y0": position["y0"] if position else None,
                    "x1": position["x1"] if position else None,
                    "y1": position["y1"] if position else None,
                    "location": (
                        "패키지 전면 큰 제목" if "패키지 전면" in field
                        else "우측 작업정보 " + ("PRODUIT" if "PRODUIT" in field else "GAMME")
                    ),
                })
    finally:
        doc.close()
    return results
