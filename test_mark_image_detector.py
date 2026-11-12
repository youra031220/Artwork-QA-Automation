"""Private-PDF-free rendering tests for image marks and conditional review."""
import io
import unittest
from unittest.mock import patch

import cv2
import fitz
import numpy as np
from PIL import Image

from mark_image_detector import detect_pdf_marks, review_mark_rules, preview_mark


def sample_pdf(with_qr=True, commitment=True):
    pdf=fitz.open()
    page=pdf.new_page(width=540,height=420)
    if commitment:
        page.insert_text((220,205),"TEFAL COMMITMENTS",fontsize=12)
    else:
        page.insert_text((220,205),"SCAN FOR USE & CARE",fontsize=12)
    if with_qr:
        encoder=cv2.QRCodeEncoder_create()
        data=encoder.encode("https://example.org/commitment")
        # Nearest-neighbor enlargement avoids blurred QR finder patterns.
        data=cv2.resize(data,(180,180),interpolation=cv2.INTER_NEAREST)
        image=Image.fromarray(data)
        binary=io.BytesIO()
        image.save(binary,format="PNG")
        page.insert_image(fitz.Rect(260,110,360,210),stream=binary.getvalue())
    payload=pdf.tobytes()
    pdf.close()
    return payload


class MarkImageTests(unittest.TestCase):
    def test_actual_qr_pixels_detected_near_commitment_label(self):
        raw=sample_pdf()
        found=detect_pdf_marks(raw,"qr.pdf")
        self.assertTrue(any(f["code"]=="TEFAL_COMMITMENTS_QR" and
                            f["status"]=="DETECTED" for f in found))
        qr=next(f for f in found if f["status"]=="DETECTED")
        self.assertGreater(qr["bbox"][2]-qr["bbox"][0],10)
        png=preview_mark(raw,qr["page"],qr["bbox"])
        self.assertTrue(png.startswith(b"\x89PNG"))

    def test_missing_qr_is_review_not_fail(self):
        empty=sample_pdf(with_qr=False)
        findings=detect_pdf_marks(empty,"empty.pdf")
        self.assertFalse(any(x["status"]=="DETECTED" for x in findings))
        results=review_mark_rules(findings,[],[{"file":"empty.pdf"}],"empty.pdf")
        qr=next(x for x in results if x["rule_id"]=="IMG-TEFAL_COMMITMENTS_QR")
        self.assertEqual(qr["status"],"REVIEW")
        self.assertEqual(qr["found_occurrences"],0)

    def test_non_qr_text_cannot_pass_qr_image(self):
        pdf=fitz.open()
        page=pdf.new_page(width=520,height=420)
        page.insert_text((220,205),"TEFAL COMMITMENTS QR",fontsize=12)
        raw=pdf.tobytes()
        pdf.close()
        results=detect_pdf_marks(raw,"text_only.pdf")
        self.assertFalse(any(x["status"]=="DETECTED" for x in results))

    def test_world_text_is_only_visual_candidate_not_logo_ok(self):
        pdf=fitz.open()
        page=pdf.new_page(width=520,height=420)
        page.insert_text((220,205),"WORLD N1",fontsize=12)
        raw=pdf.tobytes()
        pdf.close()
        found=detect_pdf_marks(raw,"world.pdf")
        icons=[x for x in found if x["code"]=="WORLD_NO1"]
        self.assertFalse(icons)  # Text alone is not logo image evidence

    def test_world_badge_requires_red_printed_panel_not_just_world_text(self):
        pdf=fitz.open()
        page=pdf.new_page(width=540,height=420)
        page.draw_rect(fitz.Rect(195,165,310,240),
                       color=(.9,0,0),fill=(.9,0,0))
        page.insert_text((220,205),"WORLD N1",fontsize=12,color=(1,1,1))
        source=pdf.tobytes()
        pdf.close()
        findings=detect_pdf_marks(source,"red.pdf")
        world=[x for x in findings if x["code"]=="WORLD_NO1"]
        self.assertFalse(any(x["method"]=="image_region_text_anchor" for x in world))
        # Without image OCR confirmation, a red banner stays unverified.

    def test_raster_world_badge_detected_without_native_world_text(self):
        # A logo flattened into an image has no PDF-native WORLD lettering.
        pdf=fitz.open()
        page=pdf.new_page(width=540,height=420)
        page.draw_rect(fitz.Rect(195,165,310,240),
                       color=(.9,0,0),fill=(.9,0,0))
        payload=pdf.tobytes()
        pdf.close()
        with patch("pytesseract.image_to_string",
                   return_value="Tefal WORLD -N'1- IN COOKWARE"):
            found=detect_pdf_marks(payload,"raster_world.pdf")
        self.assertTrue(any(x["code"]=="WORLD_NO1"
                            and x["status"]=="DETECTED"
                            and "raster" in x["method"] for x in found))

    def test_recycling_text_without_disposal_notice_is_review(self):
        pdf=fitz.open()
        page=pdf.new_page(width=520,height=420)
        page.insert_text((220,205),"RECYCLABLE METAL",fontsize=12)
        source=pdf.tobytes()
        pdf.close()
        found=detect_pdf_marks(source,"recycle.pdf")
        rr=review_mark_rules(found,[],[{"file":"recycle.pdf"}],"recycle.pdf")
        notice=next(x for x in rr if x["rule_id"]=="IMG-RECYCLING")
        self.assertEqual(notice["status"],"REVIEW")
        self.assertIn("이미지 미확인",notice["finding"])

    def test_green_circular_pictogram_is_visual_candidate_not_auto_approved(self):
        pdf=fitz.open()
        page=pdf.new_page(width=540,height=420)
        rgb=np.full((90,90,3),255,dtype=np.uint8)
        cv2.circle(rgb,(45,45),28,(35,105,35),-1)
        encoded=io.BytesIO()
        Image.fromarray(rgb).save(encoded,format="PNG")
        page.insert_image(fitz.Rect(235,180,325,270),stream=encoded.getvalue())
        source=pdf.tobytes()
        pdf.close()
        found=detect_pdf_marks(source,"recycling_shape.pdf")
        candidates=[x for x in found if x["code"]=="RECYCLING"]
        self.assertFalse(candidates)  # Plain green circles are not recycling logos

    def test_recycling_image_and_restored_korean_notice_are_checked_together(self):
        found=[{"file":"x.pdf","page":1,"code":"RECYCLING",
                "label":"재활용 마크","status":"CANDIDATE",
                "bbox":[20,30,60,70],"method":"green_circular_pixel_candidate"}]
        clean=[{"file":"x.pdf","extracted":"적절한 분리배출 및 적합한 시설에서 처리시 재활용 가능."}]
        results=review_mark_rules(found,[],[{"file":"x.pdf"}],"x.pdf",clean)
        category=next(r for r in results if r["rule_id"]=="IMG-RECYCLING")
        self.assertNotIn("한국어 분리배출 안내 문구 확인 필요",category["finding"])
        self.assertEqual(category["status"],"REVIEW")

    def test_world_badge_plus_recovered_citation_is_source_co_presence(self):
        found=[{"file":"x.pdf","page":1,"code":"WORLD_NO1",
                "label":"세계 1위 엠블럼","status":"DETECTED",
                "bbox":[20,30,60,70],"method":"red_world_badge_pixels"}]
        clean=[{"file":"x.pdf","extracted":"테팔 세계판매 1위. Euromonitor International Limited, Home and Garden 2026 에디션, 2025 기준"}]
        result=review_mark_rules(found,[],[{"file":"x.pdf"}],"x.pdf",clean)
        r=next(x for x in result if x["rule_id"]=="IMG-WORLD_NO1")
        self.assertEqual(r["status"],"OK")
        self.assertNotIn("각주 확인 필요",r["finding"])

    def test_france_badge_only_if_manufacture_france(self):
        pdf=fitz.open()
        page=pdf.new_page(width=520,height=420)
        page.insert_text((220,205),"MADE IN FRANCE",fontsize=12)
        source=pdf.tobytes()
        pdf.close()
        china=detect_pdf_marks(source,"france.pdf",{"manufacturing_country":"CHINA"})
        self.assertFalse(any(x["code"]=="MADE_IN_FRANCE" for x in china))
        france=detect_pdf_marks(source,"france.pdf",{"manufacturing_country":"FRANCE"})
        self.assertFalse(any(x["code"]=="MADE_IN_FRANCE" for x in france))  # Text alone is not badge
        self.assertFalse(any(x["code"]=="MADE_IN_FRANCE" and x["status"]=="DETECTED"
                             for x in france))

if __name__=="__main__":
    unittest.main()
