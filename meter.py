"""
Meter — records every call's token usage (OpenAI / Ollama schema).

Writes one JSONL line per call to rig_calls.jsonl. Local models report
prompt_tokens (input) and completion_tokens (output); there is NO cache-read
token, so cache_read_ratio is gone. The headroom signals here are context
growth and token savings between transforms (see dashboard.py / analysis.ipynb).

Cost is ~0 for local models. PRICES is kept (default 0) so you can plug in
hosted-model prices later if you A/B against a paid endpoint.
"""

import json
import os
import time

CALLS_LOG = os.environ.get("RIG_LOG", "rig_calls.jsonl")

# Per-million-token USD prices by model substring. Local/Ollama => 0.
PRICES: dict[str, dict] = {
    # "gpt-4o": {"input": 2.5, "output": 10.0},
}
DEFAULT_PRICE = {"input": 0.0, "output": 0.0}


def _price_for(model: str | None) -> dict:
    if model:
        m = model.lower()
        for key, p in PRICES.items():
            if key in m:
                return p
    return DEFAULT_PRICE


def call_cost(usage: dict) -> float:
    """USD cost of a single call. ~0 for local models (no prices registered)."""
    p = _price_for(usage.get("model"))
    inp = usage.get("input_tokens", 0)
    out = usage.get("output_tokens", 0)
    return (inp * p["input"] + out * p["output"]) / 1_000_000


def record_call(transform: str, usage: dict, latency: float, text: str = "",
                n_messages: int = 0, session: str | None = None,
                run_id: str | None = None):
    row = {
        "ts": time.time(),
        "run_id": run_id,
        "session": session,
        "transform": transform,
        "n_messages": n_messages,  # turn depth -> x-axis for context growth
        "usage": usage,
        "cost_usd": round(call_cost(usage), 6),
        "latency_s": round(latency, 3),
        "text_len": len(text),
        "text_head": text[:200],  # short fingerprint for divergence diffing
    }
    with open(CALLS_LOG, "a") as f:
        f.write(json.dumps(row) + "\n")


def report(path: str = CALLS_LOG):
    """Aggregate the log: per-transform token totals + avg input per turn."""
    if not os.path.exists(path):
        print("no calls logged yet")
        return
    rows = [json.loads(l) for l in open(path) if l.strip()]
    by_t = {}
    for r in rows:
        t = r["transform"]
        b = by_t.setdefault(t, {"calls": 0, "inp": 0, "out": 0, "cost": 0.0})
        u = r["usage"]
        b["calls"] += 1
        b["inp"] += u.get("input_tokens", 0)
        b["out"] += u.get("output_tokens", 0)
        b["cost"] += r["cost_usd"]

    print(f"{'transform':<12}{'calls':>7}{'in_tok':>12}{'out_tok':>12}{'avg_in/turn':>13}")
    print("-" * 56)
    for t, b in by_t.items():
        avg_in = b["inp"] / b["calls"] if b["calls"] else 0
        print(f"{t:<12}{b['calls']:>7}{b['inp']:>12}{b['out']:>12}{avg_in:>13.0f}")
    print()
    print("No cache_read_ratio on local models. Compare 'in_tok' across transforms")
    print("to read the savings; watch 'avg_in/turn' for context growth.")


if __name__ == "__main__":
    report()
