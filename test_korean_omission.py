"""Regressions for Korean phrase omissions found on the Stewpot 24 artwork.

Synthetic strings only; no company artwork is committed.
"""
import unittest

from extractor import _ocr_korean_span, fill_damaged_glyphs, merge_hole_readings
from layout import group_paragraphs
from embedded_reference import load_master
from phrase_matcher import match_phrases

H = "�"


def row(text, block, line, x0, baseline, size=8.0, numeric=False):
    return {"file": "f.pdf", "page": 1, "block_id": block, "line_id": line,
            "curved": False, "dir_x": 1.0, "dir_y": 0.0, "font_size": size,
            "baseline_y": baseline, "korean_text": text, "pdf_original": text,
            "status": "원본 추출 정상", "numeric_review": numeric, "warnings": [],
            "x0": x0, "y0": baseline - size, "x1": x0 + 100, "y1": baseline + 2}


class OcrSpanTests(unittest.TestCase):
    def test_misread_latin_inside_sentence_does_not_truncate(self):
        ocr = "공간 절약ㆍ편수냄비 4개, SEA 4개 수납을 기준으로 기존 자사 MET 비교 테스트 진행 /"
        self.assertEqual(_ocr_korean_span(ocr),
                         "공간 절약ㆍ편수냄비 4개, SEA 4개 수납을 기준으로 기존 자사 MET 비교 테스트 진행")

    def test_terminal_period_kept(self):
        self.assertEqual(_ocr_korean_span("'테팔 세계판매 1위 주방용품."), "테팔 세계판매 1위 주방용품.")


class HoleFillTests(unittest.TestCase):
    def test_only_holes_change_native_letters_kept(self):
        native = f"공간{H}절약 • 편수냄비 {H}개, 뚜껑 {H}개{H}수납을{H}기준으로"
        text, filled, unresolved = fill_damaged_glyphs(
            native, "공간 절약ㆍ편수냄비 4개, SEA 4개 수납을 기준으로")
        self.assertEqual(text, "공간 절약 • 편수냄비 4개, 뚜껑 4개 수납을 기준으로")
        self.assertNotIn("SEA", text)          # OCR garbage never replaces native text
        self.assertEqual(unresolved, 0)

    def test_digit_count_must_match_hole_count(self):
        text, _, unresolved = fill_damaged_glyphs(f"최대 {H}{H}% 수납", "최대 4% 수납")
        self.assertEqual(text, f"최대 {H}{H}% 수납")
        self.assertEqual(unresolved, 2)

    def test_unrelated_ocr_is_ignored(self):
        text, filled, _ = fill_damaged_glyphs(f"가나{H}다라", "전혀 다른 문장")
        self.assertEqual(filled, [])

    def test_space_difference_next_to_numeric_hole(self):
        text, _, unresolved = fill_damaged_glyphs(f"테팔 세계판매 {H}위 주방용품.", "테팔 세계판매1위 주방용품.")
        self.assertEqual(text, "테팔 세계판매 1위 주방용품.")
        self.assertEqual(unresolved, 0)


class DigitAgreementTests(unittest.TestCase):
    def test_single_reading_never_restores_a_digit(self):
        native = f"{H}{H}/{H}{H} 스테인리스"
        self.assertEqual(merge_hole_readings(native, ["19/10 스테인리스"]), native)

    def test_conflicting_readings_stay_unresolved(self):
        native = f"{H}{H}/{H}{H} 스테인리스"
        merged = merge_hole_readings(native, ["19/10 스테인리스", "18/10 스테인리스"])
        self.assertEqual(merged, f"1{H}/10 스테인리스")

    def test_majority_of_three_restores(self):
        native = f"{H}{H}/{H}{H} 스테인리스"
        merged = merge_hole_readings(native, ["19/10 스테인리스", "18/10 스테인리스", "18/10 스테인리스"])
        self.assertEqual(merged, "18/10 스테인리스")

    def test_space_needs_one_reading(self):
        self.assertEqual(merge_hole_readings(f"공간{H}절약", ["공간 절약"]), "공간 절약")


class WorldFootnoteJoinTests(unittest.TestCase):
    def test_claim_and_source_on_consecutive_lines_join_and_match(self):
        rows = [
            row("테팔 세계판매 1위 주방용품.", 17, 8, 1860.8, 1207.0, numeric=True),
            row("Euromonitor International Limited, Home and Garden 2026 에디션, "
                "주방용품 카테고리 브랜드 매출, 2025 기준", 17, 9, 1715.0, 1216.0),
        ]
        groups = group_paragraphs(rows)
        self.assertEqual(len(groups), 1)
        match = match_phrases(groups, load_master())[0]
        self.assertEqual(match["phrase_id"], "P202")
        self.assertIn("2026", match["differences"])

    def test_other_block_is_not_joined(self):
        rows = [
            row("테팔 세계판매 1위 주방용품.", 17, 8, 1860.8, 1207.0),
            row("Euromonitor International Limited, Home and Garden 2026 에디션", 30, 0, 100, 1216.0),
        ]
        self.assertEqual(len(group_paragraphs(rows)), 2)


class LedgerTests(unittest.TestCase):
    def test_same_korean_registered_twice_is_not_ambiguous(self):
        match = match_phrases([{"file": "f", "page": 1,
                                "paragraph": "무거운 무게에도 안정적인 견고한 손잡이"}], load_master())[0]
        self.assertEqual(match["status"], "EXACT_MATCH")
        self.assertEqual({a["phrase_id"] for a in match["alternates"]}, {"P44", "P45"})

    def test_added_number_is_reported_as_addition(self):
        match = match_phrases([{"file": "f", "page": 1,
                                "paragraph": "18/10 스테인리스 스틸 - 10년 품질보증"}], load_master())[0]
        self.assertEqual(match["phrase_id"], "P219")
        self.assertIn("18/10", match["differences"])
        self.assertIn("추가", match["differences"])


if __name__ == "__main__":
    unittest.main()


class LabelTableExclusionTests(unittest.TestCase):
    """한글표시사항 tables are recognised by structure and excluded."""

    @staticmethod
    def _page(rows, with_text=True):
        import fitz
        document = fitz.open()
        page = document.new_page(width=600, height=400)
        x0, x1, top = 100, 300, 60
        for index in range(rows + 1):
            y = top + index * 12
            page.draw_line((x0, y), (x1, y), width=.4)
        for x in (x0, 160, x1):
            page.draw_line((x, top), (x, top + rows * 12), width=.4)
        if with_text:
            for index in range(rows):
                page.insert_text((104, top + index * 12 + 9), "Label field text value", fontsize=7)
        page.insert_text((100, 300), "Marketing claim outside the table", fontsize=9)
        return document, page

    def test_ruled_grid_with_lettering_is_a_label_table(self):
        from region_text import find_label_tables
        document, page = self._page(rows=10)
        tables = find_label_tables(page, page.get_text("rawdict", flags=0))
        self.assertEqual(len(tables), 1)
        import fitz
        self.assertNotIn(fitz.Point(110, 300), tables[0])   # other copy stays in scope

    def test_few_rules_or_no_lettering_is_not_a_label_table(self):
        from region_text import find_label_tables
        document, page = self._page(rows=4)
        self.assertEqual(find_label_tables(page, page.get_text("rawdict", flags=0)), [])
        document, page = self._page(rows=10, with_text=False)
        self.assertEqual(find_label_tables(page, page.get_text("rawdict", flags=0)), [])
