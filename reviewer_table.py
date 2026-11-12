"""Compact, full-text reviewer table with stable column widths.

Streamlit's interactive dataframe truncates long cells to one line. This
read-only HTML table wraps each cell fully without widening other columns.
All user/PDF-supplied content is HTML-escaped.
"""
from html import escape

COLUMNS = (
    ("추출 문구", 31),
    ("문구 카테고리", 12),
    ("문구 유형", 9),
    ("대조 결과", 13),
    ("기준 국문", 24),
    ("확인할 사항", 11),
)


def reviewer_html_table(records):
    """Render every character of every visible cell, with no ellipsis/scroll."""
    if not records:
        return ""
    style = """
<style>
.artwork-qa-wrap {width:100%; overflow-x:hidden; margin: .5rem 0 1rem;}
.artwork-qa-table {width:100%; table-layout:fixed; border-collapse:collapse;
  font-size:13px; line-height:1.55; color:inherit;}
.artwork-qa-table th, .artwork-qa-table td {border:1px solid rgba(128,128,128,.22);
  text-align:left; padding:9px 10px; vertical-align:top;
  white-space:normal !important; overflow-wrap:anywhere !important;
  word-break:break-word !important; text-overflow:clip !important;
  max-width:none; height:auto;}
.artwork-qa-table th {background:rgba(128,128,128,.10); font-weight:600;}
.artwork-qa-table tr:nth-child(even) td {background:rgba(128,128,128,.035);}
</style>"""
    cols = "<colgroup>" + "".join(
        f'<col style="width:{width}%">' for _, width in COLUMNS
    ) + "</colgroup>"
    headings = "<thead><tr>" + "".join(
        f"<th>{escape(title)}</th>" for title, _ in COLUMNS
    ) + "</tr></thead>"
    body = []
    for record in records:
        cells = "".join(
            "<td>" + escape(str(record.get(title) or "")).replace("\n", "<br>") + "</td>"
            for title, _ in COLUMNS
        )
        body.append(f"<tr>{cells}</tr>")
    return (style + '<div class="artwork-qa-wrap"><table class="artwork-qa-table">'
            + cols + headings + "<tbody>" + "".join(body)
            + "</tbody></table></div>")
