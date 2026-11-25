"""Render the Inkling race card from chained gauntlet receipts.

python3 board/race.py  ->  board/race.json + board/race.html
Reads receipts/gauntlet.jsonl (verifies chain first).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "harness"))
import receipts as rc  # type: ignore[import-not-found]  # noqa: E402

FILE = ROOT / "receipts" / "gauntlet.jsonl"
CSS = """
body{margin:0;background:#0b0e14;color:#e6e9ef;font-family:ui-sans-serif,system-ui}
.wrap{padding:26px 30px;max-width:1150px}
h1{font-size:24px;margin:0 0 2px}.sub{color:#8b95a7;font-size:12px;margin-bottom:16px}
table{border-collapse:collapse;width:100%}
th{color:#8b95a7;font-weight:500;font-size:11px;text-align:right;padding:6px 10px;border-bottom:1px solid #232b3d}
th:first-child{text-align:left}
td{padding:9px 10px;font-size:14px;text-align:right;border-bottom:1px solid #1a2233;font-variant-numeric:tabular-nums}
td:first-child{text-align:left;font-weight:600}
.win{color:#3ddc84;font-weight:700}
.bad{color:#ff6b6b}
.foot{color:#5b6577;font-size:11px;margin-top:14px}
"""

def main() -> int:
    n, broken = rc.verify(str(FILE))
    if broken:
        raise SystemExit(f"refusing to render: broken chain {broken}")
    rows = [json.loads(l) for l in FILE.read_text().splitlines() if l.strip()]
    arms = [r for r in rows if r.get("kind") == "siliconref-gauntlet-v1"]
    if not arms:
        raise SystemExit("no gauntlet receipts")
    suite = arms[0]["suite_sha256"][:16]

    def cell(arm, section, key=None, field="median_tps"):
        try:
            node = arm["checks"][section]
            return node[key][field] if key else node[field]
        except KeyError:
            return None

    cols = ["S1 prose", "S2 code", "S3 math", "L1 32K", "L2 128K", "c4 agg", "c8 agg", "needle"]
    table = []
    for arm in arms:
        row = {
            "arm": arm["arm"], "verdict": arm["verdict"],
            "S1 prose": cell(arm, "decode_c1", "S1"),
            "S2 code": cell(arm, "decode_c1", "S2"),
            "S3 math": cell(arm, "decode_c1", "S3"),
            "L1 32K": cell(arm, "L1_32k", None, "median_tps"),
            "L2 128K": cell(arm, "L2_128k", None, "median_tps"),
            "c4 agg": cell(arm, "agg_c4", None, "aggregate_tps"),
            "c8 agg": cell(arm, "agg_c8", None, "aggregate_tps"),
            "needle": all(arm["checks"].get(k, {}).get("needle_found", True)
                          for k in ("L1_32k", "L2_128k")),
        }
        table.append(row)
    (ROOT / "board" / "race.json").write_text(json.dumps(
        {"suite_sha256": suite, "rows": table}, indent=2))

    winners = {}
    for c in cols[:-1]:
        vals = [(r[c], r["arm"]) for r in table if isinstance(r[c], (int, float))]
        if vals:
            winners[c] = max(vals)[1]

    ths = "".join(f"<th>{c}</th>" for c in cols)
    trs = []
    for r in table:
        tds = [f"<td>{r['arm']} <span class={'bad' if r['verdict']!='PASS' else ''}>{'' if r['verdict']=='PASS' else 'FAIL'}</span></td>"]
        for c in cols:
            v = r[c]
            if c == "needle":
                tds.append(f"<td>{'✓' if v else '✗'}</td>")
            elif isinstance(v, (int, float)):
                cls = ' class="win"' if winners.get(c) == r["arm"] else ""
                tds.append(f"<td{cls}>{v:g}</td>")
            else:
                tds.append("<td>–</td>")
        trs.append("<tr>" + "".join(tds) + "</tr>")
    html = f"""<!doctype html><html><head><meta charset="utf-8"><style>{CSS}</style></head><body><div class="wrap">
<h1>Inkling 2 Mini on one DGX Spark — certified race card</h1>
<div class="sub">one box, one day, one pinned suite {suite}… · greedy byte-identity + 32K/128K needle · all receipts hash-chained · siliconref</div>
<table><tr><th>arm</th>{ths}</tr>{''.join(trs)}</table>
<div class="foot">tok/s: prose/code/math single-stream default sampling · L1/L2 decode at 32K/128K prompt (greedy) · c4/c8 aggregate. github.com/ar33s08/siliconref</div>
</div></body></html>"""
    (ROOT / "board" / "race.html").write_text(html)
    print(json.dumps(table, indent=2))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
