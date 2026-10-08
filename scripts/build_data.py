"""Dump the case workbook verbatim to api/data/workbook.json (no interpretation here).
Usage: python scripts/build_data.py path/to/workbook.xlsx"""
import sys, json, datetime, openpyxl
src = sys.argv[1]
wb = openpyxl.load_workbook(src, data_only=True)
def rows(ws):
    it = ws.iter_rows(values_only=True); head = [str(h).strip() for h in next(it)]
    out = []
    for r in it:
        if all(v is None for v in r): continue
        out.append({h: (v.isoformat()[:10] if isinstance(v, (datetime.date, datetime.datetime)) else v) for h, v in zip(head, r)})
    return out
out = {ws.title: rows(ws) for ws in wb}
json.dump(out, open("api/data/workbook.json", "w"), indent=1, ensure_ascii=False)
print({k: len(v) for k, v in out.items()})
