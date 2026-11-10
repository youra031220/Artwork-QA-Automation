"""Privacy-safe regressions based on reported P0 issues; no company artwork bundled."""
import unittest
import fitz

from extractor import korean_segment, numeric_tokens, _korean_scope_end
from layout import group_paragraphs
from product_parser import parse_product_pdf
from product_identity import check_product_identity


def pdf_fixture(style):
    doc = fitz.open()
    page = doc.new_page(width=900, height=1000)
    ticket = (
        [(120, 40, "GAMME G7 SAMPLE START EXTRA"),
         (120, 60, "DOSSIER"), (220, 60, "CST_13_26_123456"),
         (120, 80, "PRODUIT"), (220, 80, "CASSEROLE 16 cm + CV"),
         (120, 100, "ECHELLE"), (220, 100, "1:1"),
         (350, 550, "SAMPLE START"),
         (250, 820, "GAMME ET UNE GAMME NOUVELLE")]
        if style == "inline" else
        [(120, 40, "NOM GAMME"), (240, 40, "SAMPLE CALM"),
         (120, 60, "DOSSIER"), (240, 60, "CST 13 26 123456"),
         (120, 80, "DESCRIPTION"), (240, 80, "Faitout 20 cm + CV"),
         (120, 100, "ECHELLE"), (240, 100, "1:1"),
         (350, 550, "SAMPLE CALM"),
         (250, 310, "Dossier suivi par somebody")]
    )
    for x, y, text in ticket:
        page.insert_text((x, y), text, fontsize=15 if y == 550 else 9)
    if style == "inline":
        page.insert_text((250, 620), "MADE IN VIETNAM")
        page.insert_text((250, 660), "ALL HOBS + INDUCTION")
    else:
        page.insert_text((250, 620), "MADE IN CHINA")
        page.insert_text((250, 660), "ALL HOBS EXCEPT INDUCTION")
    raw = doc.tobytes()
    doc.close()
    return raw


def raw_hangul_line(text):
    chars = [{"c": c, "bbox": (i * 7, 0, (i + 1) * 7, 11)}
             for i, c in enumerate(text)]
    return {"spans": [{"chars": chars}]}


class P0BugRegressions(unittest.TestCase):
    def test_workinfo_not_shifted_into_dossier(self):
        obj = parse_product_pdf(pdf_fixture("inline"), "dummy.pdf")
        self.assertEqual(obj["product_type_raw"], "CASSEROLE 16 cm + CV")
        self.assertEqual(obj["product_type_standard"], "SAUCEPAN")
        self.assertEqual(obj["has_lid"], True)
        self.assertEqual(obj["size_cm"], 16)

    def test_shortened_front_title_needs_review(self):
        items = check_product_identity(pdf_fixture("inline"), "dummy.pdf")
        primary = [x for x in items if x["is_primary"]]
        self.assertTrue(primary)
        self.assertTrue(all(x["status"] == "REVIEW" for x in primary))
        self.assertTrue(all(x["extracted"] != "GAMME ET UNE GAMME NOUVELLE" for x in primary))
        self.assertEqual(primary[0]["extracted"], "SAMPLE START")

    def test_dossier_prose_must_not_override_ticket(self):
        obj = parse_product_pdf(pdf_fixture("split"), "dummy.pdf")
        self.assertEqual(obj["product_type_standard"], "STEWPOT")
        self.assertEqual(obj["dossier"], "CST 13 26 123456")
        self.assertEqual(obj["has_lid"], True)
        self.assertEqual(obj["manufacturing_country"], "CHINA")
        self.assertFalse(obj["induction_compatible"])

    def test_source_coordinates_point_to_value(self):
        raw = pdf_fixture("split")
        obj = parse_product_pdf(raw, "dummy.pdf")
        e = obj["evidence"]["range_name"][0]
        self.assertEqual(e["original_text"], "SAMPLE CALM")
        self.assertGreater(e["bbox"][0], 200)

    def test_numerical_prefix_preserved(self):
        seg = korean_segment(raw_hangul_line("18/10 스테인리스 스틸"))
        self.assertIsNotNone(seg)
        self.assertTrue(seg[1].startswith("18/10"))
        seg = korean_segment(raw_hangul_line("2025 기준"))
        self.assertTrue(seg[1].startswith("2025"))

    def test_numeric_token_recognition(self):
        self.assertIn("40%", numeric_tokens("최대 40% 수납"))
        self.assertIn("18/10", numeric_tokens("18/10 스테인리스"))
        self.assertIn("2025", numeric_tokens("2025 기준"))

    def test_vertical_sentence_not_curved_product(self):
        row = {"file": "dummy.pdf", "page": 1, "curved": True,
               "korean_text": "가스레인지, 핫플레이트 사용 가능 (인덕션 사용 불가)",
               "status": "곡선 배치 · 연결 확인", "font_size": 10,
               "dir_x": 0, "dir_y": 1, "x0": 10, "y0": 10,
               "x1": 30, "y1": 160, "block_id": 0, "line_id": 0}
        output = group_paragraphs([row])
        self.assertEqual(output[0]["type"], "세로 일반 문구")
        self.assertIn(", ", output[0]["paragraph"])
        self.assertIn("(인덕션 사용 불가)", output[0]["paragraph"])

if __name__ == "__main__":
    unittest.main()
