"""Privacy-safe tests for native PDF evidence highlights and numeric status."""
import unittest
import fitz
from pdf_overlay import _citation_rects, collect_boxes, render_selected_crop


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
        self.assertEqual(len(rects), 1)
        self.assertTrue(all(r[0] >= 25 for r in rects))

    def test_multilingual_line_highlights_only_korean_source(self):
        dutch = "Limited, Home and Garden 2026 editie. / "
        korean = "테팔 세계판매 �위 주방용품. "
        english = "Euromonitor International "
        line = evidence(dutch + korean + english, "p1:b8:l9", 25, 40)
        next_line = evidence("Limited, Home and Garden 2026 에디션", "p1:b8:l10", 20, 55)
        row = {
            "source_citation": "Euromonitor International Limited, Home and Garden 2026",
            "raw_evidence_ids": ["p1:b8:l10", "p1:b8:l9"],
        }
        boxes = _citation_rects(row, {line["id"]: line, next_line["id"]: next_line})
        self.assertEqual(len(boxes), 2)
        expected_x = 25 + (len(dutch) + len(korean)) * 5
        self.assertTrue(any(abs(box[0] - expected_x) < 1 for box in boxes), boxes)
        self.assertFalse(any(box[0] == 25 for box in boxes))

    def test_selected_crop_includes_multiple_lines_and_is_enlarged(self):
        doc = fitz.open()
        page = doc.new_page(width=600, height=800)
        page.insert_text((100, 220), "FIRST LINE", fontsize=12)
        page.insert_text((115, 240), "SECOND LINE", fontsize=12)
        left = list(page.search_for("FIRST LINE")[0])
        right = list(page.search_for("SECOND LINE")[0])
        data = doc.tobytes()
        doc.close()
        crop = render_selected_crop(data, 1, {"rects": [left, right]})
        self.assertIsNotNone(crop)
        self.assertGreater(crop.width, 200)
        self.assertGreater(crop.height, 60)
        self.assertLess(crop.width, 900)

    def test_selected_crop_empty_rectangles_return_none(self):
        doc = fitz.open()
        doc.new_page(width=300, height=300)
        data = doc.tobytes()
        doc.close()
        self.assertIsNone(render_selected_crop(data, 1, {"rects": []}))

    def test_selected_crop_near_edge_stays_in_bounds(self):
        doc = fitz.open()
        page = doc.new_page(width=240, height=140)
        page.insert_text((5, 14), "EDGE", fontsize=10)
        rect = list(page.search_for("EDGE")[0])
        data = doc.tobytes()
        doc.close()
        crop = render_selected_crop(data, 1, {"rects": [rect]})
        self.assertIsNotNone(crop)
        self.assertGreater(crop.width, 0)
        self.assertGreater(crop.height, 0)

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
