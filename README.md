# Token-Reduction Research Rig (Ollama / OpenAI-format)

Transparent OpenAI-compatible proxy + pluggable transform slot + differential meter.
Routes a coding harness (mini-swe-agent) through a **local Ollama model**, so
experiments are free to run. Mechanisms are experiments you run on the rig, not
commitments.

> Re-shaped from the original Anthropic-format rig (preserved in `legacy_anthropic/`).
> Local models report **no prompt-cache-read tokens**, so `cache_read_ratio` is gone —
> the headroom signals here are **input-token growth** and **token savings**.

## Files
- `proxy.py`       — localhost proxy on `/v1/chat/completions`. Unbuffered SSE pass-through, out-of-band metering. Forwards to Ollama.
- `transforms.py`  — the single transform slot: `identity`, `dedup`, `prune`.
- `meter.py`       — per-call token logging + (optional) cost.
- `ab_runner.py`   — replays recorded requests transform-on vs off @ temp 0; measures divergence + token savings.
- `rig_data.py`    — shared loader for the two log streams.
- `dashboard.py`   — Streamlit live dashboard (the three numbers).
- `analysis.ipynb` — Jupyter narrative of the same charts.

## Setup
```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
ollama serve &                 # start the local model server (port 11434)
ollama pull llama3.1           # a TOOL-CAPABLE model (mini-swe-agent v2 uses tool calls)
```

## Run sequence (the experiment ladder)

### Step 1: boot the rig in pass-through
```bash
# identity transform = pure pass-through baseline
RIG_TRANSFORM=identity .venv/bin/uvicorn proxy:app --port 8787
# upstream defaults to http://localhost:11434/v1 (override with RIG_UPSTREAM_BASE)
```

### Step 2: point mini-swe-agent at it
mini-swe-agent calls models via **litellm**. Use the `openai/` provider so litellm
speaks the OpenAI Chat Completions API, and set the base URL to the proxy (with `/v1`):
```bash
export OPENAI_API_KEY=ollama                  # any non-empty string; Ollama ignores it
export OPENAI_API_BASE=http://localhost:8787/v1
.venv/bin/mini -m openai/llama3.1 -y -t "your coding task"
# (litellm with api_base=.../v1 sends POST /v1/chat/completions — the proxy route)
```
⚠️ litellm honors `OPENAI_API_BASE`, **NOT** the Anthropic SDK's `ANTHROPIC_BASE_URL`.

### Step 3: read the numbers
```bash
.venv/bin/python meter.py                 # per-transform token totals
.venv/bin/streamlit run dashboard.py      # live charts
.venv/bin/jupyter notebook analysis.ipynb # narrative
```

### Step 4: calibrate divergence (the noise floor), then run experiments
Capture real requests by booting the proxy with `RIG_DUMP=reqs.jsonl`, drive a task,
then:
```bash
.venv/bin/python ab_runner.py reqs.jsonl identity   # NOISE FLOOR (≈0 at temp 0 locally)
.venv/bin/python ab_runner.py reqs.jsonl dedup      # lossless: divergence AT the floor
.venv/bin/python ab_runner.py reqs.jsonl prune      # lossy: savings vs divergence
```
Divergence above the floor for `dedup` = a bug, not a tradeoff. For `prune`, divergence
triages whether the savings are worth it. ONE transform at a time — never compose.

### Step 5+: add risky transforms
Add a function to `transforms.py`, register it, set `RIG_TRANSFORM=<name>`.

## The three numbers to bring back
1. input-token totals / savings per transform (does it actually shrink context?)
2. per-turn context growth (how fast does the tail balloon?)
3. divergence vs noise floor + token savings (lossless? worth the tradeoff?)

## Notes
- Use a **tool-capable** Ollama model (e.g. `llama3.1`, `qwen2.5`, `mistral-nemo`).
  mini-swe-agent v2 uses tool calls; for non-tool models see its text-based model class.
- Cost is ~0 locally. Populate `PRICES` in `meter.py` only if you A/B against a paid endpoint.
