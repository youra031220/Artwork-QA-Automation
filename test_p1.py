"""P1 unit and regression tests using synthetic text only."""
import io
import json
import unittest
from zipfile import ZipFile

from phrase_matcher import match_phrases
from rule_engine import evaluate_rules, summarize_matches
from condition_engine import evaluate_conditions
from bilingual_engine import evaluate_bilingual
from symbol_detector import inspect_symbols
from qa_report import export_p1
from ui_labels import product_title, product_labels, display_file_table, readable_ocr_review
from ocr_review import combine_damaged_coating, combine_damaged_attribution
from unittest.mock import patch
import fitz
from embedded_reference import load_master


def master():
    phrases=[
        ("P1","열원","인덕션 사용 가능","ALL HOBS + INDUCTION","R1"),
        ("P2","열원","인덕션 사용 불가","ALL HOBS EXCEPT INDUCTION","R1"),
        ("P3","품질","최대 40% 수납 공간 절약","UP TO 40% SPACE SAVING","R2"),
        ("P4","주의사항","사용 시 주의하세요","CAUTION","R3"),
        ("P5","주의사항","제품을 세척하세요","WASH","R3"),
    ]
    return {
        "phrases":[dict(phrase_id=p,category_id=c,korean_original=k,
                        english_original=e,approval_status="UNVERIFIED",
                        source_row=i+10) for i,(p,c,k,e,r) in enumerate(phrases)],
        "variants":[dict(phrase_id=p,rule_id=r,applicability="") for p,c,k,e,r in phrases],
        "rules":[
            dict(rule_id="R1",category="열원",rule_type="EXACTLY_ONE",
                 min_count=1,max_count=1,condition_expression="X=1"),
            dict(rule_id="R2",category="품질",rule_type="AT_LEAST_ONE",
                 min_count=1,max_count=None,condition_expression="X>=1"),
            dict(rule_id="R3",category="주의사항",rule_type="ALL_REQUIRED",
                 min_count=2,max_count=2,condition_expression="ALL"),
            dict(rule_id="R4",category="재활용",rule_type="CONDITIONAL",
                 min_count=1,max_count=1,condition_expression="logo exists"),
        ],
    }


def group(text,page=1,damage=False):
    return dict(file="example.pdf",page=page,paragraph=text,numeric_review=damage,
                line_indices=[0],source_coordinates=[
                    dict(bbox=[10,10,90,25],page=page,line_index=0)])


class DamagedCoatingReviewTests(unittest.TestCase):
    def test_ocr_coating_forms_one_review_item_and_keeps_native_evidence(self):
        doc=fitz.open()
        doc.new_page(width=900,height=1800)
        content=doc.tobytes()
        doc.close()
        texts=["테팔�기본�코팅�대비�최대", "�배�더�오래가는",
               "엑스트라�라이프�논스틱�코팅"]
        rows=[{"file":"sample.pdf","page":1,"dir_x":-1.0} for _ in range(3)]
        groups=[]
        for i,text in enumerate(texts):
            groups.append({
                "file":"sample.pdf","page":1,"paragraph":text,
                "line_indices":[i],"line_count":1,
                "status":"수치 대조 필요","numeric_review":True,
                "source_coordinates":[{"page":1,"line_index":i,
                                       "bbox":[320,1340+i*11,420,1362+i*11]}],
                "raw_evidence_ids":[f"p1:b{i}:l0"],
                "numeric_tokens":[],"ocr_candidates":[],"warnings":[]
            })
        reading=("테팔 기본 코팅 대비 최대 4배 더 오래가는 "
                 "엑스트라 라이프 논스틱 코팅")
        with patch("ocr_review._ocr_coating",return_value=reading):
            result=combine_damaged_coating(groups,rows,{"sample.pdf":content})
        self.assertEqual(len(result),1)
        self.assertEqual(result[0]["paragraph"],reading)
        self.assertEqual(result[0]["original_paragraph"]," / ".join(texts))
        self.assertTrue(result[0]["numeric_review"])
        self.assertTrue(result[0]["ocr_reconstructed"])
        self.assertEqual(len(result[0]["source_coordinates"]),3)
        self.assertEqual([g["paragraph"] for g in groups],texts)
        match=match_phrases(result,master())[0]
        self.assertEqual(match["status"],"OCR_REVIEW")
        self.assertEqual(match["original_extracted"]," / ".join(texts))

    def test_no_ocr_result_does_not_invent_digit_or_join_groups(self):
        doc=fitz.open()
        doc.new_page(width=900,height=1800)
        payload=doc.tobytes()
        doc.close()
        groups=[
            {"file":"sample.pdf","page":1,"paragraph":t,
             "line_indices":[i],"source_coordinates":[{"bbox":
                    [320,1340+i*11,420,1362+i*11]}]}
            for i,t in enumerate(["테팔�기본�코팅�대비�최대","�배�더�오래가는",
                                  "엑스트라�라이프�논스틱�코팅"])
        ]
        rows=[dict(dir_x=-1.0) for _ in range(3)]
        with patch("ocr_review._ocr_coating",return_value=None):
            result=combine_damaged_coating(groups,rows,{"sample.pdf":payload})
        self.assertEqual(result,groups)


