"""Append-only hash-chained receipt log for siliconref runs (JSONL).

row_hash = sha256(prev_hash + canonical_json(payload)). Editing or deleting
any receipt breaks every later link. v0.1 receipts are SELF-ATTESTED:
the chain proves nobody (including us) altered a receipt after the fact;
neutrality comes from every cell listing exact reproducing commands anyone
can re-run. Runner-registered signing keys are roadmap v0.2, not fake now.
"""

from __future__ import annotations

import hashlib
import json
import os
import time


def canonical(payload: dict) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False)


def row_hash(prev_hash: str, payload: dict) -> str:
    return hashlib.sha256((prev_hash + canonical(payload)).encode("utf-8")).hexdigest()


GENESIS = "0" * 64


def append(path: str, payload: dict) -> tuple[int, str]:
    prev_hash = GENESIS
    count = 0
    if os.path.exists(path):
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                if line.strip():
                    prev_hash = json.loads(line)["_chain"]["row_hash"]
                    count += 1
    blob = canonical(payload)
    h = row_hash(prev_hash, json.loads(blob))
    rec = json.loads(blob)
    rec["_chain"] = {"seq": count + 1, "prev_hash": prev_hash, "row_hash": h,
                     "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return count + 1, h


def verify(path: str) -> tuple[int, list[int]]:
    """Return (n_rows, list of broken seqs)."""
    expected_prev = GENESIS
    n = 0
    broken = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            if not line.strip():
                continue
            rec = json.loads(line)
            chain = rec.pop("_chain")
            recomputed = row_hash(expected_prev, json.loads(canonical(rec)))
            if chain["prev_hash"] != expected_prev or chain["row_hash"] != recomputed:
                broken.append(chain["seq"])
            expected_prev = recomputed
            n += 1
    return n, broken
