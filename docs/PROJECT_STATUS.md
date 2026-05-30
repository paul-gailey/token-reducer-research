# Project Status — Token-Reduction Rig (resume-here doc)

*Last updated: 2026-05-29. Purpose: pick the project back up without re-deriving context.*
*Companion docs: `../README.md` (rig design), `FINDINGS.md` (results writeup).*

## TL;DR — where we are
The rig works end-to-end on a **real benchmark**. Run #1 (SWE-bench Lite, 1 instance,
hosted `gpt-5.4-mini`, `identity` baseline) ran through the proxy, produced a real patch,
and was **scored** with the local `swebench` harness: **not resolved (0/1)** — a clean
wrong-fix, not a pipeline failure. The pipeline (generate → apply → run hidden tests →
grade) is fully validated. Next milestone: an **A/B slice** (identity vs prune) to measure
token savings vs resolved-rate.

## Status checklist
- [x] Rig understood: proxy → transform → meter → upstream.
- [x] Hosted-mode wiring (`.env` → OpenAI), verified.
- [x] **Run one SWE-bench instance through the rig** (Run #1, `runs/smoke/preds.json`).
- [x] **Score it** — local `swebench` 4.1.0 harness → not resolved (see `FINDINGS.md`).
- [ ] **A/B a benchmark slice** (`--slice 0:5`): identity vs prune → resolved-rate + token delta. ← NEXT
- [ ] (Optional) `meter.py`: populate `PRICES` + parse `cached_tokens` for real $ / cache-hit ratio.

## Key result (full version in `FINDINGS.md`)
- Workload is **input-dominated (~40:1 input:output)** on a real hosted run; input grows
  every turn as history accumulates → optimize input + use prompt caching.
- Run #1 patch **not resolved**: missed the target `FAIL_TO_PASS` test *and* broke one
  `PASS_TO_PASS` test. A legitimate wrong-fix from `gpt-5.4-mini`.

## Design note for the A/B (important)
Run #1's instance resolves at **0 for the baseline**, so it can't show a transform
*dropping* resolved-rate. The A/B slice needs instances the baseline actually resolves —
run a **larger slice (5–10)** so some pass. Headline = **token savings** (always
measurable) with **resolved-rate as the "did prune break anything" guard.**

## Command cheatsheet

### Run an instance through the rig (hosted)
```bash
# one-time: pre-pull the eval image so container start beats mini's 120s timeout
docker pull docker.io/swebench/sweb.eval.x86_64.sqlfluff_1776_sqlfluff-1625:latest

# terminal 1 — proxy (baseline). identity = no transform = control.
set -a && . ./.env && set +a
RIG_TRANSFORM=identity PYTHONPATH=src .venv/bin/uvicorn rig.proxy:app --port 8787

# terminal 2 — agent generates patches
set -a && . ./.env && set +a
export MSWEA_COST_TRACKING=ignore_errors
.venv/bin/mini-extra swebench -m openai/gpt-5.4-mini --subset lite --slice 0:1 -o runs/smoke
```

### Score predictions (local harness)
```bash
.venv/bin/python -m swebench.harness.run_evaluation \
  --dataset_name princeton-nlp/SWE-bench_Lite --split dev \
  --predictions_path runs/smoke/preds.json \
  --instance_ids sqlfluff__sqlfluff-1625 \
  --run_id smoke-score-1 --max_workers 1 --cache_level instance
# → report at logs/run_evaluation/<run_id>/.../report.json ; key field: "resolved"
```

## Setup & gotchas (learned the hard way)
- **Pre-pull eval images.** They're x86 (~3.6 GB) running under emulation on arm64;
  mini-swe-agent gives the container only **120 s to start**, so a cold pull times out →
  empty patch. Pull once, then runs start in seconds.
- The runner **skips instances already in the output dir's `preds.json`** (even failed
  empty-patch ones). Clear/rename the output dir before re-running.
- `OPENAI_API_BASE` (litellm) points the agent at the proxy on `:8787`; the proxy forwards
  to `RIG_UPSTREAM_BASE`. Both repo `.env` and mini's global `.env` must agree.
- `export MSWEA_COST_TRACKING=ignore_errors` — litellm can't price every model.
- Token usage is logged as `input_tokens`/`output_tokens` in `rig_calls.jsonl` (proxy
  remaps OpenAI's `prompt_tokens`/`completion_tokens`).
- **`.env` is gitignored and was never committed** — repo is public; keep real keys only in `.env`.

## Generated output (gitignored — regenerated on each run)
`runs/` (patches + trajectories), `logs/` (eval reports), `rig_calls.jsonl` (metering),
`reqs.jsonl` / `ab_results.jsonl` (A/B-replay tooling output).
