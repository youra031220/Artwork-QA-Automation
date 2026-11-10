"""Read user-uploaded artwork reference Excel into reproducible P0 data models.

Only Python stdlib: no remote calls, no persistence, no edits to the workbook.
"""
from collections import defaultdict
from dataclasses import asdict, dataclass
import io
import re
from xml.etree import ElementTree as ET
from zipfile import ZipFile

NS = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
      "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships"}
MAIN = "{" + NS["x"] + "}"


@dataclass
class Phrase:
    phrase_id: str
    category_id: str
    english_original: str
    korean_original: str
    remark_original: str
    source_sheet: str
    source_row: int
    approval_status: str = "UNVERIFIED"
    parse_status: str = "PARSED"


@dataclass
class Rule:
    rule_id: str
    category: str
    rule_type: str
    min_count: int
    max_count: int | None
    required: bool
    condition_expression: str
    scope: str
    source_reference: str


@dataclass
class Variant:
    variant_id: str
    rule_id: str
    phrase_id: str
    english_pattern: str
    korean_pattern: str
    variable_definitions: list
    applicability: str
    notes: str


def _column(cell_ref):
    letters = re.match(r"[A-Z]+", cell_ref).group()
    value = 0
    for letter in letters:
        value = value * 26 + ord(letter) - 64
    return value


def _read_xlsx(upload):
    """Return sheet_name -> sparse {row -> {col -> value}}, and merged regions."""
    raw = upload if isinstance(upload, bytes) else upload.read()
    with ZipFile(io.BytesIO(raw)) as z:
        book = ET.fromstring(z.read("xl/workbook.xml"))
        relroot = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
        targets = {r.attrib["Id"]: r.attrib["Target"] for r in relroot}
        strings = []
        if "xl/sharedStrings.xml" in z.namelist():
            root = ET.fromstring(z.read("xl/sharedStrings.xml"))
            for item in root.findall("x:si", NS):
                strings.append("".join(n.text or "" for n in item.iter(MAIN + "t")))
        sheets = {}
        for sheet in book.find("x:sheets", NS):
            name = sheet.attrib["name"]
            ref = sheet.attrib["{" + NS["r"] + "}id"]
            path = targets[ref].lstrip("/")
            if not path.startswith("xl/"):
                path = "xl/" + path
            tree = ET.fromstring(z.read(path))
            cells = defaultdict(dict)
            for cell in tree.findall(".//x:sheetData/x:row/x:c", NS):
                coordinate = cell.attrib["r"]
                row_num = int(re.search(r"\d+", coordinate).group())
                col_num = _column(coordinate)
                inline = cell.find("x:is", NS)
                value = cell.find("x:v", NS)
                if inline is not None:
                    text_value = "".join(el.text or "" for el in inline.iter(MAIN + "t"))
                elif value is None:
                    text_value = ""
                elif cell.attrib.get("t") == "s":
                    text_value = strings[int(value.text)]
                else:
                    text_value = value.text or ""
                cells[row_num][col_num] = text_value
            merges = [el.attrib["ref"] for el in tree.findall(".//x:mergeCell", NS)]
            sheets[name] = (cells, merges)
    return sheets


def _rule_spec(category, condition, source_row):
    rule_type, min_count, max_count = "OPTIONAL", 0, None
    cond = re.sub(r"\s+", "", condition).upper().replace("≥", ">=")
    if "조건부" in condition:
        rule_type, min_count, max_count = "CONDITIONAL", 1, 1
    elif "모든 문장" in condition or re.search(r"X\s*=\s*4", condition, re.I):
        rule_type, min_count, max_count = "ALL_REQUIRED", 4, 4
    elif re.search(r"X>=1", cond):
        rule_type, min_count, max_count = "AT_LEAST_ONE", 1, None
    elif re.search(r"X=1", cond):
        rule_type, min_count, max_count = "EXACTLY_ONE", 1, 1
    elif "대조 문구 있을 때" in condition:
        rule_type, min_count, max_count = "IF_PRESENT", 0, None
    elif "없어도" in condition:
        rule_type, min_count, max_count = "OPTIONAL", 0, None
    elif "반드시" in condition:
        rule_type, min_count, max_count = "AT_LEAST_ONE", 1, None
    return rule_type, min_count, max_count


def _variables(english, korean, remark):
    variables = []
    # YX is an artwork performance multiplier, not the X=1 cardinality.
    if re.search(r"\bYX\b", english, re.I) or "Y배" in korean or "Y= 숫자" in remark:
        variables.append({"name": "Y", "dtype": "integer", "unit_en": "X",
                          "unit_ko": "배", "range": None})
    if re.search(r"\bX\s*(?:=|>=|≥)\s*\d", remark):
        variables.append({"name": "X", "dtype": "integer", "role": "count_or_edition",
                          "range": None, "requires_review": True})
    for token, unit in [(r"\b\d+\s*cm\b", "cm"),
                        (r"\b\d+\s*%", "%"), (r"\b\d+\s*(?:years?|년)\b", "year")]:
        if re.search(token, english + " " + korean, re.I):
            variables.append({"name": "literal", "dtype": "number", "unit": unit})
    return variables


