"""P1 unit and regression tests using synthetic text only."""
import io
import json
import unittest
from zipfile import ZipFile

from phrase_matcher import match_phrases
from rule_engine import evaluate_rules, summarize_matches
from condition_engine import evaluate_conditions
from qa_report import export_p1


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


class ConditionTests(unittest.TestCase):
    def test_france_badge_never_auto_pass(self):
        results=evaluate_conditions([dict(file="example.pdf",
                                         manufacturing_country="FRANCE")],[],[])
        r=next(r for r in results if r["rule_id"]=="P1-FR-BADGE")
        self.assertEqual(r["status"],"REVIEW")

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
