"""siliconref gauntlet: certified multi-arm benchmark for the Inkling 2 Mini
Spark race (and any OpenAI-compatible arms generally).

Why this exists: every published tok/s number in this race is self-graded on
a private prompt set, and the NVIDIA forum thread proved the prompt set alone
moves single-stream decode by ~a third. So we run ONE pinned request set
against every recipe, on the same box, back to back, and emit chained
receipts per arm. Byte-identity is checked at greedy temp 0 across arms.

Suite (content-hashed, do not edit without bumping SUITE_VERSION):
  S1 prose 300t | S2 code 600t | S3 math 200t   (speed: 5 reps, default sampling)
  all greedy x3 for cross-arm byte-identity
  L1 32K-needle | L2 128K-needle (greedy, 2 reps, from gauntlet/longtext.txt)
  c4/c8 aggregate rounds of S1+S2 (1 round)

Usage:
  python3 gauntlet/gauntlet.py --arm knapcio-dflash2=http://127.0.0.1:8000,Inkling-2-Mini \
      --arm sxuff-vllm=http://127.0.0.1:8020,thinkingmachines/Inkling-2-Mini
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import hashlib
import json
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "harness"))
import receipts as rc  # noqa: E402
from probe import stream_one, bimodal_flag, env_attestation  # noqa: E402

SUITE_VERSION = "gauntlet-suite-v1"
LONGTEXT = ROOT / "gauntlet" / "longtext.txt"

S1 = ("Write a vivid 250-word description of a fishing harbor at dawn: "
      "the boats, the gulls, the smell of rope and diesel, one named character "
      "who notices the weather turning. Plain, confident prose.")
S2 = ("Write a Python module (no explanation, code only) implementing a thread-safe "
      "LRU cache with TTL expiry: get/set/delete/len, an internal time function "
      "injectable for tests, and a cleanup pass that runs under the lock.")
S3 = ("Show the multiplication steps and final result for these products: "
      "137*89, 421*347, and 1291*733. Finish with a line 'ANSWER: <a>, <b>, <c>'.")

def needle_prompt(corpus: str, target_chars: int, depth: float, secret: str) -> str:
    body = corpus[:target_chars]
    cut = int(len(body) * depth)
    marker = f"\n\nIMPORTANT NOTICE: the activation phrase is '{secret}'. Note it.\n\n"
    return body[:cut] + marker + body[cut:] + (
        "\n\nQuestion: what was the activation phrase in the notice above? "
        "Answer with just the phrase.")


def timed(arm_url: str, model: str, prompt: str, max_tokens: int, thinking: str) -> dict:
    return stream_one(arm_url, model, prompt, max_tokens, None, thinking)


def suite_sha() -> str:
    blob = json.dumps([SUITE_VERSION, S1, S2, S3], sort_keys=True)
    corpus = LONGTEXT.read_bytes()
    return hashlib.sha256((blob + corpus.hex()).encode()).hexdigest()


def run_arm(label: str, url: str, model: str, thinking: str, quick: bool) -> dict:
    speed_prompts = [("S1", S1, 300), ("S2", S2, 600), ("S3", S3, 200)]
    checks, failures = {}, []

    # 1. greedy byte-identity: same prompt, 3 runs, one output hash
    identity = {}
    for pid, p, mt in speed_prompts:
        hs = [timed(url, model, p, mt, "off")["text_sha256"] for _ in range(3)]
        identity[pid] = {"unique": len(set(hs)), "pass": len(set(hs)) == 1,
                         "sha": hs[0][:16]}
        if len(set(hs)) != 1:
            failures.append(f"identity:{pid}")
    checks["identity_greedy"] = identity

    # 2. decode speed at default sampling, c1, 5 reps each
    perf = {}
    for pid, p, mt in speed_prompts:
        samps = [timed(url, model, p, mt, thinking)["decode_tps"] for _ in range(5)]
        perf[pid] = {"median_tps": statistics.median(samps),
                     "min_tps": min(samps), "max_tps": max(samps),
                     "bimodal_flag": bimodal_flag(samps)}
        if perf[pid]["bimodal_flag"]:
            failures.append(f"decode:bimodal:{pid}")
    checks["decode_c1"] = perf

    # 3. long-context needle (32K / 128K chars ~ tokens) from pinned corpus
    if not quick:
        corpus = LONGTEXT.read_text(errors="replace")
        for lid, chars, secret in (("L1_32k", 130000, "VERMILION-OTTER-42"),
                                   ("L2_128k", 520000, "COPPER-KITE-7")):
            pr = needle_prompt(corpus, chars, 0.9, secret)
            runs = [timed(url, model, pr, 300, "off") for _ in range(2)]
            found = secret.lower() in runs[0]["text_preview"].lower()
            checks[lid] = {"needle_found": found,
                           "median_tps": statistics.median([r["decode_tps"] for r in runs]),
                           "ttft_median_s": statistics.median([r["ttft_s"] for r in runs])}
            if not found:
                failures.append(f"needle:{lid}")

    # 4. aggregate throughput c4 / c8 (S1+S2 mixed)
    for c in (4, 8):
        if quick and c == 8:
            continue
        jobs = [(S1 if i % 2 else S2, 300 if i % 2 else 600) for i in range(c)]
        with cf.ThreadPoolExecutor(max_workers=c) as ex:
            futs = [ex.submit(timed, url, model, p, mt, thinking) for p, mt in jobs]
            rows = [f.result() for f in futs]
        checks[f"agg_c{c}"] = {
            "aggregate_tps": round(sum(r["tokens"] for r in rows) /
                                   sum(r["tokens"] / max(r["decode_tps"], 0.1) for r in rows), 2),
            "per_stream_median_tps": statistics.median([r["decode_tps"] for r in rows])}

    return {"kind": "siliconref-gauntlet-v1", "suite_version": SUITE_VERSION,
            "suite_sha256": suite_sha(), "arm": label, "base_url": url,
            "model": model, "sampling": "default (thinking=%s)" % thinking,
            "runner": env_attestation(), "checks": checks, "failures": failures,
            "verdict": "PASS" if not failures else "FAIL",
            "run_ts": datetime.now(timezone.utc).isoformat()}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--arm", action="append", required=True,
                    help="label=base_url,model")
    ap.add_argument("--thinking", default="off")
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--out", default=str(ROOT / "receipts" / "gauntlet.jsonl"))
    args = ap.parse_args()
    all_rows = []
    for spec in args.arm:
        label, rest = spec.split("=", 1)
        url, model = rest.split(",", 1)
        print(f"### gauntlet arm {label} @ {url}", flush=True)
        row = run_arm(label, url, model, args.thinking, args.quick)
        seq, h = rc.append(args.out, row)
        print(json.dumps({"seq": seq, "arm": label, "verdict": row["verdict"],
                          "failures": row["failures"],
                          "decode": {k: v["median_tps"] for k, v in row["checks"].get("decode_c1", {}).items()}},
                         indent=2), flush=True)
        all_rows.append(row)
    # cross-arm greedy identity: same suite -> same hashes
    if len(all_rows) > 1:
        ref = all_rows[0]["checks"]["identity_greedy"]
        for other in all_rows[1:]:
            for pid in ref:
                same = ref[pid]["sha"] == other["checks"]["identity_greedy"][pid]["sha"]
                if not same:
                    print(f"IDENTITY DIVERGENCE: {other['arm']} {pid} vs {all_rows[0]['arm']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
