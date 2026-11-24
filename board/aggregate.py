"""Aggregate siliconref receipts into a certificate + shareable leaderboard.

Reads receipts.jsonl, VERIFYs the hash chain first (refuse to publish a
broken chain), then builds one row per (cell, run) with verdicts, decode
distributions and reproducing commands. Emits:
  board/certificate.json   — matrix sha, chain head, per-receipt verdicts
  board/leaderboard.html   — dark card, tweet-screenshot ready
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "harness"))
import receipts as rc  # noqa: E402

RECEIPTS = ROOT / "receipts" / "receipts.jsonl"
MATRIX = ROOT / "harness" / "matrix.json"


def build() -> dict:
    n, broken = rc.verify(str(RECEIPTS))
    if broken:
        raise SystemExit(f"refusing to publish: broken chain links {broken}")
    rows = rc.rows(str(RECEIPTS)) if hasattr(rc, "rows") else [
        json.loads(l) for l in RECEIPTS.read_text().splitlines() if l.strip()]
    matrix_sha = hashlib.sha256(MATRIX.read_bytes()).hexdigest()
    cells = {}
    for rec in rows:
        if rec.get("kind") != "siliconref-receipt-v0.1" or "checks" not in rec:
            continue
        d = rec["checks"]["decode"]
        cells[rec["cell_id"]] = {
            "gpu": rec["gpu"], "vendor": rec["vendor"], "backend": rec["backend"],
            "backend_version": rec["backend_version"], "model": rec["model"],
            "precision": rec["precision"], "verdict": rec["verdict"],
            "failures": rec["failures"],
            "median_tps": d["median_tps"], "min_tps": d["min_tps"],
            "max_tps": d["max_tps"], "bimodality_coef": d["bimodality_coef"],
            "bimodal_flag": d["bimodal_flag"], "ttft_median_s": d["ttft_median_s"],
            "n_samples": d["n"], "reproduce": rec["reproduce"],
            "run_ts": rec["run_ts"], "row_hash": rec["_chain"]["row_hash"],
        }
    cert = {
        "kind": "siliconref-certificate-v0.1",
        "matrix_sha256": matrix_sha,
        "n_receipts": n,
        "chain_head": rows[-1]["_chain"]["row_hash"] if rows else None,
        "cells": cells,
    }
    (HERE / "certificate.json").write_text(json.dumps(cert, indent=2))
    render_html(cert)
    return cert


CSS = """
body{margin:0;background:#0b0e14;color:#e6e9ef;font-family:ui-sans-serif,system-ui}
.wrap{padding:28px 32px;max-width:1100px}
h1{font-size:26px;margin:0 0 4px}.sub{color:#8b95a7;font-size:13px;margin-bottom:20px}
.card{background:#121724;border:1px solid #232b3d;border-radius:12px;padding:16px 18px;margin-bottom:14px}
.head{display:flex;justify-content:space-between;align-items:baseline}
.gpu{font-size:18px;font-weight:600}.verdict{font-size:15px;font-weight:700;padding:2px 10px;border-radius:6px}
.PASS{background:#0f3;color:#062;font-size:13px}.FAIL,.ERROR{background:#f33;color:#fff}
.PASS{color:#3ddc84;background:#0d2b1c}.FAIL{color:#ff6b6b;background:#2b0d0d}.ERROR{color:#ffb86b;background:#2b1a0d}
.meta{color:#8b95a7;font-size:12px;margin-top:2px}
.stats{display:flex;gap:26px;margin-top:12px;font-size:13px}
.stats b{display:block;font-size:19px;color:#fff}
.flag{color:#ffb86b;font-weight:600}.ok{color:#3ddc84}
code{background:#1a2233;padding:1px 6px;border-radius:4px;font-size:11px;color:#9ecbff}
.foot{color:#5b6577;font-size:11px;margin-top:18px}
"""

def render_html(cert: dict) -> None:
    rows_html = []
    for cid, c in sorted(cert["cells"].items()):
        flag = ('<span class="flag">BIMODAL ⚠</span>' if c["bimodal_flag"]
                else '<span class="ok">stable</span>')
        rows_html.append(f"""
<div class="card">
  <div class="head"><div class="gpu">{c['gpu']}</div>
  <div class="verdict {c['verdict']}">{c['verdict']}</div></div>
  <div class="meta">{c['backend']} · {c['model']} · {c['precision']}</div>
  <div class="stats">
    <div><b>{c['median_tps']}</b>med tok/s</div>
    <div><b>{c['min_tps']}–{c['max_tps']}</b>range</div>
    <div><b>{c['ttft_median_s']}s</b>median TTFT</div>
    <div><b>{c['bimodality_coef']}</b>bimodality {flag}</div>
    <div><b>{c['n_samples']}</b>samples</div>
  </div>
  <div class="meta">reproduce: <code>{c['reproduce']}</code></div>
</div>""")
    html = f"""<!doctype html><html><head><meta charset="utf-8"><style>{CSS}</style></head>
<body><div class="wrap">
<h1>siliconref — independent LLM-stack scorecards</h1>
<div class="sub">hash-pinned probe matrix {cert['matrix_sha256'][:16]}… · {cert['n_receipts']} chained receipts · chain head {str(cert['chain_head'])[:16]}…</div>
{''.join(rows_html)}
<div class="foot">Every number reproducible: exact commands above. Chain: edit any receipt and every later link breaks. github.com/ar33s08/siliconref</div>
</div></body></html>"""
    (HERE / "leaderboard.html").write_text(html)


if __name__ == "__main__":
    cert = build()
    print(json.dumps({cid: c["verdict"] for cid, c in cert["cells"].items()}, indent=2))