class EuromonitorOCRReviewTests(unittest.TestCase):
    def test_fragmented_2026_2025_attribution_is_one_review_entry(self):
        doc=fitz.open()
        doc.new_page(width=1300,height=1800)
        pdf=doc.tobytes()
        doc.close()
        texts=[
            "테팔 세계판매 �위 주방용품. Euromonitor International Limited, Home and Garden 2026",
            "에디션, 주방용품 카테고리 브랜드 매출, ���� 기준",
        ]
        groups=[{
            "file":"sample.pdf","page":1,"paragraph":value,
            "line_indices":[i],"line_count":1,"warnings":[],
            "source_coordinates":[{"bbox":[700,1400+9*i,930,1420+9*i]}],
            "ocr_candidates":[],"raw_evidence_ids":[str(i)],
            "numeric_tokens":[],
        } for i,value in enumerate(texts)]
        with patch("ocr_review._ocr_attribution",return_value=("2026","2025")):
            final=combine_damaged_attribution(groups,{"sample.pdf":pdf})
        self.assertEqual(len(final),1)
        self.assertIn("세계판매 1위",final[0]["paragraph"])
        self.assertIn("2025 기준",final[0]["paragraph"])
        self.assertTrue(final[0]["numeric_review"])
        self.assertIn("����",final[0]["original_paragraph"])
        with patch("ocr_review._ocr_attribution",return_value=None):
            no_ocr=combine_damaged_attribution(groups,{"sample.pdf":pdf})
        self.assertEqual(no_ocr,groups)


class ReviewerDisplayTests(unittest.TestCase):
    def test_pdf_derived_label_and_duplicate_disambiguation(self):
        meta = [
            dict(file="very_long_private_filename_a.pdf", range_name="Mint Calm",
                 product_type_standard="SAUCEPAN", size_cm=16),
            dict(file="very_long_private_filename_b.pdf", range_name="Mint Calm",
                 product_type_standard="SAUCEPAN", size_cm=16),
        ]
        self.assertEqual(product_title(meta[0]), "Mint Calm · 편수냄비 · 16cm")
        mapping = product_labels(meta, [x["file"] for x in meta])
        self.assertNotEqual(mapping[meta[0]["file"]], mapping[meta[1]["file"]])
        self.assertNotIn(".pdf", mapping[meta[0]["file"]])
        original = [{"file": meta[0]["file"], "status": "OK"}]
        shown = display_file_table(original, mapping)
        self.assertEqual(shown[0]["제품"], mapping[meta[0]["file"]])
        self.assertNotIn("file", shown[0])
        self.assertEqual(original[0]["file"], meta[0]["file"])

    def test_ocr_candidate_is_labeled_and_source_is_untouched(self):
        row={
            "status":"OCR_REVIEW",
            "extracted":"쉬운�요리를�위한�강력한�코팅, 가벼운�무게",
            "ocr_candidates":[{"text":"쉬운 요리를 위한 강력한 코팅, 가벼운 무게"}],
        }
        shown=readable_ocr_review(row)
        self.assertIn("OCR 읽기 후보 · 확인 필요",shown)
        self.assertIn("쉬운 요리를 위한",shown)
        self.assertIn("\ufffd",row["extracted"])
        unconfirmed=dict(row,ocr_candidates=[{"text":"불확실"}])
        self.assertEqual(readable_ocr_review(unconfirmed),row["extracted"])


    def test_unknown_label_does_not_guess_from_filename(self):
        mapping = product_labels([dict(file="Casserole_18cm_foo.pdf",
                                      range_name=None,
                                      product_type_standard="UNKNOWN",
                                      size_cm=None)], ["Casserole_18cm_foo.pdf"])
        self.assertEqual(mapping["Casserole_18cm_foo.pdf"], "제품정보 확인 필요")


