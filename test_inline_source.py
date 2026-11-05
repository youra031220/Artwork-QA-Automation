"""Regression checks for Korean text containing an English bibliography."""
import unittest
from extractor import korean_segment


def line_of(text):
    return {"spans": [{"chars": [
        {"c": char, "bbox": (i, 0, i + 1, 1)} for i, char in enumerate(text)
    ]}]}


class InlineEnglishSourceTests(unittest.TestCase):
    def test_euromonitor_inside_korean_sentence(self):
        phrase = (
            "테팔 세계판매 1위 주방용품. Euromonitor International Limited, "
            "Home and Garden 2026 에디션, 주방용품 카테고리 브랜드 매출, 2025 기준"
        )
        self.assertEqual(korean_segment(line_of(phrase))[1], phrase)

    def test_does_not_include_adjacent_foreign_translation(self):
        phrase = (
            "세계판매 1위 주방용품. Euromonitor International Limited, "
            "Home and Garden 2026 에디션, 브랜드 매출, 2025 기준 "
            "/ Tefal the world number one cookware brand"
        )
        result = korean_segment(line_of(phrase))[1]
        self.assertIn("Home and Garden 2026 에디션", result)
        self.assertNotIn("the world number one", result)

    def test_does_not_swallow_foreign_translation_on_simple_line(self):
        self.assertEqual(
            korean_segment(line_of("인덕션 포함 모든 열원 사용 가능 TOATE SURSELE + INDUCTIE"))[1],
            "인덕션 포함 모든 열원 사용 가능",
        )


if __name__ == "__main__":
    unittest.main()