def _applicability(remark):
    """Parse only deterministic constraints; keep other prose for human review."""
    text = re.sub(r"\s+", "", remark)
    if "유리뚜껑" in text:
        if "없을경우" in text or "미포함" in text:
            return "lid_material != glass"
        if "있을경우" in text or "포함" in text:
            return "lid_material == glass"
    if "18cm" in text and "뚝배기" in text:
        return "size_cm == 18"
    return "REQUIRES_REVIEW" if remark else ""


def parse_reference_excel(upload):
    """Build phrase/rule/variant/issue tables from source Excel without inventing approvals."""
    sheets = _read_xlsx(upload)
    sheet_name = "텍스트 대조 데이터"
    if sheet_name not in sheets:
        raise ValueError("텍스트 대조 데이터 시트를 찾지 못했습니다.")
    rows, merges = sheets[sheet_name]
    phrases, rules, variants, issues = [], [], [], []
    active_category = None
    active_rule = None
    rule_index = 0
    name_count = defaultdict(int)
    duplicate_pairs = defaultdict(list)
    english_ko = defaultdict(set)

    def issue(row_num, code, detail, action="담당자 확인"):
        issues.append({"source_sheet": sheet_name, "source_row": row_num,
                       "issue_type": code, "detail": detail, "action": action})

    for row_num in sorted(rows):
        if row_num <= 5:
            continue
        cells = rows[row_num]
        category = str(cells.get(2, "") or "").strip()
        condition = str(cells.get(3, "") or "").strip()
        english = str(cells.get(4, "") or "").strip()
        korean = str(cells.get(5, "") or "").strip()
        remark = str(cells.get(6, "") or "").strip()
        if category:
            active_category = category
            rule_index += 1
            active_rule = None
        if condition:
            if active_category is None:
                issue(row_num, "MISSING_CATEGORY", condition)
            rule_index += 1 if not category else 0
            rule_type, min_count, max_count = _rule_spec(active_category or "", condition, row_num)
            active_rule = "R" + str(row_num)
            rules.append(asdict(Rule(
                active_rule, active_category or "UNKNOWN",
                rule_type, min_count, max_count, min_count > 0,
                condition, "distinct_variants", sheet_name + "!C" + str(row_num)
            )))
            if rule_type == "OPTIONAL" and not any(k in condition for k in ("없어도", "대조 문구", "필수")):
                issue(row_num, "UNPARSED_CONDITION", condition)
        if not english and not korean:
            continue
        if active_category is None:
            issue(row_num, "MISSING_CATEGORY", english[:70])
            active_category = "UNKNOWN"
        if active_rule is None:
            active_rule = "R" + str(row_num)
            rules.append(asdict(Rule(active_rule, active_category,
                                     "OPTIONAL", 0, None, False, "",
                                     "distinct_variants", sheet_name + "!C" + str(row_num))))
        key = "P" + str(row_num)
        phrases.append(asdict(Phrase(
            key, active_category, english, korean, remark, sheet_name, row_num,
            parse_status="PARSED" if english and korean else "INCOMPLETE"
        )))
        variants.append(asdict(Variant(
            "V" + str(row_num), active_rule, key, english, korean,
            _variables(english, korean, remark), _applicability(remark),
            remark
        )))
        if not english or not korean:
            issue(row_num, "MISSING_TRANSLATION", english or korean)
        if english and korean:
            pair = (re.sub(r"\s+", " ", english).casefold(), re.sub(r"\s+", " ", korean))
            duplicate_pairs[pair].append(row_num)
            english_ko[pair[0]].add(pair[1])

    for pair, locations in duplicate_pairs.items():
        if len(locations) > 1:
            issue(locations[0], "DUPLICATE_PAIR",
                  "동일 문구 쌍: " + ", ".join(map(str, locations)))
    for en, translations in english_ko.items():
        if len(translations) > 1:
            matching = [p["source_row"] for p in phrases if
                        re.sub(r"\s+", " ", p["english_original"]).casefold() == en]
            issue(matching[0], "AMBIGUOUS_TRANSLATION",
                  "영문 하나에 복수 국문: " + ", ".join(map(str, matching)))

    for record in variants:
        remark = record["notes"]
        if remark and any(w in remark for w in ("경우", "변수", "숫자")):
            issue(int(record["phrase_id"][1:]), "REMARK_REVIEW", remark[:160])
    return {"phrases": phrases, "rules": rules, "variants": variants,
            "validation_issues": issues, "source_sheet": sheet_name,
            "merged_ranges": merges}
