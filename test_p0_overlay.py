"""Privacy-safe tests for native PDF evidence highlights and numeric status."""
import unittest
import fitz
from pdf_overlay import _citation_rects, collect_boxes, render_selected_crop, numeric_display_label


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
        self.assertEqual(boxes[0]["kind"], "수치 포함")
        self.assertEqual(boxes[0]["display_label"], "수치 포함")
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

    def test_isolated_maximum_crop_includes_neighboring_number(self):
        """The 40% above 'maximum' must remain in the cropped PDF view."""
        doc = fitz.open()
        page = doc.new_page(width=500, height=500)
        page.insert_text((135, 155), "40%", fontsize=26)
        page.insert_text((120, 190), "MAX", fontsize=11)
        page.insert_text((110, 225), "SPACE SAVING", fontsize=18)
        region = list(page.search_for("MAX")[0])
        original = doc.tobytes()
        doc.close()
        target = {"label": "최대", "status": "문장 연결 확인 필요",
                  "rects": [region]}
        cropped = render_selected_crop(original, 1, target)
        normal = render_selected_crop(original, 1, {"label": "MAX",
                                                      "status": "원본 추출 정상",
                                                      "rects": [region]})
        self.assertIsNotNone(cropped)
        self.assertGreater(cropped.width, normal.width * 2.0)
        self.assertGreater(cropped.height, normal.height * 2.0)
        self.assertLessEqual(cropped.width, 1800)
        self.assertLessEqual(cropped.height, 1100)

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

    def test_numeric_labels_normal_and_uncertain(self):
        self.assertEqual(numeric_display_label(
            "최대 40% 수납 공간 절약", "원본 추출 정상"),
            "수치 포함")
        self.assertEqual(numeric_display_label(
            "최대 3배 코팅", "원본 추출 정상"),
            "수치 포함")
        self.assertEqual(numeric_display_label(
            "18/10 스테인리스 10년", "원본 추출 정상"),
            "수치 포함")
        self.assertEqual(numeric_display_label(
            "최대 40& 수납 공간 절약", "원본 추출 정상"),
            "수치 포함")
        self.assertEqual(numeric_display_label(
            "최대 ��% 수납 공간 절약", "수치 대조 필요 · 원본 확인", True),
            "수치 포함")
        self.assertEqual(numeric_display_label(
            "제품 설명", "원본 추출 정상"), "")
        self.assertEqual(numeric_display_label(
            "최대 [뒤따르는 수치·문구 연결 확인 필요]",
            "문장 연결 확인 필요 · 숫자 객체 연결 미확정",
            True, [{"text": "40%"}]), "수치 포함")

    def test_normal_number_visible_in_dropdown_data(self):
        row = {"file": "synthetic.pdf", "page": 1,
               "korean_text": "최대 40% 수납 공간 절약",
               "status": "원본 추출 정상", "numeric_review": False,
               "x0": 0, "y0": 0, "x1": 100, "y1": 15,
               "curved": False, "raw_evidence_ids": []}
        boxes = collect_boxes([row], [], [], "synthetic.pdf", 1, group_view=False)
        self.assertEqual(boxes[0]["kind"], "수치 포함")
        self.assertEqual(boxes[0]["display_label"], "수치 포함")
        self.assertEqual(boxes[0]["label"], row["korean_text"])
        self.assertEqual(boxes[0]["status"], "원본 추출 정상")

    def test_isolated_maximum_includes_pdf_number_and_benefit_boxes(self):
        row = {
            "file": "synthetic.pdf", "page": 1, "korean_text": "최대",
            "status": "문장 연결 확인 필요 · 숫자 객체 연결 미확정",
            "numeric_review": True,
            "x0": 1456, "y0": 848, "x1": 1476, "y1": 860,
            "curved": False, "raw_evidence_ids": [],
        }
        number = evidence("40%", "p1:b38:l1", 1480, 817)
        number["bbox"] = [1480, 817, 1539, 873]
        phrase = evidence("수납 공간 절약", "p1:b37:l0", 1427, 861)
        phrase["bbox"] = [1427, 861, 1540, 893]
        unrelated = evidence("40%", "p1:b32:l0", 820, 788)
        unrelated["bbox"] = [820, 788, 898, 844]
        summaries = [{"file": "synthetic.pdf", "page": 1,
                      "raw_evidence": [number, phrase, unrelated]}]
        group = {
            "file": "synthetic.pdf", "page": 1,
            "line_indices": [0], "type": "문장 연결 확인",
            "paragraph": "최대 [뒤따르는 수치·문구 연결 확인 필요]",
            "status": row["status"], "numeric_review": True
        }
        boxes = collect_boxes([row], [group], [], "synthetic.pdf", 1,
                              group_view=True, raw_summaries=summaries)
        selected = boxes[0]
        self.assertEqual(selected["context_candidates"], ["40%", "수납 공간 절약"])
        self.assertEqual(selected["original_label"], group["paragraph"])
        self.assertIn("40% / 수납 공간 절약", selected["label"])
        self.assertEqual(len(selected["rects"]), 3)
        self.assertFalse(any(rect[0] == 820 for rect in selected["rects"]))

    def test_numeric_review_has_own_kind_in_list(self):
        row = {"file": "synthetic.pdf", "page": 1, "korean_text": "최대 ��% 수납",
               "status": "수치 대조 필요 · 원본 확인", "x0": 0, "y0": 0,
               "x1": 100, "y1": 15, "curved": False,
               "source_citation": "", "raw_evidence_ids": []}
        boxes = collect_boxes([row], [], [], "synthetic.pdf", 1,
                              group_view=False)
        self.assertEqual(boxes[0]["kind"], "수치 포함")
        self.assertEqual(boxes[0]["line_index"], 0)


if __name__ == "__main__":
    unittest.main()
