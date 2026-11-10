"""Synthetic BUG-03 tests: no internal artwork is committed."""
import unittest
from extractor import (
    numeric_tokens, numeric_evidence_disagrees, repair_damaged_native,
    source_citation_prefix, korean_segment, numeric_peer_for
)
from layout import group_paragraphs


def fake_line(text):
    return {"spans": [{"chars": [
        {"c": c, "bbox": [i * 6, 0, (i + 1) * 6, 8]}
        for i, c in enumerate(text)
    ]}]}


class NumericPipelineTests(unittest.TestCase):
    def test_ocr_does_not_insert_partial_fraction(self):
        original = "��/�� 스테인리스�스틸로 완성된 내구성"
        revised, repairs = repair_damaged_native(
            original, "18/10 스테인리스 스틸로 완성된 내구성"
        )
        self.assertEqual(revised, original)
        self.assertNotIn("스테인리스10스틸로", revised)
        self.assertTrue(repairs)

    def test_units_normalized_without_false_alarms(self):
        for phrase in ("40%", "18/10", "2025", "3배", "10년",
                       "1위", "16cm", "1.7L", "4개", "2 YEARS", "No.1"):
            self.assertTrue(numeric_tokens(phrase), phrase)
            self.assertFalse(numeric_evidence_disagrees(phrase, phrase))
        self.assertTrue(numeric_evidence_disagrees("최대 40% 수납", "최대 409 수납") is False)
        # 409 alone is not a recognized formatted claim: compare the
        # visibly damaged native source in extraction instead.
        self.assertTrue(numeric_evidence_disagrees("최대 40% 수납", "최대 30% 수납"))

    def test_numeric_prefix_preserved(self):
        self.assertEqual(korean_segment(fake_line("18/10 스테인리스"))[1],
                         "18/10 스테인리스")
        self.assertEqual(korean_segment(fake_line("2025 기준"))[1],
                         "2025 기준")

    def test_citation_fragments_need_real_source(self):
        quote, warnings = source_citation_prefix(
            "Limited, Home and Garden 2026 에디션, 브랜드 매출, 2025 기준",
            "English footnote: Euromonitor International"
        )
        self.assertEqual(quote, "Euromonitor International Limited, Home and Garden 2026")
        self.assertFalse(warnings)
        partial, warnings = source_citation_prefix(
            "Limited, Home and Garden 2026 에디션", ""
        )
        self.assertEqual(partial, "Limited, Home and Garden 2026")
        self.assertTrue(warnings)

    def test_split_number_is_evidence_not_auto_insert(self):
        row = {
            "korean_text": "최대 수납 공간 절약",
            "x0": 100, "y0": 100, "x1": 200, "y1": 112,
            "dir_x": 1, "dir_y": 0, "font_size": 10
        }
        nearby = [{
            "id": "p1:b3:l2", "text": "40%", "bbox": [205,100,230,112],
            "font_size": 10, "direction": [1, 0]
        }, {
            "id": "p1:b4:l0", "text": "90%", "bbox": [800,800,830,810],
            "font_size": 10, "direction": [1, 0]
        }]
        self.assertEqual(
            [e["text"] for e in numeric_peer_for(row, nearby)], ["40%"]
        )
        self.assertEqual(row["korean_text"], "최대 수납 공간 절약")

    def test_numeric_warning_reaches_paragraph_json(self):
        row = {
            "file": "sample.pdf", "page": 1, "curved": False,
            "korean_text": "최대 ��% 수납", "status": "수치 대조 필요 · 원본 확인",
            "warnings": ["수치 대조 필요 · 원본 확인"],
            "numeric_review": True, "raw_evidence_ids": ["p1:b0:l0"],
            "native_numeric_tokens": [], "ocr_candidate": "최대 40% 수납",
            "x0": 0, "y0": 0, "x1": 100, "y1": 12,
            "block_id": 0, "line_id": 0, "font_size": 10,
            "dir_x": 1, "dir_y": 0
        }
        result = group_paragraphs([row])[0]
        self.assertTrue(result["numeric_review"])
        self.assertIn("수치 대조 필요", result["status"])
        self.assertTrue(result["warnings"])
        self.assertEqual(result["ocr_candidates"][0]["text"], "최대 40% 수납")
        self.assertEqual(result["raw_evidence_ids"], ["p1:b0:l0"])
        self.assertEqual(len(result["source_coordinates"]), 1)


if __name__ == "__main__":
    unittest.main()
