import unittest
from document_policy import (evaluate_document_policy, compare_range_messages,
    evaluate_bilingual_values, evaluate_recycling_exclusivity)


def row(text, filename="sample.pdf", category="", status="EXACT_MATCH"):
    return {"file":filename,"page":1,"extracted":text,"status":status,
            "category":category,"reference_korean":text}


def raw(*texts, filename="sample.pdf"):
    return [{"file":filename,"page":1,
             "raw_evidence":[{"text":x,"bbox":[10,20+idx*10,150,30+idx*10]}
                             for idx,x in enumerate(texts)]}]


class CorrectionPolicyTests(unittest.TestCase):
    OLD="모든 열원 사용 가능 (인덕션 제외)"
    NEW="가스레인지, 핫플레이트, 하이라이트 사용 가능 (인덕션 사용 불가)"

    def evaluate(self, korean, english=(), filename="sample.pdf", metadata=()):
        return evaluate_document_policy(
            [row(t,filename) for t in korean],raw(*english,filename=filename),
            list(metadata),filename)

    def test_legacy_nih_wording_is_fail_even_though_meaning_is_correct(self):
        results=self.evaluate([self.OLD],["ALL HOBS EXCEPT INDUCTION"])
        risk=next(r for r in results if r["rule_id"]=="DOC-NIH-LEGACY")
        self.assertEqual(risk["status"],"FAIL")
        self.assertEqual(risk["corrected_text"],self.NEW)
        self.assertFalse(any(r["rule_id"]=="DOC-IH-SEMANTIC-CONFLICT" for r in results))

    def test_current_nih_wording_and_english_are_consistent(self):
        self.assertFalse(any(r["status"]=="FAIL" for r in
            self.evaluate([self.NEW],["ALL HOBS EXCEPT INDUCTION"])))

    def test_old_and_new_non_induction_wording_are_not_allowed_together(self):
        rules=self.evaluate([self.OLD,self.NEW],["ALL HOBS EXCEPT INDUCTION"])
        self.assertEqual(next(r for r in rules if r["rule_id"]=="DOC-NIH-MIXED-WORDING")["status"],"FAIL")

    def test_opposite_heating_conditions_fail_even_when_korean_missing(self):
        rr=self.evaluate(["인덕션 포함 모든 열원 사용 가능"],["ALL HOBS EXCEPT INDUCTION"])
        self.assertEqual(next(x for x in rr if x["rule_id"]=="DOC-IH-SEMANTIC-CONFLICT")["status"],"FAIL")

    def test_non_induction_english_does_not_misfire_induction_positive(self):
        self.assertFalse(any(x["rule_id"]=="DOC-IH-SEMANTIC-CONFLICT" for x in
            self.evaluate([self.NEW],["ALL HOBS EXCEPT INDUCTION"])))

    def test_world_source_wrong_korean_edition_matches_email_error(self):
        ko=("테팔 세계판매 1위 주방용품. Euromonitor International Limited, "
            "Home and Garden 2025 에디션, 주방용품 카테고리 브랜드 매출, 2025 기준")
        en=("Tefal world N°1 in cookware. Source : Euromonitor International "
            "Limited, Home and Garden 2026 edition, brand retail value RSP, 2025 data.")
        results=self.evaluate([ko],[en])
        err=next(x for x in results if x["rule_id"]=="DOC-WORLD-EDITION-LANG")
        self.assertEqual(err["status"],"FAIL")
        self.assertFalse(any(x["rule_id"]=="DOC-WORLD-DATA-LANG" for x in results))

    def test_world_source_years_are_independent_and_correct(self):
        ko=("테팔 세계판매 1위 주방용품. Euromonitor International Limited, "
            "Home and Garden 2026 에디션, 주방용품 카테고리 브랜드 매출, 2025 기준")
        en=("Tefal world N°1 in cookware. Source : Euromonitor International "
            "Limited, Home and Garden 2026 edition, brand retail value RSP, 2025 data.")
        self.assertFalse(any(r["rule_id"].startswith("DOC-WORLD") for r in self.evaluate([ko],[en])))

    def test_data_year_differs_from_edition_year_and_from_other_language(self):
        ko="테팔 세계판매 1위. Euromonitor International Limited, Home and Garden 2026 에디션, 2024 기준"
        en="Tefal world N°1 in cookware. Source : Euromonitor International Limited, Home and Garden 2026 edition, 2025 data."
        result=self.evaluate([ko],[en])
        self.assertEqual(next(x for x in result if x["rule_id"]=="DOC-WORLD-DATA-LANG")["status"],"FAIL")

    def test_unknown_year_policy_is_review_not_hardcoded_edition_data_plus_one(self):
        ko="테팔 세계판매 1위. Euromonitor International Limited, Home and Garden 2027 에디션, 2026 기준"
        rr=self.evaluate([ko],["Tefal world N°1 in cookware. Source: Euromonitor International Limited, Home and Garden 2027 edition, 2026 data."])
        self.assertEqual(next(r for r in rr if r["rule_id"]=="DOC-WORLD-YEAR-POLICY")["status"],"REVIEW")

    def test_warranty_english_korean_number_mismatch(self):
        rr=self.evaluate(["구입일로부터 2년간 품질 보증 제도를 실시합니다"],
                         ["This product is guaranteed for 5 years against manufacturing defects."])
        self.assertEqual(next(r for r in rr if r["rule_id"]=="DOC-WARRANTY-LANGUAGE")["status"],"FAIL")

    def test_warranty_2yr_and_stainless_10yr_are_review_not_false_fail(self):
        rr=self.evaluate(["제품 품질 보증 2년","스테인리스 품질 보증 10년"],())
        self.assertEqual(next(r for r in rr if r["rule_id"]=="DOC-WARRANTY-SCOPE")["status"],"REVIEW")

    def test_glass_lid_context_is_review_not_auto_fail(self):
        rr=self.evaluate(["적절한 분리배출 및 적합한 시설에서 처리시 재활용 가능."],(),
                         metadata=[{"file":"sample.pdf","lid_material":"glass"}])
        self.assertEqual(next(r for r in rr if r["rule_id"]=="DOC-RECYCLE-GLASS")["status"],"REVIEW")

    def test_unknown_lid_material_does_not_create_false_failure(self):
        rr=self.evaluate(["적절한 분리배출 및 적합한 시설에서 처리시 재활용 가능."],(),
                         metadata=[{"file":"sample.pdf","lid_material":"unknown"}])
        self.assertFalse(any(r["rule_id"]=="DOC-RECYCLE-GLASS" for r in rr))

    def test_bilingual_multiplier_actual_values_conflict(self):
        ko=row("테팔 기본 코팅 대비 최대 3배 더 오래가는 코팅")
        ko["reference_english"]="UP TO 5X MORE RESISTANT"
        evidence=raw("UP TO 5X MORE RESISTANT")
        violations=evaluate_bilingual_values([ko],evidence,"sample.pdf")
        self.assertEqual(next(r for r in violations if r["rule_id"]=="DOC-BILINGUAL-MULTIPLIER")["status"],"FAIL")

    def test_bilingual_percentage_actual_values_conflict(self):
        ko=row("최대 40% 수납 공간 절약")
        ko["reference_english"]="UP TO 30% SPACE SAVING"
        violations=evaluate_bilingual_values([ko],raw("UP TO 30% SPACE SAVING"),"sample.pdf")
        self.assertEqual(next(r for r in violations if r["rule_id"]=="DOC-BILINGUAL-PERCENT")["status"],"FAIL")

    def test_missing_english_value_is_not_invented_from_master(self):
        ko=row("최대 40% 수납 공간 절약")
        ko["reference_english"]="UP TO 30% SPACE SAVING"
        self.assertEqual(evaluate_bilingual_values([ko],raw("FRENCH OTHER SOURCE"),"sample.pdf"),[])

    def test_two_distinct_recycling_qualifiers_require_review(self):
        mm=[row("적절한 분리배출 및 적합한 시설에서 처리시 재활용 가능."),
            row("적절한 분리배출 및 적합한 시설에서 처리시 재활용 가능 (유리뚜껑 제외).")]
        rr=evaluate_recycling_exclusivity(mm,[],"sample.pdf")
        self.assertEqual(rr[0]["status"],"REVIEW")
        self.assertEqual(rr[0]["rule_id"],"DOC-RECYCLE-MIXED")

    def test_single_recycling_notice_containing_exclusion_is_not_conflict(self):
        mm=[row("적절한 분리배출 및 적합한 시설에서 처리시 재활용 가능 (유리뚜껑 제외).")]
        self.assertEqual(evaluate_recycling_exclusivity(mm,[],"sample.pdf"),[])

    def test_product_isolation_across_two_uploaded_documents(self):
        matches=[row(self.OLD,"first.pdf"),row(self.NEW,"second.pdf")]
        evidence=raw("ALL HOBS EXCEPT INDUCTION",filename="first.pdf")+raw(
            "ALL HOBS EXCEPT INDUCTION",filename="second.pdf")
        a=evaluate_document_policy(matches,evidence,[],"first.pdf")
        b=evaluate_document_policy(matches,evidence,[],"second.pdf")
        self.assertTrue(any(r["rule_id"]=="DOC-NIH-LEGACY" for r in a))
        self.assertFalse(any(r["rule_id"]=="DOC-NIH-LEGACY" for r in b))

    def test_same_range_different_key_message_is_review(self):
        mm=[row("요리는 쉽게", "a.pdf",category="키 메시지"),
            row("더 쉽게 요리", "b.pdf",category="키 메시지")]
        metas=[dict(file="a.pdf",range_name="Same Range"),
               dict(file="b.pdf",range_name="Same Range")]
        rr=compare_range_messages(mm,metas)
        self.assertEqual({x["file"] for x in rr},{"a.pdf","b.pdf"})
        self.assertTrue(all(x["status"]=="REVIEW" for x in rr))

    def test_different_ranges_not_compared(self):
        metas=[dict(file="a.pdf",range_name="A"),
               dict(file="b.pdf",range_name="B")]
        mm=[row("첫 번째", "a.pdf",category="키 메시지"),
            row("두 번째", "b.pdf",category="키 메시지")]
        self.assertEqual(compare_range_messages(mm,metas),[])

if __name__=="__main__":
    unittest.main()
