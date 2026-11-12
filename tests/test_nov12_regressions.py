"""Regression tests for reference matching and source-only numerals."""
import unittest
from phrase_matcher import _one, _variable_year_match


class MatchingRegressions(unittest.TestCase):
    def setUp(self):
        self.master = {
            "phrases": [{
                "phrase_id": "P1",
                "category_id": "품질 보증",
                "korean_original": "테팔은 모든 제조 과정 중의 결함에 대하여 구입일로부터 2년간 품질 보증 제도를 실시합니다.",
                "english_original": "This product is guaranteed for 2 years against manufacturing defects.",
            }],
            "variants": [{"phrase_id": "P1", "rule_id": "R1"}],
        }

    def test_extra_disclaimer_is_not_approved(self):
        base = self.master["phrases"][0]["korean_original"]
        result = _one({"file": "x.pdf", "page": 1,
                       "paragraph": base + " 스크래치 및 변색은 제외됩니다."},
                      self.master)
        self.assertEqual(result["status"], "TEXT_MISMATCH")
        self.assertIn("추가", result["reason"])

    def test_exact_warranty_is_unchanged(self):
        result = _one({"paragraph": self.master["phrases"][0]["korean_original"]},
                      self.master)
        self.assertEqual(result["status"], "EXACT_MATCH")

    def test_edition_data_years_are_independent(self):
        template = "Home and Garden 202X 에디션, 브랜드 매출, 202X 기준"
        observed = "Home and Garden 2026 에디션, 브랜드 매출, 2025 기준"
        self.assertEqual(_variable_year_match(observed, template), ("2026", "2025"))

    def test_missing_digits_are_not_restored_from_template(self):
        template = "Home and Garden 202X 에디션, 브랜드 매출, 202X 기준"
        self.assertIsNone(_variable_year_match(
            "Home and Garden 2026 에디션, 브랜드 매출, □□□□ 기준", template))


if __name__ == "__main__":
    unittest.main()
