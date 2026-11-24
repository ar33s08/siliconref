"""siliconref probe runner: runs one matrix cell, emits a chained receipt.

Checks (stack-level, not model-quality):
  determinism  same prompt @ temp 0, N runs -> identical sha256(text)?
  decode       per-sample tok/s; bimodality coefficient flags flaky stacks
  smoke        expected substring / line count catches silent breakage
  ttft         time-to-first-token distribution
  env          GPU/backend/driver attestation collected on the runner box

stdlib only. Bimodality = SAS coefficient b = (skew^2 + 1) / (kurt + 3);
b > 0.555 flagged. The detector is self-tested before any real number is
trusted (see scripts/selftest.py — a rubric that cannot pass is worthless).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import socket
import statistics
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import receipts as rc  # noqa: E402

ROOT = HERE.parent


def stream_one(base_url: str, model: str, prompt: str, max_tokens: int,
               api_key: str | None, thinking: str) -> dict:
    body = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "temperature": 0,
        "stream": True,
        "stream_options": {"include_usage": True},
    }
    if thinking == "off":
        body["chat_template_kwargs"] = {"enable_thinking": False}
    data = json.dumps(body).encode()
    req = urllib.request.Request(base_url.rstrip("/") + "/v1/chat/completions",
                                 data=data,
                                 headers={"Content-Type": "application/json"},
                                 method="POST")
    if api_key:
        req.add_header("Authorization", "Bearer " + api_key)
    t0 = time.monotonic()
    first = last = None
    text_parts: list[str] = []
    n_chunks = 0
    usage_tokens = None
    with urllib.request.urlopen(req, timeout=240) as resp:
        for raw in resp:
            line = raw.decode("utf-8", "replace").strip()
            if not line.startswith("data:"):
                continue
            payload = line[5:].strip()
            if payload == "[DONE]":
                break
            try:
                chunk = json.loads(payload)
            except json.JSONDecodeError:
                continue
            usage = chunk.get("usage")
            if usage and usage.get("completion_tokens") is not None:
                usage_tokens = usage["completion_tokens"]
            for choice in chunk.get("choices", []):
                delta = choice.get("delta") or {}
                piece = (delta.get("content") or delta.get("reasoning")
                         or delta.get("reasoning_content") or "")
                if piece:
                    now = time.monotonic()
                    if first is None:
                        first = now
                    last = now
                    n_chunks += 1
                    text_parts.append(piece)
    if first is None:
        raise RuntimeError("no content chunks streamed")
    tokens = usage_tokens if usage_tokens else n_chunks
    dur = max(last - first, 1e-9)
    text = "".join(text_parts)
    return {
        "text_sha256": hashlib.sha256(text.encode()).hexdigest(),
        "text_preview": text[:200],
        "decode_tps": round((tokens - 1) / dur, 2),
        "ttft_s": round(first - t0, 4),
        "tokens": tokens,
    }


def bimodality_coef(vals: list[float]) -> float | None:
    if len(vals) < 6:
        return None
    m = statistics.mean(vals)
    sd = statistics.pstdev(vals)
    if sd == 0:
        return 0.0
    skew = statistics.mean([(v - m) ** 3 for v in vals]) / sd ** 3
    kurt_raw = statistics.mean([(v - m) ** 4 for v in vals]) / sd ** 4
    # SAS BC uses EXCESS kurtosis: b = (skew^2 + 1) / (excess + 3) == (skew^2 + 1) / kurt_raw
    # (normal distribution -> b = 1/3; two tight clusters -> b -> 1.0)
    b = (skew ** 2 + 1) / kurt_raw
    return round(b, 4)


def bimodal_flag(samples_list: list[float]) -> bool:
    """Bimodal requires mass on BOTH sides, not just an outlier: SAS BC alone
    fires on tight clusters (small-n) and on single stalls. Require the
    coefficient AND >=3 samples under 0.7*med AND >=3 over 1.3*med."""
    if len(samples_list) < 20:
        return False
    med = statistics.median(samples_list)
    if med == 0:
        return False
    b = bimodality_coef(samples_list)
    if b is None or b <= 0.555:
        return False
    low = sum(1 for v in samples_list if v < 0.7 * med)
    high = sum(1 for v in samples_list if v > 1.3 * med)
    return low >= 3 and high >= 3


def stall_flag(samples_list: list[float]) -> bool:
    """Any single sample below half the median = a stall event (a co-tenant
    hiccup is a real data point, but it is NOT a bimodal stack)."""
    if len(samples_list) < 20:
        return False
    med = statistics.median(samples_list)
    return med > 0 and any(v < 0.5 * med for v in samples_list)


def env_attestation() -> dict:
    att = {
        "platform": platform.platform(),
        "machine": platform.machine(),
        "hostname": socket.gethostname(),
        "python": platform.python_version(),
    }
    for name, cmd in (("rocm", ["rocm-smi", "--showproductname"]),
                      ("nvidia", ["nvidia-smi", "--query-gpu=name,driver_name,driver_version",
                                  "--format=csv,noheader"]),
                      ("metal", ["system_profiler", "SPHardwareDataType"])):
        try:
            out = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
            if out.returncode == 0 and out.stdout.strip():
                att[name] = out.stdout.strip()[:1500]
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass
    return att


def run_cell(cell: dict, matrix: dict, samples: int) -> dict:
    probes = matrix["probes"]
    base, model = cell["base_url"], cell["model"]
    key, thinking = cell.get("api_key"), cell.get("thinking", "endpoint")
    checks: dict = {}
    failures: list[str] = []

    # 1. determinism: every probe repeated 3x, identical output hashes
    det: dict = {}
    for p in probes:
        hashes = []
        for _ in range(3):
            r = stream_one(base, model, p["prompt"], p["max_tokens"], key, thinking)
            hashes.append(r["text_sha256"])
        det[p["id"]] = {"unique_hashes": len(set(hashes)), "pass": len(set(hashes)) == 1}
        if len(set(hashes)) != 1:
            failures.append(f"determinism:{p['id']}")
    checks["determinism"] = det

    # 2. smoke: content expectations catch silent breakage/garbage
    smoke: dict = {}
    for p in probes:
        r = stream_one(base, model, p["prompt"], p["max_tokens"], key, thinking)
        ok, why = True, ""
        if p.get("expect_digit_only"):
            stripped = r["text_preview"].strip().split("\n")[0].strip()
            if not stripped.isdigit():
                ok, why = False, "first line not digits-only"
        if p.get("expect_contains") and p["expect_contains"] not in r["text_preview"]:
            ok, why = False, "missing substring " + p["expect_contains"]
        if p.get("expect_lines"):
            lines = [l for l in r["text_preview"].splitlines() if l.strip()]
            if len(lines) != p["expect_lines"]:
                ok, why = False, f"got {len(lines)} lines"
        if r["tokens"] <= 1:
            ok, why = False, "empty completion"
        smoke[p["id"]] = {"pass": ok, "why": why, "text_sha256": r["text_sha256"],
                          "text_preview": r["text_preview"]}
        if not ok:
            failures.append(f"smoke:{p['id']}")
    checks["smoke"] = smoke

    # 3. decode perf + bimodality on the longest probe
    perf_probe = max(probes, key=lambda p: p["max_tokens"])
    samples_list, ttfts = [], []
    for _ in range(samples):
        r = stream_one(base, model, perf_probe["prompt"], perf_probe["max_tokens"],
                       key, thinking)
        samples_list.append(r["decode_tps"])
        ttfts.append(r["ttft_s"])
    b = bimodality_coef(samples_list)
    med = statistics.median(samples_list)
    spread = (max(samples_list) - min(samples_list)) / med if med else 0.0
    bimodal = bimodal_flag(samples_list)
    stalled = stall_flag(samples_list)
    checks["decode"] = {
        "n": len(samples_list),
        "median_tps": med,
        "min_tps": min(samples_list), "max_tps": max(samples_list),
        "relative_spread": round(spread, 3),
        "bimodality_coef": b, "bimodal_flag": bimodal,
        "stall_flag": stalled,
        "ttft_median_s": statistics.median(ttfts),
        "raw_samples": samples_list,
    }
    if bimodal:
        failures.append("decode:bimodal")
    if stalled:
        failures.append("decode:stall")

    matrix_bytes = (HERE / "matrix.json").read_bytes()
    return {
        "kind": "siliconref-receipt-v0.1",
        "cell_id": cell["id"], "gpu": cell["gpu"], "vendor": cell["vendor"],
        "backend": cell["backend"], "backend_version": cell["backend_version"],
        "model": model, "precision": cell["precision"],
        "reproduce": cell["reproduce"],
        "matrix_sha256": hashlib.sha256(matrix_bytes).hexdigest(),
        "runner": env_attestation(),
        "checks": checks, "failures": failures,
        "verdict": "PASS" if not failures else "FAIL",
        "run_ts": datetime.now(timezone.utc).isoformat(),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cell", required=True)
    ap.add_argument("--samples", type=int, default=24)
    ap.add_argument("--out", default=str(ROOT / "receipts" / "receipts.jsonl"))
    args = ap.parse_args()
    matrix = json.loads((HERE / "matrix.json").read_text())
    cells = [c for c in matrix["cells"] if c["id"] == args.cell]
    if not cells:
        print(f"no such cell: {args.cell}", file=sys.stderr)
        return 2
    try:
        rec = run_cell(cells[0], matrix, args.samples)
    except Exception as exc:  # a crashed cell IS a data point
        rec = {"kind": "siliconref-receipt-v0.1", "cell_id": args.cell,
               "verdict": "ERROR", "failures": [f"runner:{type(exc).__name__}: {exc}"],
               "matrix_sha256": hashlib.sha256((HERE / 'matrix.json').read_bytes()).hexdigest()}
    seq, h = rc.append(args.out, rec)
    print(json.dumps({"seq": seq, "row_hash": h, "verdict": rec["verdict"],
                      "failures": rec.get("failures", [])}, indent=2))
    return 0 if rec["verdict"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
