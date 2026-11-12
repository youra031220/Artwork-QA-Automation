"""Raster-confirmed Korean citation number repair: synthetic public fixtures only."""
import unittest
from unittest.mock import patch
import fitz

from numeric_citation import repair_korean_world_years


def example():
    doc=fitz.open()
    doc.new_page(width=800,height=900)
    raw=doc.tobytes()
    doc.close()
    text=("세계판매 □위 주방용품. Euromonitor International Limited, "
          "Home and Garden 2026 에디션, 주방용품 카테고리 브랜드 매출, □□□□ 기준")
    group={"file":"sample.pdf","page":1,"paragraph":text,
           "source_coordinates":[{"bbox":[100,150,520,195]}],
           "ocr_candidates":[],"numeric_review":True}
    return group,{"sample.pdf":raw}


class KoreanCitationOCRTests(unittest.TestCase):
    def test_independent_raster_rank_and_data_year_are_restored(self):
        group,pdfs=example()
        with patch("numeric_citation._read_korean_print",
                   return_value=("1","2025","세계판매 1위 브랜드 매출 2025 기순")):
            result=repair_korean_world_years([group],pdfs)
        self.assertEqual(len(result),1)
        self.assertIn("세계판매 1위",result[0]["paragraph"])
        self.assertIn("2026 에디션",result[0]["paragraph"])
        self.assertIn("2025 기준",result[0]["paragraph"])
        self.assertEqual(result[0]["original_paragraph"],group["paragraph"])
        self.assertTrue(result[0]["numeric_review"])

    def test_missing_korean_year_is_not_borrowed_from_english_citation(self):
        group,pdfs=example()
        with patch("numeric_citation._read_korean_print",
                   return_value=("1",None,"세계판매 1위")):
            result=repair_korean_world_years([group],pdfs)[0]
        self.assertIn("세계판매 1위",result["paragraph"])
        self.assertIn("□□□□ 기준",result["paragraph"])
        self.assertNotIn("2025 기준",result["paragraph"])

    def test_no_raster_evidence_preserves_original(self):
        group,pdfs=example()
        with patch("numeric_citation._read_korean_print",return_value=None):
            self.assertEqual(repair_korean_world_years([group],pdfs),[group])

if __name__=="__main__":
    unittest.main()
