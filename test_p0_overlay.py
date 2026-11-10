"""Privacy-safe tests for native PDF evidence highlights and numeric status."""
import unittest
from pdf_overlay import _citation_rects, collect_boxes


def evidence(text, key, x, y):
    return {
        "id": key, "text": text,
        "spans": [{"chars": [
            {"text": ch, "bbox": [x + i * 5, y, x + (i + 1) * 5, y + 9]}
            for i, ch in enumerate(text)
        ]}],
    }


class SourceOverlayTests(unittest.TestCase):
    def test_split_english_source_has_two_distinct_rectangles(self):
        first = evidence("Disclaimer: Euromonitor International ", "p1:b4:l9", 100, 40)
        second = evidence("Limited, Home and Garden 2026 에디션", "p1:b4:l10", 30, 53)
        row = {
            "file": "synthetic.pdf", "page": 1, "block_id": 4, "line_id": 10,
            "x0": 170, "y0": 53, "x1": 230, "y1": 62,
            "korean_text": "Euromonitor International Limited, Home and Garden 2026 에디션",
            "source_citation": "Euromonitor International Limited, Home and Garden 2026",
            "raw_evidence_ids": ["p1:b4:l10", "p1:b4:l9"],
            "status": "원본 추출 정상", "numeric_review": False
        }
        summaries = [{"file": "synthetic.pdf", "page": 1, "raw_evidence": [first,second]}]
        group = {"file": "synthetic.pdf", "page": 1, "line_indices": [0],
                 "type": "일반 문단", "paragraph": row["korean_text"],
                 "status": row["status"]}
        boxes = collect_boxes([row], [group], [], "synthetic.pdf", 1,
                              group_view=True, raw_summaries=summaries)
        self.assertEqual(len(boxes), 1)
        self.assertEqual(boxes[0]["kind"], "한국어")
        self.assertEqual(len(boxes[0]["rects"]), 3)
        self.assertTrue(any(r[1] == 40 for r in boxes[0]["rects"]))
        self.assertTrue(any(r[1] == 53 and r[0] == 30 for r in boxes[0]["rects"]))

    def test_single_line_citation_highlights_original_latin_glyphs(self):
        line = evidence("Euromonitor International Limited, Home and Garden 2026 에디션",
                        "p1:b5:l0", 25, 80)
        row = {"source_citation": "Euromonitor International Limited, Home and Garden 2026",
               "raw_evidence_ids": ["p1:b5:l0"]}
        rects = _citation_rects(row, {line["id"]: line})
        self.assertEqual(len(rects), 2)
        self.assertTrue(all(r[0] >= 25 for r in rects))

    def test_numeric_review_has_own_kind_in_list(self):
        row = {"file": "synthetic.pdf", "page": 1, "korean_text": "최대 ��% 수납",
               "status": "수치 대조 필요 · 원본 확인", "x0": 0, "y0": 0,
               "x1": 100, "y1": 15, "curved": False,
               "source_citation": "", "raw_evidence_ids": []}
        boxes = collect_boxes([row], [], [], "synthetic.pdf", 1,
                              group_view=False)
        self.assertEqual(boxes[0]["kind"], "수치 확인")
        self.assertEqual(boxes[0]["line_index"], 0)


if __name__ == "__main__":
    unittest.main()