class EmbeddedReferenceIntegrationTests(unittest.TestCase):
    def test_real_reference_can_match_without_workbook_upload(self):
        source=load_master()
        self.assertGreaterEqual(len(source["phrases"]),200)
        sample=next(p for p in source["phrases"]
                    if p.get("korean_original") and len(p["korean_original"])>=12)
        entry=group(sample["korean_original"])
        matched=match_phrases([entry],source)
        self.assertEqual(len(matched),1)
        self.assertIn(matched[0]["status"],
                      ("EXACT_MATCH","AMBIGUOUS_MATCH"))
        self.assertEqual(matched[0]["extracted"],sample["korean_original"])
        rules=evaluate_rules(matched,source,"example.pdf")
        self.assertEqual(len(rules),len(source["rules"]))

class PhraseMatcherTests(unittest.TestCase):
    def test_exact(self):
        x=match_phrases([group("인덕션 사용 가능")],master())[0]
        self.assertEqual(x["status"],"EXACT_MATCH")
        self.assertEqual(x["phrase_id"],"P1")
        self.assertEqual(x["approval_status"],"UNVERIFIED")
        self.assertEqual(len(x["source_coordinates"]),1)

    def test_whitespace_and_numeric(self):
        x=match_phrases([group("최대 40 % 수납 공간 절약")],master())[0]
        self.assertEqual(x["status"],"NORMALIZED_MATCH")
        x=match_phrases([group("최대 30% 수납 공간 절약")],master())[0]
        self.assertEqual(x["status"],"NUMERIC_MISMATCH")
        self.assertEqual(x["phrase_id"],"P3")

    def test_euromonitor_202x_years_are_independent_variables(self):
        ref=("테팔 세계판매 1위 주방용품. Euromonitor International Limited, "
             "Home and Garden 202X 에디션, 주방용품 카테고리 브랜드 매출, 202X 기준")
        actual=("테팔 세계판매 1위 주방용품. Euromonitor International Limited, "
                "Home and Garden 2026 에디션, 주방용품 카테고리 브랜드 매출, 2025 기준")
        model=master()
        model["phrases"].append(dict(phrase_id="P202",category_id="세계 1위",
                                     korean_original=ref,english_original="",
                                     approval_status="UNVERIFIED",source_row=202))
        model["variants"].append(dict(phrase_id="P202",rule_id="R2",applicability=""))
        result=match_phrases([group(actual)],model)[0]
        self.assertEqual(result["status"],"VARIABLE_MATCH")
        self.assertEqual(result["phrase_id"],"P202")
        self.assertEqual(result["differences"],"연도 변수: 2026, 2025")
        self.assertNotIn("불일치",result["differences"])
        swapped=actual.replace("2026 에디션","2027 에디션").replace("2025 기준","2026 기준")
        next_year=match_phrases([group(swapped)],model)[0]
        self.assertEqual(next_year["status"],"VARIABLE_MATCH")
        wrong=actual.replace("2025 기준","2015 기준")
        self.assertNotEqual(match_phrases([group(wrong)],model)[0]["status"],"VARIABLE_MATCH")

    def test_multiplier_placeholder_requires_human_range_check(self):
        m=master()
        m["phrases"].append(dict(
            phrase_id="P6",category_id="특장점",
            korean_original="최대 Y배 더 오래가는 코팅",
            english_original="UP TO YX LONGER LASTING",
            approval_status="UNVERIFIED",source_row=99))
        m["variants"].append(dict(phrase_id="P6",rule_id="R2",applicability=""))
        match=match_phrases([group("최대 3배 더 오래가는 코팅")],m)[0]
        self.assertEqual(match["status"],"TEXT_MISMATCH")
        self.assertEqual(match["phrase_id"],"P6")
        self.assertEqual(match["differences"],"Y=3")

    def test_numeric_damage_requires_review(self):
        x=match_phrases([group("최대 ��% 수납 공간 절약",damage=True)],master())[0]
        self.assertEqual(x["status"],"OCR_REVIEW")

    def test_unregistered_is_never_deleted(self):
        rows=[group("처음 출시한 제품 문구"),group("완전히 새로운 국문 광고")]
        matches=match_phrases(rows,master())
        self.assertEqual(len(matches),len(rows))
        self.assertTrue(all(m["status"]=="UNREGISTERED" for m in matches))
        self.assertEqual([m["extracted"] for m in matches],
                         [r["paragraph"] for r in rows])

    def test_damaged_warranty_with_clean_substring_requires_review(self):
        m=master()
        actual=("테팔은 모든 제조 과정 중의 결함에 대하여 구입일로부터 �년간 "
                "품질 보증 제도를 실시합니다. "
                "제품 내부와 외부에 생긴 스크래치 또는 사용 중 발생한 변색과 얼룩 등은 해당되지 않습니다.")
        m["phrases"].append(dict(
            phrase_id="WARRANTY", category_id="품질 보증",
            korean_original="제품 내부와 외부에 생긴 스크래치 또는 사용 중 발생한 변색과 얼룩 등은 해당되지 않습니다.",
            english_original="Your local statutory rights are not affected",
            approval_status="UNVERIFIED", source_row=34,
        ))
        result=match_phrases([group(actual)],m)[0]
        self.assertEqual(result["status"],"OCR_REVIEW")
        self.assertNotIn("숫자·단위 불일치", result["differences"])
        rules=evaluate_rules([result],m,"example.pdf")
        self.assertNotIn(result["status"],("EXACT_MATCH","NORMALIZED_MATCH"))
        self.assertEqual(result["extracted"],actual)

    def test_clean_phrase_remains_match_after_damaged_counterpart_guard(self):
        matched=match_phrases([group("인덕션 사용 가능")],master())[0]
        self.assertEqual(matched["status"],"EXACT_MATCH")

    def test_missing_terminal_period_is_not_qr_mismatch(self):
        m=master()
        m["phrases"].append(dict(
            phrase_id="PQR",category_id="사용방법",
            korean_original="QR 코드를 스캔하여 최적의 사용 및 관리방법을 확인하세요.",
            english_original="Get the best use & care advice",
            approval_status="UNVERIFIED",source_row=30
        ))
        r=match_phrases([group("QR 코드를 스캔하여 최적의 사용 및 관리방법을 확인하세요")],m)[0]
        self.assertEqual(r["status"],"NORMALIZED_MATCH")

    def test_broken_korean_spacing_is_not_numeric_mismatch(self):
        m=master()
        m["phrases"].append(dict(
            phrase_id="PC",category_id="코팅",
            korean_original="엑스트라 라이프 논스틱 코팅",
            english_original="EXTRA LIFE NON-STICK",
            approval_status="UNVERIFIED",source_row=31
        ))
        result=match_phrases([group("엑스트라�라이프�논스틱�코팅",damage=True)],m)[0]
        self.assertEqual(result["status"],"OCR_REVIEW")
        self.assertNotEqual(result["differences"],"숫자·단위 불일치")


    def test_negation_is_not_passed(self):
        x=match_phrases([group("인덕션 사용 불가")],master())[0]
        self.assertEqual(x["phrase_id"],"P2")
        self.assertNotEqual(x["phrase_id"],"P1")

    def test_no_bare_short_fragment_match(self):
        x=match_phrases([group("최대")],master())[0]
        self.assertNotIn(x["status"],("EXACT_MATCH","NORMALIZED_MATCH"))


