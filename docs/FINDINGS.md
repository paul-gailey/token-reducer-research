# Token-Reduction Rig — Findings

*A transparent OpenAI-compatible proxy that sits between a coding agent and the model,
applies one swappable context-shrinking transform per request, and meters tokens in/out.
Goal: quantify how much input context can be removed, and whether removing it changes the
model's behavior.*

---

# Run #1 — first real benchmark run (hosted)

*2026-05-29. SWE-bench Lite, 1 instance (`sqlfluff__sqlfluff-1625`), hosted model
`gpt-5.4-mini-2026-03-17`, `identity` transform (baseline). This is a **smoke test**:
its job is to prove the pipeline runs end-to-end on a real benchmark, NOT to produce a
result. Evidence comes when we A/B a transform across a slice (next).*

## What this run establishes
- **The rig works on a real workload.** A real coding agent (`mini-swe-agent`) worked a
  real GitHub issue inside the benchmark's Docker container, with every model call
  transparently routed through our proxy.
- **End-to-end path confirmed:** agent → proxy (:8787, `identity`) → OpenAI → back,
  per-call metering in `rig_calls.jsonl`, real patch in `runs/smoke/preds.json`.

## Numbers (this run)
- **13 model calls**, all logged through the proxy.
- **74,682 input tokens / 1,870 output tokens → 39.9 : 1 input:output.**
- Per-call input **grew 1,282 → 7,684 tokens** as the agent read files and accumulated
  history — you can watch the context balloon, call by call.
- Output per call stays small (3–436 tokens).
- Agent produced an **844-char patch** (adds a `has_join_clause` guard to sqlfluff's
  L031 rule). Patch applied cleanly and the hidden tests ran.

## Correctness (scored 2026-05-29, local `swebench` 4.1.0 harness)
**Result: NOT resolved (0/1).** The patch applied cleanly and tests executed — a genuine
wrong-fix, not a pipeline failure. Breakdown:
- **`FAIL_TO_PASS`** (the bug's target test, must go fail→pass):
  `test__cli__command_directed` → **still failing**. The fix was insufficient.
- **`PASS_TO_PASS`** (regression guard, ~65 tests must stay passing): 64 passed, but
  **`test__cli__command_fix_stdin[SELECT]` broke** → the guard was also too aggressive.
- So it failed on both axes: didn't fix the bug *and* introduced a regression.

This validates the full pipeline end-to-end (generate → apply → run hidden tests → grade)
and is a clean honest negative: `gpt-5.4-mini` attempted a plausible but wrong fix.

> **Design note for the A/B:** this instance resolves at 0 for the baseline, so it can't
> show a *drop* in resolve-rate under a transform. The A/B slice needs instances the
> baseline actually resolves — run a larger slice (5–10) so some pass, then report token
> savings (measurable regardless) with resolve-rate as the "did we break anything" guard.

## Why this matters (the thesis)
On a real coding-agent workload against a hosted model, the run is overwhelmingly
**input-dominated (~40:1)**, and the input *grows* with every turn as history piles up.
**The tokens — and therefore the cost and the latency — live in the input context.
That is the lever.** This is exactly what the transforms (`dedup`/`prune`) attack, and
why prompt caching is the obvious complement. The whole point of the rig is to measure
how hard that lever can be pulled before the model's behavior changes.

## What this run does NOT show (stated plainly)
- **n = 1.** One instance. No statistical claim.
- **Baseline only.** `identity` = no transform, so no savings or divergence measured
  here. It is the control we will A/B against.
- **Correctness unverified.** The patch exists; we have not run the benchmark's tests to
  see if it actually *resolves* the issue.

## Hard-won setup notes (where the real time went)
- SWE-bench images are **x86; this is an arm64 Mac** → emulation. The image is ~3.6 GB
  and `mini-swe-agent` gives the container only **120 s to start**. First attempt timed
  out mid-pull → container never started → **empty patch**. **Fix: pre-`docker pull` the
  image once** (no timeout); subsequent runs start in seconds.
- The runner **skips any instance already in the output dir's `preds.json`** — even a
  failed one with an empty patch. Clear/rename the output dir before re-running or it
  silently reports "Running on 0 instances".
- Token usage is logged as `input_tokens`/`output_tokens` in `rig_calls.jsonl` (the
  proxy remaps OpenAI's `prompt_tokens`/`completion_tokens`); the upstream `model`
  string confirms which model actually served each call.

## Method (so the next runs are comparable)
- **Per-call metering, not per-session.** Each request is metered independently so we can
  attribute token/behavior effects to the transform on that call, not to the compounding
  butterfly effect of an agent loop.
- **`identity` is the control.** Run the baseline first; an A/B compares a test transform
  against `identity` on the *same* instances, so any difference is the transform's.
- **One transform at a time** — no composition — for clean causal attribution.

## Next steps (from here)
1. **Score this prediction** (`sb-cli` cloud) — does the patch resolve the issue?
2. **A/B a slice** (`--slice 0:5`): `identity` vs `prune`, same instances. Compare
   **resolved-rate** (correctness) against **total input tokens** (savings). Target
   claim: *"prune cuts input tokens by X% with ≤Y pp drop in resolved rate."*

## Reproduce
```bash
# terminal 1 — proxy (baseline)
set -a && . ./.env && set +a
RIG_TRANSFORM=identity PYTHONPATH=src .venv/bin/uvicorn rig.proxy:app --port 8787

# one-time: pre-pull the image so container start doesn't hit the 120s timeout
docker pull docker.io/swebench/sweb.eval.x86_64.sqlfluff_1776_sqlfluff-1625:latest

# terminal 2 — one instance through the rig
set -a && . ./.env && set +a
export MSWEA_COST_TRACKING=ignore_errors
.venv/bin/mini-extra swebench -m openai/gpt-5.4-mini --subset lite --slice 0:1 -o runs/smoke
```
Raw data: `runs/smoke/preds.json` (patch), `rig_calls.jsonl` (live metering, this run).
