"""Prove the siliconref detectors can pass AND can fail — before trusting
any real number (crossfire invariant: prove the rubric can be passed).

Self-test contract:
  bimodality_coef(uniform)      -> flagged == False
  bimodality_coef(synthetic 2-cluster) -> flagged == True
  receipts chain verify         -> 0 broken after 3 appends
  receipts chain tamper         -> detects an edited line
"""
import json
import random
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "harness"))
import receipts as rc  # noqa: E402
from probe import bimodality_coef, bimodal_flag, stall_flag  # noqa: E402

random.seed(7)
fails = []

# 1. clean unimodal samples must NOT be flagged
uniform = [24.0 + random.gauss(0, 0.4) for _ in range(60)]
b1 = bimodality_coef(uniform)
if b1 is None or b1 > 0.555:
    fails.append(f"unimodal b={b1} should be <=0.555")

# 2. synthetic bimodal (two tight clusters, n>=20) MUST be flagged
bi = [20.0 + random.gauss(0, 0.3) for _ in range(30)] + \
     [40.0 + random.gauss(0, 0.3) for _ in range(30)]
b2 = bimodality_coef(bi)
if b2 is None or b2 <= 0.555:
    fails.append(f"bimodal b={b2} should be >0.555")
if not bimodal_flag(bi):
    fails.append("bimodal_flag missed synthetic bimodal")

# 2b. REGRESSION: today's real false positive — 12 tight samples, b>0.555
tight12 = [35.45, 35.53, 36.16, 36.28, 36.4, 36.58, 36.88, 37.18,
           37.41, 37.52, 37.78, 37.8]
if bimodal_flag(tight12):
    fails.append("bimodal_flag fired on tight unimodal cluster (false positive)")

# 2c. single stall outlier = stall True, bimodal False (today's Spark data)
stall_case = [11.48] + [28.0 + random.gauss(0, 2.2) for _ in range(23)]
if not stall_flag(stall_case):
    fails.append("stall_flag missed single-outlier stall")
if bimodal_flag(stall_case):
    fails.append("bimodal_flag fired on single outlier (should be stall only)")

# 3. receipt chain integrity + tamper detection
with tempfile.TemporaryDirectory() as td:
    p = str(Path(td) / "r.jsonl")
    for i in range(3):
        rc.append(p, {"n": i, "x": "hello é中"})
    n, broken = rc.verify(p)
    if n != 3 or broken:
        fails.append(f"clean chain n={n} broken={broken}")
    lines = Path(p).read_text().splitlines()
    obj = json.loads(lines[1])
    obj["n"] = 99
    lines[1] = json.dumps(obj)
    Path(p).write_text("\n".join(lines) + "\n")
    n, broken = rc.verify(p)
    # editing row 2 must break row 2 AND every later link (chain semantics)
    if broken != [2, 3]:
        fails.append(f"tamper not detected: broken={broken}")

if fails:
    print("SELFTEST FAIL:")
    [print(" -", f) for f in fails]
    raise SystemExit(1)
print(f"SELFTEST PASS  unimodal_b={b1}  bimodal_b={b2}  chain=ok  tamper=caught")