class RuleTests(unittest.TestCase):
    def test_single_variant_repeated_is_not_conflict(self):
        rows=[group("인덕션 사용 가능"),group("인덕션 사용 가능",2)]
        matches=match_phrases(rows,master())
        rules=evaluate_rules(matches,master(),"example.pdf")
        r=next(r for r in rules if r["rule_id"]=="R1")
        self.assertEqual(r["found_occurrences"],2)
        self.assertEqual(r["distinct_variants"],1)
        self.assertEqual(r["status"],"OK")

    def test_two_variants_fail(self):
        matches=match_phrases([group("인덕션 사용 가능"),
                               group("인덕션 사용 불가")],master())
        rules=evaluate_rules(matches,master(),"example.pdf")
        self.assertEqual(next(r for r in rules if r["rule_id"]=="R1")["status"],"FAIL")
        self.assertEqual(next(r for r in rules if r["rule_id"]=="P1-HEAT-CONFLICT")["status"],"FAIL")

    def test_missing_does_not_misreport_approved_fail(self):
        rules=evaluate_rules([],master(),"example.pdf")
        required=next(r for r in rules if r["rule_id"]=="R1")
        self.assertEqual(required["status"],"REVIEW")
        self.assertEqual(required["found_occurrences"],0)

    def test_all_required_partial(self):
        matches=match_phrases([group("사용 시 주의하세요")],master())
        rules=evaluate_rules(matches,master(),"example.pdf")
        self.assertEqual(next(r for r in rules if r["rule_id"]=="R3")["status"],"REVIEW")

    def test_conditional_remains_review(self):
        r=next(r for r in evaluate_rules([],master(),"example.pdf")
               if r["rule_id"]=="R4")
        self.assertEqual(r["applicability"],"UNDETERMINED")
        self.assertEqual(r["status"],"REVIEW")

    def test_english_heat_contradiction_without_korean(self):
        output = evaluate_rules([], master(), "example.pdf", context={
            "raw_pdf_text": "ALL HOBS + INDUCTION / ALL HOBS EXCEPT INDUCTION"
        })
        risk = next(r for r in output if r["rule_id"] == "P1-HEAT-CONFLICT")
        self.assertEqual(risk["status"], "FAIL")

    def test_warranty_scope_uncertain_requiring_review(self):
        mm = [dict(file="example.pdf", extracted="제품 품질보증 2년"),
              dict(file="example.pdf", extracted="스테인리스 품질보증 10년")]
        output = evaluate_rules(mm, master(), "example.pdf")
        risk = next(r for r in output if r["rule_id"] == "P1-WARRANTY-DURATION")
        self.assertEqual(risk["status"], "REVIEW")
        self.assertEqual(risk["distinct_variants"], 2)

    def test_report_archives_raw_and_unregistered(self):
        m=match_phrases([group("인덕션 사용 가능"),group("신규 문구")],master())
        rr=evaluate_rules(m,master(),"example.pdf")
        summary=summarize_matches(m,rr)
        data=export_p1(m,rr,summary)
        with ZipFile(io.BytesIO(data)) as z:
            self.assertEqual(len(z.namelist()),7)
            items=json.loads(z.read("p1_unregistered.json"))
            self.assertEqual(items[0]["extracted"],"신규 문구")
            self.assertEqual(summary[0]["unregistered_count"],1)


