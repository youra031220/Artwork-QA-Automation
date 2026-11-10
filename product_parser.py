"""Extract structured product metadata from multiple artwork agency layouts.

Keep PDF evidence and do not treat company addresses as origin of manufacture.
"""
import re
from difflib import SequenceMatcher
import fitz

LABELS = {
    "range_name": ("NOM GAMME", "GAMME"),
    "product_type_raw": ("DESCRIPTION", "PRODUIT"),
    "dossier": ("DOSSIER",),
    "scale": ("ECHELLE", "ÉCHELLE"),
    "client": ("CLIENT",),
}
TYPES = {
    "STEWPOT": (r"\bfaitout\b", r"\bstewpot\b", r"\b양수냄비\b"),
    "SAUCEPAN": (r"\bcasserole\b", r"\bsaucepan\b", r"\b편수냄비\b"),
    "FRYPAN": (r"\bpo[eê]le\b", r"\bfry\s?pan\b", r"\bfrying\s+pan\b", r"프라이팬"),
    "WOK": (r"\bwok\b", r"볶음팬"),
    "PANCAKE": (r"\bcr[eê]pi[eè]re\b", r"\bpancake\b", r"팬케이크"),
}
COUNTRIES = {
    "FRANCE": r"(?:MADE IN|FABRIQU[EÉ]\s+EN|HECHO EN)\s+FRANCE\b",
    "VIETNAM": r"(?:MADE IN|FABRIQU[EÉ]\s+AU|HECHO EN)\s+VIETNAM\b",
    "CHINA": r"(?:MADE IN|FABRIQU[EÉ]\s+EN|HECHO EN)\s+CHINA\b",
}
HEATS = {
    "EXCEPT_INDUCTION": r"ALL\s+HOBS\s+EXCEPT\s+INDUCTION|인덕션\s*사용\s*불가",
    "WITH_INDUCTION": r"ALL\s+HOBS\s*\+\s*INDUCTION|TOUS\s+FEUX\s*\+\s*INDUCTION|인덕션\s*포함\s*모든\s*열원",
    "HOBS_ONLY": r"ALL\s+HOBS(?!\s*(?:EXCEPT|\+))",
}


def _lines(page):
    result = []
    for block in page.get_text("dict", flags=0).get("blocks", []):
        for line in block.get("lines", []):
            spans = line.get("spans", [])
            text = "".join(s.get("text", "") for s in spans).strip()
            if not text:
                continue
            x0, y0, x1, y1 = line["bbox"]
            result.append({"text": re.sub(r"\s+", " ", text),
                           "page": page.number + 1,
                           "x0": float(x0), "y0": float(y0),
                           "x1": float(x1), "y1": float(y1),
                           "font_size": max(float(s["size"]) for s in spans)})
    return result


def _evidence(line, source="pdf"):
    return {"original_text": line["text"], "source": source,
            "page": line["page"], "bbox": [round(line[k], 2) for k in ("x0","y0","x1","y1")],
            "confidence": "native_text"}


def _field(lines, labels, page_width, page_height):
    # Work-ticket labels live in the top area, not body copy where e.g.
    # 'gamme' could occur as a French word in marketing footnotes.
    candidates = []
    for line in lines:
        if line["y0"] > page_height * .22:
            continue
        for label in labels:
            match = re.match(r"^\s*" + re.escape(label) + r"\s*[:：-]?\s*(.*)$",
                             line["text"], re.I)
            if not match:
                continue
            tail = match.group(1).strip()
            if tail:
                candidates.append((line, tail, line))
            else:
                peers = [other for other in lines
                         if other is not line
                         and abs(other["y0"] - line["y0"]) <= max(line["font_size"] * 1.5, 9)
                         and 0 <= other["x0"] - line["x1"] <= page_width * .24]
                if peers:
                    other = sorted(peers, key=lambda p: p["x0"] - line["x1"])[0]
                    candidates.append((line, other["text"], other))
            break
    if not candidates:
        return None, None
    label_line, value, value_line = min(candidates, key=lambda x: x[0]["y0"])
    return value, _evidence(value_line)


def _first_match(lines, pattern, ignore_case=True):
    flags = re.I if ignore_case else 0
    for line in lines:
        match = re.search(pattern, line["text"], flags)
        if match:
            return match, line
    return None, None


def _normalize_type(text):
    for code, patterns in TYPES.items():
        if any(re.search(pattern, text, re.I) for pattern in patterns):
            return code
    return "UNKNOWN"


