"""재활용 가능 문구 ↔ 유리뚜껑 조건 (원장 P200 / P201).

원장 기준
  * 재활용 로고가 있으면 두 문장 중 정확히 하나가 있어야 한다.
      P200  적절한 분리배출 및 적합한 시설에서 처리시 재활용 가능.
            → 유리뚜껑이 없을 경우
      P201  적절한 분리배출 및 적합한 시설에서 처리 시 재활용 가능합니다. (유리뚜껑 제외)
            → 유리뚜껑이 있을 경우 (LID, GLASS LID 단어 포함 시)
  * 2개 이상 발견 → 오류, 0개 발견 → 발견 실패 표기.

뚜껑 여부는 PDF에서 읽은 글자(제품 유형 표기 포함)로만 판단한다. 원장 문구나
파일명은 근거로 쓰지 않는다. 'EXCEPT LID', 'WITHOUT LID', '4 LIDS'(비교 테스트
각주)처럼 제품 구성이 아닌 문맥의 LID 는 근거에서 뺀다.
"""
import re

GLASS = re.compile(r"(?:[A-Z]+\s+)?WITH\s+GLASS\s+LIDS?|GLASS\s+LIDS?|COUVERCLE\s+EN\s+VERRE|"
                   r"[가-힣]*\s*\(?\s*유리\s*뚜껑(?!\s*제외)\s*(?:포함)?\)?|玻璃蓋|玻璃盖|ฝาแก้ว", re.I)
LID = re.compile(r"[가-힣]+\s*\(\s*뚜껑\s*포함\s*\)|뚜껑\s*포함|"
                 r"(?:[A-Z]+\s+)?WITH\s+(?:THE\s+)?LIDS?\b|\+\s*CV\b|AVEC\s+COUVERCLE|\bLIDS?\b", re.I)
NOT_COMPOSITION = re.compile(
    r"EXCEPT\s+(?:THE\s+)?(?:GLASS\s+)?LIDS?|WITHOUT\s+(?:THE\s+)?LIDS?|"
    r"\d+\s+LIDS?\b|LIDS?\s+REST|\(\s*유리\s*뚜껑\s*제외\s*\)|뚜껑\s*제외|"
    r"뚜껑\s*\d+\s*개", re.I)

WITHOUT_GLASS = "P200"
WITH_GLASS = "P201"


def _snippet(text, match):
    return re.sub(r"\s+", " ", match.group()).strip()


def lid_evidence(observed):
    """Return ('glass' | 'lid' | 'none', evidence snippet)."""
    text = NOT_COMPOSITION.sub(" ", str(observed or ""))
    for kind, pattern in (("glass", GLASS), ("lid", LID)):
        found = [_snippet(text, m) for m in pattern.finditer(text)]
        if found:
            # Show Korean or English evidence first when the PDF has it.
            found.sort(key=lambda v: (not re.search(r"[가-힣]", v), not re.search(r"[A-Za-z]", v)))
            gloss = {"玻璃蓋": "玻璃蓋(중국어 유리뚜껑)", "玻璃盖": "玻璃盖(중국어 유리뚜껑)",
                     "ฝาแก้ว": "ฝาแก้ว(태국어 유리뚜껑)"}
            shown = list(dict.fromkeys(gloss.get(v, v) for v in found))[:2]
            return kind, "', '".join(shown)
    return "none", ""


def judge(observed, matches):
    """Judge the recycling sentence for one product.

    ``matches`` are this product's phrase-matcher results. Returns a dict with
    ``status`` (OK / FAIL / MISSING), ``message`` for the checklist and
    ``finding`` for the result table (empty when OK).
    """
    lid, evidence = lid_evidence(observed)
    found = [m for m in matches if m.get("phrase_id") in (WITHOUT_GLASS, WITH_GLASS)]
    found_ids = [m["phrase_id"] for m in found]
    required = WITH_GLASS if lid in ("glass", "lid") else WITHOUT_GLASS
    if lid == "glass":
        basis = f"유리뚜껑 포함 (근거: '{evidence}')"
    elif lid == "lid":
        basis = f"뚜껑 포함 (근거: '{evidence}') · 원장 기준 LID 표기 시 유리뚜껑 조건 적용"
    else:
        basis = "뚜껑 표기 없음 → 유리뚜껑 없는 구성"
    need = ("'(유리뚜껑 제외)' 문장" if required == WITH_GLASS
            else "'처리시 재활용 가능.' 문장 (유리뚜껑 제외 표기 없음)")
    if not found:
        return {"status": "MISSING", "lid": lid, "required": required, "found": found_ids,
                "message": f"— 재활용 안내 문구 미발견 · {basis} → 재활용 로고가 있으면 {need} 누락",
                "finding": ""}
    if len(found) >= 2:
        return {"status": "FAIL", "lid": lid, "required": required, "found": found_ids,
                "message": f"✗ 재활용 안내 문구 {len(found)}개 발견 — 하나만 있어야 함 · {basis}",
                "finding": f"재활용 문구가 {len(found)}개 인쇄됨 · 원장 기준 하나만 있어야 함 ({basis})"}
    if found_ids[0] != required:
        printed = ("'(유리뚜껑 제외)' 문장" if found_ids[0] == WITH_GLASS
                   else "'(유리뚜껑 제외)' 없는 문장")
        return {"status": "FAIL", "lid": lid, "required": required, "found": found_ids,
                "message": f"✗ 재활용 문구 조건 불일치 — {basis}인데 {printed} 인쇄 · {need}이어야 함",
                "finding": f"{basis} → {need}이어야 하는데 {printed}이 인쇄됨"}
    return {"status": "OK", "lid": lid, "required": required, "found": found_ids,
            "message": f"✓ 재활용 문구 조건 일치 — {basis} → {need} 확인 · 재활용 마크 확인 필요",
            "finding": ""}
