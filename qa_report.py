"""P1 JSON/CSV export without altering the existing P0 archive."""
import csv
import io
import json
import zipfile


def _csv(rows):
    output=io.StringIO(newline="")
    keys=list(dict.fromkeys(k for row in rows for k in row))
    if keys:
        writer=csv.DictWriter(output,fieldnames=keys)
        writer.writeheader()
        for row in rows:
            writer.writerow({key:json.dumps(value,ensure_ascii=False)
                             if isinstance(value,(list,dict)) else value
                             for key,value in row.items()})
    return "\ufeff"+output.getvalue()


def export_p1(matches,rules,summary):
    unregistered=[m for m in matches if m["status"]=="UNREGISTERED"]
    buffer=io.BytesIO()
    with zipfile.ZipFile(buffer,"w",zipfile.ZIP_DEFLATED) as z:
        for name,rows in (("phrase_matches",matches),("rule_results",rules),
                          ("unregistered",unregistered)):
            z.writestr("p1_"+name+".json",json.dumps(rows,ensure_ascii=False,indent=2))
            z.writestr("p1_"+name+".csv",_csv(rows))
        z.writestr("p1_qa_summary.json",json.dumps(summary,ensure_ascii=False,indent=2))
    return buffer.getvalue()
