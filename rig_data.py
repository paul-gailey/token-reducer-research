"""
Shared loader for the rig's two log streams. The dashboard and the analysis
notebook both import from here, so the numbers can never drift apart.

  rig_calls.jsonl  -> live proxy traffic (one row per API call)
  ab_results.jsonl -> ab_runner divergence + token-savings (one row per A/B call)
"""

import json
import os
import pandas as pd


def load_calls(path: str = "rig_calls.jsonl") -> pd.DataFrame:
    """Flatten the per-call proxy log into a tidy frame.

    Adds `turn` = call index within each (run_id, session) -> the x-axis for
    context growth.
    """
    if not os.path.exists(path):
        return pd.DataFrame()
    rows = [json.loads(l) for l in open(path) if l.strip()]
    recs = []
    for r in rows:
        u = r.get("usage", {}) or {}
        recs.append({
            "ts": r.get("ts"),
            "run_id": r.get("run_id"),
            "session": r.get("session"),
            "transform": r.get("transform"),
            "n_messages": r.get("n_messages", 0),
            "input_tokens": u.get("input_tokens", 0),
            "output_tokens": u.get("output_tokens", 0),
            "cost_usd": r.get("cost_usd", 0.0),
            "latency_s": r.get("latency_s"),
            "model": u.get("model"),
        })
    df = pd.DataFrame(recs)
    if not df.empty:
        df = df.sort_values("ts").reset_index(drop=True)
        df["turn"] = df.groupby(["run_id", "session"]).cumcount() + 1
    return df


def load_ab(path: str = "ab_results.jsonl") -> pd.DataFrame:
    """Load ab_runner output (divergence + token savings per A/B call)."""
    if not os.path.exists(path):
        return pd.DataFrame()
    return pd.DataFrame([json.loads(l) for l in open(path) if l.strip()])


def noise_floor(ab: pd.DataFrame) -> float:
    """Identity-vs-identity divergence: anything below this is 'no change'."""
    if ab.empty or "transform" not in ab:
        return 0.0
    f = ab[ab["transform"] == "identity"]["divergence"]
    return float(f.mean()) if len(f) else 0.0