class BilingualAndSymbolsTests(unittest.TestCase):
    def test_english_found_missing_korean_is_review(self):
        evidence=[dict(file="example.pdf", raw_evidence=[dict(
            text="ALL HOBS EXCEPT INDUCTION")])]
        results=evaluate_bilingual(master(), [], evidence, "example.pdf")
        matched=next(r for r in results if r["rule_id"]=="P1-BILINGUAL-P2")
        self.assertEqual(matched["status"],"REVIEW")

    def test_bilingual_pair_found_is_ok_not_approved(self):
        evidence=[dict(file="example.pdf", raw_evidence=[dict(
            text="ALL HOBS EXCEPT INDUCTION")])]
        mm=match_phrases([group("인덕션 사용 불가")],master())
        result=evaluate_bilingual(master(), mm, evidence, "example.pdf")
        matched=next(r for r in result if r["rule_id"]=="P1-BILINGUAL-P2")
        self.assertEqual(matched["status"],"OK")
        self.assertEqual(matched["approval_status"],"UNVERIFIED")

    def test_symbol_absence_is_never_auto_pass(self):
        meta=[dict(file="example.pdf",manufacturing_country="FRANCE")]
        results=inspect_symbols([],meta)
        self.assertTrue(results)
        self.assertTrue(all(r["status"]=="REVIEW" for r in results))

class ConditionTests(unittest.TestCase):
    def test_france_badge_never_auto_pass(self):
        results=evaluate_conditions([dict(file="example.pdf",
                                         manufacturing_country="FRANCE")],[],[])
        r=next(r for r in results if r["rule_id"]=="P1-FR-BADGE")
        self.assertEqual(r["status"],"REVIEW")

    def test_18cm_stewpot_translation_is_review(self):
        results=evaluate_conditions([
            dict(file="example.pdf",manufacturing_country="CHINA",
                 product_type_standard="STEWPOT",size_cm=18,
                 has_lid=False)
        ],[],[])
        result=next(r for r in results if r["rule_id"]=="P1-18CM-STEW")
        self.assertEqual(result["status"],"REVIEW")
        self.assertIn("뚝배기",result["finding"])

    def test_english_heat_requires_korean(self):
        summaries=[dict(file="example.pdf",raw_evidence=[
            dict(text="ALL HOBS EXCEPT INDUCTION")
        ])]
        metadata=[dict(file="example.pdf",manufacturing_country="CHINA")]
        results=evaluate_conditions(metadata,[],summaries)
        r=next(r for r in results if r["rule_id"]=="P1-EN-KO-HEAT")
        self.assertEqual(r["status"],"REVIEW")


if __name__=="__main__":
    unittest.main()
