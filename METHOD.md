# siliconref method

Independent scorecards for LLM inference stacks. We measure stacks other
people built and grade themselves — same neutrality rules as
[crossfire](https://github.com/ar33s08/crossfire).

## What we test (stack-level, not model quality)
1. **Determinism** — same prompt, temperature 0, 3 runs → identical
   output hashes. A nondeterministic greedy stack is a broken stack.
2. **Decode stability** — N repeated samples of tok/s; the SAS bimodality
   coefficient (b > 0.555 = flagged) catches the "sometimes 20, sometimes
   40 tok/s" behavior documented anecdotally on consumer AMD cards.
3. **Smoke** — expected substrings/line counts catch silent breakage and
   garbage completions, not style.
4. **TTFT** — median time-to-first-token.

## What we do NOT claim (yet)
- **Not a vendor bake-off.** Seed receipts are one NVIDIA (DGX Spark) and
  one Apple (M3 Pro) machine. An AMD receipt lands when a runner (or a
  $3 cloud MI300X hour) provides one.
- **Shared-machine caveat.** The Spark is a production box that runs other
  inference jobs around the clock. Its seed receipt shows median 33.5
  tok/s with a single 8.9 tok/s stall sample (co-tenant contention) — we
  label that `decode:stall`, NOT `decode:bimodal`, because one hiccup is
  not a bimodal stack. A second detector (mass on both sides of the median)
  guards against calling a tight cluster bimodal. Both detectors are
  regression-tested against today's real false positives.
- **Self-attested receipts.** v0.1 receipts are hash-chained (post-hoc
  tampering breaks every later link) but NOT cryptographically bound to
  an identity. Neutrality rests on exact reproducing commands, not trust.
  Runner-registered signing keys are v0.2.
- **One sample per cell is an anecdote, not a distribution.** Publish
  verdicts as "measured on", never as "X is worse than Y" until N runners
  contribute.

## Invariants
1. Probe matrix is content-hashed; receipts pin the hash. Numbers from
   different matrices never mix.
2. Detectors are self-tested both directions (can pass, can fail) before
   any published number — `scripts/selftest.py` runs in CI.
3. Every published number carries the exact command to reproduce it.
4. The referee never runs the servers it scores; runners do, from the
   pinned `reproduce` string.

## How to contribute a receipt
Start your server with a pinned command, then:
`python3 harness/probe.py --cell <id> --samples 12`
Open a PR adding your line to `receipts/receipts.jsonl` (regenerate via
the harness; hand-edited receipts break the chain and fail CI).
