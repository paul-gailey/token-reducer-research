# Token-Reduction Research Rig

A transparent **OpenAI-compatible proxy** that sits between a coding agent and a
model, applies one swappable **context-shrinking transform** per request, and
**meters tokens** in/out — so you can measure how much input context you can
remove before the model's behavior changes.

## Why

Agent workloads are **input-dominated**: the model re-reads a growing context
every turn (Run #1 measured ~40:1 input:output). If you can shrink that context
without changing behavior, you cut cost and latency. This rig quantifies the
tradeoff against a real benchmark (SWE-bench Lite).

## Layout

The Python lives in a `rig` package under `src/` (run with `PYTHONPATH=src`):

- `src/rig/proxy.py` — the proxy + per-call metering (the core).
- `src/rig/transforms.py` — the swappable transforms: `identity`, `dedup`, `prune`.
- `src/rig/meter.py` — token-accounting helpers.
- `src/rig/rig_env.py` — zero-dep `.env` loader (auto-imported by the proxy).
- `src/rig/ab_runner.py` / `rig_data.py` / `dashboard.py` — offline A/B-replay
  tooling (replay captured requests through a transform, diff outputs, visualize).
- `docs/FINDINGS.md` — results writeup. `docs/PROJECT_STATUS.md` — live resume-here doc.

## Quickstart

```bash
# 1. install
pip install -r requirements.txt

# 2. copy env template, add your key (.env is gitignored — never commit a real key)
cp .env.example .env      # then edit OPENAI_API_KEY

# 3. boot the proxy (identity = passthrough baseline)
set -a && . ./.env && set +a
RIG_TRANSFORM=identity PYTHONPATH=src .venv/bin/uvicorn rig.proxy:app --port 8787
```

## Two modes

- **Live benchmark** — drive `mini-swe-agent` against SWE-bench through the proxy;
  the agent produces real patches, scored with the `swebench` harness. See the
  command cheatsheet in `docs/PROJECT_STATUS.md`.
- **Replay A/B** (`src/rig/ab_runner.py`) — replay the *same* captured requests through
  `identity` (control) and a test transform at temperature 0, comparing outputs
  **per call** (never per session, to avoid a compounding agent loop). Generated
  logs (`rig_calls.jsonl`, `ab_results.jsonl`, `reqs.jsonl`) are gitignored.

## Status

See `docs/PROJECT_STATUS.md` for the live checklist and `docs/FINDINGS.md` for results.