def parse_product_pdf(pdf_bytes, filename):
    result = {
        "file": filename, "cmmf": None, "dossier": None, "range_name": None,
        "product_type_raw": None, "product_type_standard": "UNKNOWN",
        "size_cm": None, "capacity_l": None, "has_lid": None,
        "lid_material": "unknown", "manufacturing_country": None,
        "induction_compatible": None, "material": None, "production_agency": None,
        "scale": None, "client": None, "evidence": {}, "uncertain_fields": []
    }
    with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
        lines = []
        for page in doc:
            page_lines = _lines(page)
            lines.extend(page_lines)
            if page.number != 0:
                continue
            for field, labels in LABELS.items():
                value, evidence = _field(page_lines, labels, page.rect.width, page.rect.height)
                if value:
                    result[field] = value
                    result["evidence"][field] = [evidence]
        if result["range_name"]:
            result["range_name"] = re.sub(
                r"^\s*G\s*\d+\s+", "", result["range_name"], flags=re.I).strip()
        if result["product_type_raw"]:
            raw = result["product_type_raw"]
            result["product_type_standard"] = _normalize_type(raw)
            cm = re.search(r"(?<!\d)(\d{2})\s*cm\b", raw, re.I)
            if cm:
                result["size_cm"] = int(cm.group(1))
                result["evidence"]["size_cm"] = result["evidence"]["product_type_raw"]
            result["has_lid"] = bool(re.search(r"\+\s*CV\b|\bWITH\s+LID\b|\bAVEC\s+COUVERCLE\b", raw, re.I))
            result["evidence"]["has_lid"] = result["evidence"]["product_type_raw"]
        if result["product_type_standard"] == "UNKNOWN":
            result["uncertain_fields"].append("product_type_standard")

        # CMMF is often far from the agency ticket; never read from filename.
        m, line = _first_match(lines, r"\bCMMF\s*[:#]?\s*(\d{8,12})\b")
        if m:
            result["cmmf"] = m.group(1)
            result["evidence"]["cmmf"] = [_evidence(line)]

        if not result["size_cm"]:
            m, line = _first_match(lines, r"[Ø⌀]\s*(\d{2})\s*cm\b")
            if m:
                result["size_cm"] = int(m.group(1))
                result["evidence"]["size_cm"] = [_evidence(line)]
        # Capacity: accept the typographic 'Ø size - volume L' line only,
        # never the warranty footnote or international address.
        cap_matches = []
        for line in lines:
            m = re.search(r"(?:[Ø⌀]\s*\d{2}\s*cm[^\n]{0,20}[-–]\s*|\b)(\d{1,2}[,.]\d)\s*L\b", line["text"], re.I)
            if m and (("Ø" in line["text"] or "⌀" in line["text"]) or re.search(r"\b\d{1,2}[,.]\d\s*L\s*[-–]\s*\d", line["text"])):
                cap_matches.append((float(m.group(1).replace(",", ".")), line))
        if cap_matches:
            vals = sorted(set(v for v, _ in cap_matches))
            if len(vals) == 1:
                result["capacity_l"] = vals[0]
                result["evidence"]["capacity_l"] = [_evidence(cap_matches[0][1])]
            else:
                result["uncertain_fields"].append("capacity_l")

        origins = {}
        for country, pattern in COUNTRIES.items():
            for line in lines:
                if re.search(pattern, line["text"], re.I):
                    origins.setdefault(country, []).append(_evidence(line))
        if len(origins) == 1:
            result["manufacturing_country"] = next(iter(origins))
            result["evidence"]["manufacturing_country"] = next(iter(origins.values()))
        elif len(origins) > 1:
            result["uncertain_fields"].append("manufacturing_country: conflicting origin declarations")
        else:
            result["uncertain_fields"].append("manufacturing_country: declaration not found")

        heats = {}
        for code, pattern in HEATS.items():
            for line in lines:
                if re.search(pattern, line["text"], re.I):
                    heats.setdefault(code, []).append(_evidence(line))
        # HOBS_ONLY is ambiguous unless confirmed with an approved source.
        if len(heats) == 1 and "HOBS_ONLY" not in heats:
            result["induction_compatible"] = "WITH_INDUCTION" in heats
            result["evidence"]["induction_compatible"] = next(iter(heats.values()))
        elif len(heats) > 1:
            result["uncertain_fields"].append("induction_compatible: conflicting variants")
        elif heats:
            result["uncertain_fields"].append("induction_compatible: ambiguous ALL HOBS")
        else:
            result["uncertain_fields"].append("induction_compatible: not found")

        if any(re.search(r"18/10\s*(?:STAINLESS\s+STEEL|스테인리스)", x["text"], re.I) for x in lines):
            result["material"] = "18/10 STAINLESS STEEL"
        elif any(re.search(r"\bSTAINLESS\s+STEEL\b", x["text"], re.I) for x in lines):
            result["material"] = "STAINLESS STEEL"
        for label, pattern in [("Publicis", r"Publicis"),
                               ("Texto", r"Agence\s+Texto")]:
            if any(re.search(pattern, x["text"], re.I) for x in lines):
                result["production_agency"] = label
                break

        if not result["range_name"]:
            result["uncertain_fields"].append("range_name")
        if not result["cmmf"]:
            result["uncertain_fields"].append("cmmf")
    result["parse_status"] = "REVIEW" if result["uncertain_fields"] else "EXTRACTED"
    return result
