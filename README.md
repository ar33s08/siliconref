# siliconref

Independent referee for LLM inference stacks. AMD says its CI is 93% green.
NVIDIA says buy CUDA. Reddit says whatever it felt like that day. **Nobody
grades them — so we do.**

One command runs a hash-pinned probe matrix against any OpenAI-compatible
endpoint and emits a tamper-evident receipt:

```
python3 harness/probe.py --cell cell-001 --samples 12
```

Per stack we score: greedy **determinism** (temp-0 output hash identity),
**decode stability** (SAS bimodality coefficient catches "sometimes 20,
sometimes 40 tok/s"), **smoke** failures (silent breakage, empty or garbage
completions), and **TTFT**. Receipts are append-only hash-chained: edit one
and every later link breaks (`scripts/selftest.py` proves the detector
both passes clean data and catches tampering — and both a synthetic bimodal
stack and a unimodal one).

- Method & honest caveats: [METHOD.md](METHOD.md)
- Scoreboard: `board/leaderboard.html` (regenerate: `python3 board/aggregate.py`)
- Same referee discipline as [crossfire](https://github.com/ar33s08/crossfire),
  same streaming-bench lineage as decodeproof.

MIT licensed. Contributions = new cells + PR'd receipts, not opinions.
