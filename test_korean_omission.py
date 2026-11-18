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


class CoatingClaimJoinTests(unittest.TestCase):
    """'테팔 기본 코팅 대비 / 최대 Y배 더 오래가는 / 엑스트라 라이프 논스틱 코팅'
    is one G7 feature even when the three lines are separate PDF objects and
    some glyphs are still damaged."""

    def _rows(self, first, second, third):
        return [row(first, 3, 0, 100, 500, size=14),
                row(second, 4, 0, 100, 520, size=14),
                row(third, 5, 0, 100, 540, size=14)]

    def test_damaged_lines_join_into_one_feature(self):
        groups = group_paragraphs(self._rows(f"테팔{H}기본 코팅 대비", f"최대 {H}배{H}더{H}오래가는",
                                             "엑스트라 라이프 논스틱 코팅"))
        self.assertEqual(len(groups), 1)
        match = match_phrases(groups, load_master())[0]
        self.assertEqual(match["phrase_id"], "P33")
        self.assertEqual(match["category"], "G7 특장점")

    def test_restored_lines_match_y_multiplier_variable(self):
        groups = group_paragraphs(self._rows("테팔 기본 코팅 대비", "최대 3배 더 오래가는",
                                             "엑스트라 라이프 논스틱 코팅"))
        self.assertEqual(len(groups), 1)
        match = match_phrases(groups, load_master())[0]
        self.assertEqual(match["phrase_id"], "P33")
        self.assertEqual(match["differences"], "Y=3")


class FootnoteAndBulletTests(unittest.TestCase):
    def test_footnote_mark_is_not_a_number(self):
        match = match_phrases([{"file": "f", "page": 1, "paragraph": "최대 40% 수납 공간 절약"}],
                              load_master())[0]
        self.assertEqual(match["phrase_id"], "P238")
        self.assertEqual(match["status"], "NORMALIZED_MATCH")

    def test_claim_and_footnote_on_one_line_are_split(self):
        from layout import split_bullet_clauses
        groups = split_bullet_clauses([{"file": "f", "page": 1, "paragraph":
            "최대 40% 수납 공간 절약 • 편수냄비 4개, 뚜껑 4개 수납을 기준으로 기존 자사 제품과 비교 테스트 진행"}])
        self.assertEqual(len(groups), 2)
        first, second = match_phrases(groups, load_master())
        self.assertEqual(first["phrase_id"], "P238")
        self.assertEqual(second["status"], "NUMERIC_MISMATCH")   # 4+4 is not in the ledger
        self.assertIn("PDF 4개, 4개", second["reason"])


class RecyclingLidRuleTests(unittest.TestCase):
    def _judge(self, observed, ids):
        from recycling_rule import judge
        return judge(observed, [{"phrase_id": i} for i in ids])

    def test_lid_requires_glass_exclusion_sentence(self):
        self.assertEqual(self._judge("SAUCEPAN WITH LID", ["P201"])["status"], "OK")
        result = self._judge("Casserole 16 cm + CV", ["P200"])
        self.assertEqual(result["status"], "FAIL")

    def test_no_lid_requires_plain_sentence(self):
        self.assertEqual(self._judge("FRY PAN", ["P200"])["status"], "OK")
        self.assertEqual(self._judge("FRY PAN", ["P201"])["status"], "FAIL")

    def test_lid_in_other_context_is_not_composition(self):
        observed = "DISHWASHER SAFE EXCEPT LID (1) TESTED ON 3 SAUCEPANS, 1 SAUTÉ PAN, 4 LIDS"
        self.assertEqual(self._judge(observed, ["P200"])["status"], "OK")

    def test_two_sentences_or_none(self):
        self.assertEqual(self._judge("FRY PAN", ["P200", "P201"])["status"], "FAIL")
        self.assertEqual(self._judge("FRY PAN", [])["status"], "MISSING")


class RequiredPhraseTests(unittest.TestCase):
    def _check(self, texts):
        from required_check import check_file
        master = load_master()
        matches = match_phrases([{"file": "f", "page": 1, "paragraph": t} for t in texts], master)
        return {c["rule_id"]: c for c in check_file(matches, master)}

    def test_warranty_sentences_found_inside_one_printed_paragraph(self):
        result = self._check([
            "테팔은 모든 제조 과정 중의 결함에 대하여 구입일로부터 2년간 품질 보증 제도를 실시합니다. "
            "제품 내부와 외부에 생긴 스크래치 또는 사용 중 발생한 변색과 얼룩 등은 해당되지 않습니다.",
            "취급 주의 사항: 본 제품 사용 시, 주의하여 주십시오. 어린이나 사용이 미숙한 사람의 손에 닿지 "
            "않는 곳에 보관하여 주십시오. 제품이 과열되지 않도록 주의하십시오."])
        self.assertEqual(result["R191"]["status"], "OK")
        self.assertEqual(result["R196"]["status"], "OK")

    def test_missing_and_duplicate(self):
        result = self._check(["인덕션 포함 모든 열원 사용 가능",
                              "가스레인지, 핫플레이트, 하이라이트 사용 가능 (인덕션 사용 불가)"])
        self.assertEqual(result["R185"]["status"], "FAIL")
        self.assertEqual(result["R188"]["status"], "MISSING")
        self.assertEqual(result["R196"]["status"], "MISSING")


class EnglishPairingTests(unittest.TestCase):
    def test_multiplier_placeholder_and_editorial_note(self):
        from english_pairing import _target_pattern, _reference_english, _observed_reference_hint, _tidy
        self.assertTrue(_target_pattern("EXTRA-LIFE NON-STICK UP TO YX MORE RESISTANT").search(
            "extralifenonstickupto3xmoreresistant"))
        self.assertEqual(_reference_english("Fry pan (in a 2-word request from KOREA)"), "Fry pan")
        self.assertTrue(_observed_reference_hint("편수냄비 4개, 뚜껑 4개 수납을 기준으로").startswith(
                         "TESTED ON 4 SAUCEPANS AND 4 LIDS BETWEEN"))
        self.assertEqual(_tidy("FR YP AN"), "FRYPAN")


class RequiredShowsExtractedPhraseTests(unittest.TestCase):
    def test_contained_ledger_phrase_reports_the_printed_phrase(self):
        from required_check import check_file
        master = load_master()
        printed = "테팔 기본 코팅 대비 최대 5배 더 오래가는 엑스트라 라이프 논스틱 코팅"
        result = {c["rule_id"]: c for c in check_file(
            match_phrases([{"file": "f", "page": 1, "paragraph": printed}], master), master)}
        self.assertIn(printed, result["R31"]["message"])

    def test_short_ledger_word_inside_other_sentence_is_not_found(self):
        from required_check import check_file
        master = load_master()
        result = {c["rule_id"]: c for c in check_file(match_phrases(
            [{"file": "f", "page": 1, "paragraph": "편수냄비 4개, 뚜껑 4개 수납을 기준으로 기존 자사 제품과 비교 테스트 진행"}],
            master), master)}
        self.assertEqual(result["R54"]["status"], "MISSING")


class KeyMessageUnregisteredTests(unittest.TestCase):
    def test_unregistered_phrase_makes_key_message_a_review_not_a_miss(self):
        from required_check import check_file
        master = load_master()
        result = {c["rule_id"]: c for c in check_file(match_phrases(
            [{"file": "f", "page": 1, "paragraph": "쉬운 요리를 위한 강력한 코팅, 가벼운 무게"}], master), master)}
        self.assertEqual(result["R6"]["status"], "REVIEW")
        self.assertTrue(result["R6"]["message"].startswith("△"))
