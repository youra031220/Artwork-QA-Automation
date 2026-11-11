"""Contextual P1 checks based on product metadata and native PDF evidence.

Unresolved logo/images cannot be treated as absent. All results are REVIEW
unless a precise source-backed contradiction is established.
"""
import re


def _raw_lines(summaries, filename):
    return [x for page in summaries if page.get("file")==filename
            for x in page.get("raw_evidence", [])]


def evaluate_conditions(metadata, matches, summaries):
    results=[]
    for product in metadata:
        filename=product["file"]
        lines=_raw_lines(summaries, filename)
        source=" ".join(x.get("text","") for x in lines)
        own=[m for m in matches if m["file"]==filename]
        ko=" ".join(m["extracted"] for m in own)
        def add(rule, category, status, reason, evidence="", condition=""):
            results.append({
                "file":filename,"rule_id":rule,"category":category,
                "rule_type":"CONDITIONAL","condition":condition,"min_count":0,
                "max_count":None,"found_occurrences":int(bool(evidence)),
                "distinct_variants":int(bool(evidence)),
                "matched_phrase_ids":[],"review_candidates":[],
                "applicability":"APPLICABLE" if evidence else "UNDETERMINED",
                "status":status,"finding":reason,
                "source_reference":"P1 product/native evidence",
                "evidence":evidence,
            })
        country=product.get("manufacturing_country")
        if country=="FRANCE":
            add("P1-FR-BADGE","제조국 마크","REVIEW",
                "프랑스 제조 제품: 지정 사각 영역 필수 배지는 이미지 검수 필요",
                "MADE IN FRANCE", "manufacturing_country == FRANCE")
        elif country is None:
            add("P1-FR-BADGE","제조국 마크","REVIEW",
                "제조국 불명: 프랑스 제조 필수 배지 적용 여부 확인 필요")
        # An actual glass lid is not established by generic '+CV' alone.
        if product.get("has_lid"):
            add("P1-GLASS-LID","재활용","REVIEW",
                "뚜껑 포함: 유리 재질 확인 및 재활용 안내의 제외 문구 검토",
                str(product.get("product_type_raw") or "lid"),
                "has_lid == True; lid_material must be verified")
        if re.search(r"WORLD\s*(?:N\s*[°ºo]?\s*1|NO[.]?\s*1)|세계판매\s*1위",source,re.I):
            has_source = bool(re.search(r"Euromonitor\s+International",source,re.I))
            year_ed=re.search(r"Home\s+and\s+Garden\s+(\d{4})", source, re.I)
            year_base=re.search(r"(\d{4})\s*기준",ko)
            add("P1-WORLD-1","세계 1위 출처","REVIEW",
                ("각주 확인: " + ("출처 명칭 확인, " if has_source else "출처 명칭 미확인, ")
                 + ("에디션 " + year_ed.group(1) if year_ed else "에디션 연도 확인 필요")
                 + ", " + ("매출 기준 " + year_base.group(1) if year_base else "매출 기준 연도 확인 필요")
                 + " · 엠블럼·각주 연결은 시각 검토 필요"),
                "Euromonitor" if has_source else "", "world no.1 mark -> Korean source footnote")
        # Explicit English heat-source phrases should have corresponding Korean.
        heat_en = re.search(r"ALL\s+HOBS\s+EXCEPT\s+INDUCTION",source,re.I)
        if heat_en:
            korean=bool(re.search(r"인덕션\s*사용\s*불가|인덕션\s*제외",ko))
            add("P1-EN-KO-HEAT","영문·국문 대응",
                "OK" if korean else "REVIEW",
                "영문 인덕션 제외 표기와 대응 국문 " + ("함께 발견" if korean else "미발견 · 수동 확인"),
                heat_en.group(), "English ALL HOBS EXCEPT INDUCTION -> Korean exception")
        # Recyclability mark/label implies the corresponding Korean
        # disposal notice may be required. Native text cannot prove an image
        # symbol is present or absent.
        if re.search(r"RECYCLABLE|RECYCLING|ACIER\s+RECYCLABLE|재활용\s*가능",source,re.I):
            has_disposal=bool(re.search(r"적절한\s*분리\s*배출|적절한\s*분리배출",ko))
            lid_glass=product.get("lid_material") in ("glass","GLASS")
            excluded=bool(re.search(r"유리\s*뚜껑\s*제외",ko))
            reason=("재활용 텍스트 앵커 발견. " +
                    ("분리배출 안내 국문 확인됨" if has_disposal
                     else "분리배출 안내 국문 미확인") +
                    (" · 유리 뚜껑 제외 표기 확인 필요" if lid_glass and not excluded else ""))
            add("P1-RECYCLE","재활용","REVIEW",reason,
                "RECYCLABLE", "recycle label -> Korean disposal notice")
        if product.get("product_type_standard")=="STEWPOT" and product.get("size_cm")==18:
            found=bool(re.search(r"뚝배기",ko))
            add("P1-18CM-STEW","제품 타입·번역","REVIEW",
                "18cm 양수냄비 번역 예외: " +
                ("뚝배기 문구 발견 · 맥락 확인" if found else "뚝배기 표기 미발견"),
                "18cm STEWPOT", "size_cm == 18 and type == STEWPOT")
        # Source performance multipliers are variable by range (not a
        # single approved fixed number). Keep candidate values for QA.
        coating_numbers=re.findall(r"(?:최대\s*)?(\d{1,2})\s*배.{0,20}코팅",ko)
        if coating_numbers:
            values=sorted(set(map(int,coating_numbers)))
            add("P1-COATING-Y","성능 수치","REVIEW",
                "코팅 성능 배수 발견: "+", ".join(map(str,values))+
                "배 · 적용 레인지의 승인 변수와 대조 필요",
                ", ".join(coating_numbers), "Y = range-specific multiplier")
        size=product.get("size_cm")
        if size and product.get("product_type_standard") and product.get("product_type_standard")!="UNKNOWN":
            mm=re.findall(r"(?<!\d)(\d{2})\s*cm\b",ko,re.I)
            other=sorted(set(int(x) for x in mm if int(x)!=int(size)))
            if other:
                add("P1-SIZE","제품 크기","REVIEW",
                    "작업정보 " + str(size) + "cm와 다른 국문 크기 발견: "
                    + ", ".join(map(str,other)) + "cm · 다른 구성품 치수 여부 확인",
                    ", ".join(mm), "size_cm")
    return results
