"""Synthetic P0 tests; no company PDFs or Excel files included."""
import io
import unittest
from zipfile import ZipFile
import fitz
from excel_loader import parse_reference_excel
from product_parser import parse_product_pdf


def sample_excel():
    buf = io.BytesIO()
    ns = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    def c(ref, text):
        return '<c r="' + ref + '" t="inlineStr"><is><t>' + text.replace("&", "&amp;").replace("<", "&lt;") + '</t></is></c>'
    workbook = '<workbook xmlns="' + ns + '" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="텍스트 대조 데이터" sheetId="1" r:id="rId1"/></sheets></workbook>'
    rels = '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Target="worksheets/sheet1.xml" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet"/></Relationships>'
    rows = [
        '<row r="6">' + c("B6", "키 메세지") + c("C6", "필수 (X=1)") + c("D6", "Easy cooking") + c("E6", "쉬운 요리") + '</row>',
        '<row r="7">' + c("D7", "Good handle") + c("E7", "좋은 손잡이") + '</row>',
        '<row r="8">' + c("B8", "사용가능 열원") + c("C8", "필수 (X=1)") + c("D8", "ALL HOBS + INDUCTION") + c("E8", "인덕션 포함") + '</row>',
    ]
    sheet = '<worksheet xmlns="' + ns + '"><sheetData>' + "".join(rows) + '</sheetData></worksheet>'
    with ZipFile(buf, "w") as z:
        z.writestr("xl/workbook.xml", workbook)
        z.writestr("xl/_rels/workbook.xml.rels", rels)
        z.writestr("xl/worksheets/sheet1.xml", sheet)
    return buf.getvalue()


def sample_pdf(style):
    doc = fitz.open()
    page = doc.new_page(width=720, height=980)
    if style == "texto":
        data = [
            (30, 40, "NOM GAMME"), (180, 40, "Sample Range"),
            (30, 55, "DESCRIPTION"), (180, 55, "Faitout 24 cm + CV"),
            (30, 70, "DOSSIER"), (180, 70, "CST 13 26 0129"),
            (300, 120, "CMMF 1234567890"),
            (240, 300, "MADE IN CHINA"),
            (240, 330, "ALL HOBS EXCEPT INDUCTION"),
            (240, 365, "5,2 L - 4"),
        ]
    else:
        data = [
            (30, 40, "GAMME G7 SAMPLE SERIES"),
            (30, 55, "PRODUIT"), (180, 55, "CASSEROLE 16 cm + CV"),
            (250, 180, "CMMF 1234567891"),
            (250, 270, "FABRIQUE AU VIETNAM - MADE IN VIETNAM"),
            (250, 320, "ALL HOBS + INDUCTION"),
            (250, 365, "1,7 L - 1"),
        ]
    for x, y, text in data:
        page.insert_text((x, y), text, fontsize=10)
    result = doc.tobytes()
    doc.close()
    return result


class P0Tests(unittest.TestCase):
    def test_excel_inherits_category_and_tracks_rows(self):
        data = parse_reference_excel(sample_excel())
        self.assertEqual(len(data["phrases"]), 3)
        self.assertEqual(data["phrases"][1]["category_id"], "키 메세지")
        self.assertEqual(data["phrases"][1]["source_row"], 7)
        self.assertEqual(len(data["rules"]), 2)
        self.assertEqual(data["rules"][0]["rule_type"], "EXACTLY_ONE")

    def test_texto_layout(self):
        result = parse_product_pdf(sample_pdf("texto"), "fixture.pdf")
        self.assertEqual(result["range_name"].casefold(), "sample range")
        self.assertEqual(result["product_type_standard"], "STEWPOT")
        self.assertEqual(result["size_cm"], 24)
        self.assertTrue(result["has_lid"])
        self.assertEqual(result["manufacturing_country"], "CHINA")
        self.assertFalse(result["induction_compatible"])
        self.assertEqual(result["cmmf"], "1234567890")

    def test_publicis_layout(self):
        result = parse_product_pdf(sample_pdf("publicis"), "fixture.pdf")
        self.assertEqual(result["range_name"], "SAMPLE SERIES")
        self.assertEqual(result["product_type_standard"], "SAUCEPAN")
        self.assertEqual(result["size_cm"], 16)
        self.assertEqual(result["manufacturing_country"], "VIETNAM")
        self.assertTrue(result["induction_compatible"])

    def test_address_not_origin(self):
        raw = sample_pdf("texto")
        with fitz.open(stream=raw, filetype="pdf") as doc:
            doc[0].insert_text((200, 600), "Example Company France", fontsize=10)
            modified = doc.tobytes()
        result = parse_product_pdf(modified, "fixture.pdf")
        self.assertEqual(result["manufacturing_country"], "CHINA")


if __name__ == "__main__":
    unittest.main()
