"""필수 문구 점검 — 엑셀 원장 '필수 조건 여부' 열 기준.

원장 규칙 (텍스트 대조 데이터 C열)
  키 메세지          X=1   없으면 발견 실패
  G7 특장점          X>=1  없으면 발견 실패
  제품타입           X>=1  없으면 발견 실패
  사용가능 열원      X=1   2개 이상 오류 · 0개 발견 실패
  사용방법 QR        X=1   없으면 발견 실패
  품질 보증 문장     X=1   (2/5/10년 · 스테인리스 5/10년 중 하나) 2개 이상 오류 · 0개 발견 실패
  품질 보증 필수 4문장 X=4  하나라도 없으면 발견 실패
조건부 필수(재활용 · 세계 1위)는 로고 유무에 따라 달라지므로 마크 체크리스트에서 다룬다.

판정 근거는 이 PDF에서 읽은 한국어 문구뿐이다. 원장 문장이 PDF의 한 문단 안에
다른 문장과 이어져 인쇄돼도(예: 보증 문장 + '제품 내부와 외부에…') 그 문장이
들어 있으면 발견으로 본다. 글자가 □로 남아 확정할 수 없으면 '확인 필요'로 둔다.
"""
import re

from phrase_matcher import compact, strip_marks

ACCEPTED = {"EXACT_MATCH", "NORMALIZED_MATCH", "VARIABLE_MATCH"}

# Sheet1(아트웍 AI 자동화 프로세스): 품질 보증 / 사용법 · 사용방법 QR 은 '슬리브만 해당'.
SLEEVE_ONLY = {"사용방법 QR", "품질 보증 / 사용법"}

CHECKS = [
    # rule_id, label, kind
    ("R6", "키 메세지", "EXACTLY_ONE"),
    ("R31", "G7 특장점", "AT_LEAST_ONE"),
    ("R54", "제품타입", "AT_LEAST_ONE"),
    ("R185", "사용가능 열원", "EXACTLY_ONE"),
    ("R188", "사용방법 QR", "EXACTLY_ONE"),
    ("R191", "품질 보증 문장 (2·5·10년 중 하나)", "EXACTLY_ONE"),
    ("R196", "품질 보증 필수 4문장", "ALL_REQUIRED"),
]


def _key(text):
    return compact(strip_marks(text)).rstrip(".。")


def _pattern(text):
    """Ledger sentence → regex over compact text (Y배 / 202X are variables)."""
    key = re.escape(_key(text))
    key = key.replace("y배", r"\d{1,2}배").replace("202x", r"20\d\d")
    return re.compile(key)


def check_file(matches, master):
    """matches: phrase-matcher results for ONE file (in reading order)."""
    phrases = {p["phrase_id"]: p for p in master.get("phrases", [])}
    variants = master.get("variants", [])
    rules = {r["rule_id"]: r for r in master.get("rules", [])}
    corpus = "".join(_key(m.get("extracted", "")) for m in matches)
    damaged = "□" in corpus or "\ufffd" in corpus
    unregistered = [m.get("extracted", "") for m in matches
                    if m.get("status") == "UNREGISTERED" and not m.get("region_ocr")]
    output = []
    for rule_id, label, kind in CHECKS:
        if rule_id not in rules:
            continue
        ids = [v["phrase_id"] for v in variants if v["rule_id"] == rule_id]
        # Same Korean registered under several ids (English variants) is
        # one sentence for the Korean check.
        by_korean = {}
        for pid in ids:
            korean = phrases.get(pid, {}).get("korean_original", "")
            if korean:
                by_korean.setdefault(_key(korean), []).append(pid)
        found, review = [], []
        for key, pids in by_korean.items():
            korean = phrases[pids[0]]["korean_original"]
            matched = [m for m in matches if m.get("phrase_id") in pids]
            if any(m.get("status") in ACCEPTED for m in matched) or _pattern(korean).search(corpus):
                found.append(korean.strip())
            elif matched:
                review.append(korean.strip())
        category = rules[rule_id].get("category", "")
        sleeve = " · 원장 프로세스 기준 슬리브 제품만 해당" if category in SLEEVE_ONLY else ""
        if kind == "ALL_REQUIRED":
            missing = [phrases[p[0]]["korean_original"].strip() for k, p in by_korean.items()
                       if phrases[p[0]]["korean_original"].strip() not in found]
            if not missing:
                status, message = "OK", f"✓ {label} — {len(found)}개 모두 발견"
            elif len(missing) == len(by_korean):
                status, message = "MISSING", f"✗ {label} — 발견 실패 (0/{len(by_korean)}){sleeve}"
            else:
                status = "REVIEW" if damaged or review else "MISSING"
                message = (f"✗ {label} — {len(by_korean) - len(missing)}/{len(by_korean)}개 발견 · 누락: "
                           + " / ".join(f"'{m}'" for m in missing))
        else:
            count = len(found)
            if count == 0 and review:
                status, message = "REVIEW", f"□ {label} — 유사 문구만 발견 · 원장 문장과 차이 확인 필요: '{review[0]}'"
            elif count == 0:
                status, message = "MISSING", f"✗ {label} — 발견 실패{sleeve}"
            elif kind == "EXACTLY_ONE" and count > 1:
                status = "FAIL"
                message = f"✗ {label} — {count}개 발견 · 하나만 있어야 함 (오류): " + " / ".join(
                    f"'{f}'" for f in found)
            else:
                status = "OK"
                shown = found[0] if count == 1 else f"{count}개"
                message = f"✓ {label} — 발견: '{shown}'" if count == 1 else f"✓ {label} — {shown} 발견"
        if status == "MISSING" and unregistered and rule_id == "R6":
            message += (" · 원장에 없는 국문 문구가 있음 (표의 '미분류' 행: "
                        + " / ".join(f"'{u}'" for u in unregistered[:2])
                        + ") — 키 메세지 원장 등록 누락일 수 있음")
        output.append({"rule_id": rule_id, "label": label, "category": category,
                       "status": status, "found": found, "message": message})
    return output
