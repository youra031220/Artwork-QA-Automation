"""Bilingual artwork phrase review, using compact wrapped two-row cells.

The category and verdict belong to one bilingual QA item, while the actual
PDF text and the reference workbook text are shown independently by language.
All PDF/workbook strings are HTML escaped.
"""
from html import escape

COLUMNS = (
    ("문구 카테고리", 13),
    ("언어", 6),
    ("PDF 추출 문구", 29),
    ("원장 기준 문구", 26),
    ("문구 유형", 8),
    ("대조 결과", 9),
    ("확인할 사항", 9),
)


def _safe(value):
    return escape(str(value or "")).replace("\n", "<br>")


def reviewer_html_table(records):
    """One item is two rows (Korean/English) with true rowspan cells.

    '영문 미발견' is never replaced by a master/source phrase. Missing
    source English is not silently considered verified.
    """
    if not records:
        return ""
    style = """
<style>
.artwork-qa-wrap {width:100%;overflow-x:hidden;margin:.5rem 0 1rem;}
.artwork-qa-table {width:100%;table-layout:fixed;border-collapse:collapse;
  font-size:13px;line-height:1.55;color:inherit;}
.artwork-qa-table th,.artwork-qa-table td {border:1px solid rgba(128,128,128,.22);
  text-align:left;padding:9px 10px;vertical-align:top;
  white-space:normal!important;overflow-wrap:anywhere!important;
  word-break:break-word!important;text-overflow:clip!important;
  max-width:none;height:auto;}
.artwork-qa-table th {background:rgba(128,128,128,.10);font-weight:600;}
.artwork-qa-table .artwork-qa-en td {background:rgba(128,128,128,.045);}
.artwork-qa-table .artwork-qa-pair {border-top:2px solid rgba(128,128,128,.35);}
.artwork-qa-table .artwork-qa-unknown {opacity:.70;}
</style>"""
    cols="<colgroup>"+ "".join(
        f'<col style="width:{width}%">' for _,width in COLUMNS
    )+"</colgroup>"
    header="<thead><tr>"+"".join(
        f"<th>{_safe(name)}</th>" for name,_ in COLUMNS
    )+"</tr></thead>"
    body=[]
    for record in records:
        category=_safe(record.get("문구 카테고리","미분류"))
        k_extract=_safe(record.get("국문 추출 문구"))
        e_extract=record.get("영문 추출 문구")
        e_visible=_safe(e_extract) if e_extract else '<span class="artwork-qa-unknown">PDF 영문 미발견</span>'
        k_ref=_safe(record.get("기준 국문"))
        e_ref=_safe(record.get("기준 영문"))
        common=(
            f'<td rowspan="2" class="artwork-qa-pair">{category}</td>'
        )
        # Category, type, result and issue are one logical inspection unit.
        common_after=(
            f'<td rowspan="2">{_safe(record.get("문구 유형"))}</td>'
            f'<td rowspan="2">{_safe(record.get("대조 결과"))}</td>'
            f'<td rowspan="2">{_safe(record.get("확인할 사항"))}</td>'
        )
        body.append(
            '<tr class="artwork-qa-ko">'+common+
            '<td>국문</td><td>'+k_extract+'</td><td>'+k_ref+'</td>'+
            common_after+'</tr>'
        )
        body.append(
            '<tr class="artwork-qa-en"><td>영문</td><td>'+e_visible+
            '</td><td>'+e_ref+'</td></tr>'
        )
    return (style+'<div class="artwork-qa-wrap"><table class="artwork-qa-table">'
            +cols+header+'<tbody>'+"".join(body)+'</tbody></table></div>')
