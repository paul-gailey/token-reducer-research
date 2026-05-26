"""
Streamlit dashboard for the token-reduction rig (Ollama / OpenAI).

Three numbers to bring back:
  1. input-token totals + savings per transform   (replaces cache_read_ratio)
  2. per-turn context growth                       (does the tail balloon?)
  3. divergence vs noise floor + token savings     (from ab_runner)

Run:  .venv/bin/streamlit run dashboard.py
"""

import plotly.express as px
import streamlit as st

from rig_data import load_calls, load_ab, noise_floor

st.set_page_config(page_title="Token-Reduction Rig (Ollama)", layout="wide")
st.title("Token-Reduction Research Rig — Ollama / OpenAI")

calls = load_calls()
ab = load_ab()

if calls.empty and ab.empty:
    st.warning("No data yet. Run the proxy behind mini-swe-agent (rig_calls.jsonl) "
               "and/or ab_runner.py (ab_results.jsonl), then hit Refresh.")
    st.stop()

with st.sidebar:
    st.header("Filters")
    if not calls.empty:
        transforms = sorted(calls["transform"].dropna().unique())
        picked = st.multiselect("Transforms", transforms, default=transforms)
        calls = calls[calls["transform"].isin(picked)]
        runs = sorted(calls["run_id"].dropna().unique())
        picked_runs = st.multiselect("Runs", runs, default=runs)
        calls = calls[calls["run_id"].isin(picked_runs)]
    st.button("Refresh")

# ---- 1. input-token totals + savings (replaces cache_read_ratio) ----
st.subheader("1 — input-token totals & savings per transform")
st.caption("Local models have no prompt cache, so this replaces cache_read_ratio: "
           "compare the total input tokens each transform feeds the model.")
if not calls.empty:
    g = calls.groupby("transform").agg(
        calls=("input_tokens", "size"),
        total_input=("input_tokens", "sum"),
        avg_input_per_turn=("input_tokens", "mean"),
        total_output=("output_tokens", "sum"),
    ).reset_index()
    c1, c2 = st.columns(2)
    with c1:
        st.plotly_chart(
            px.bar(g, x="transform", y="total_input",
                   title="total input tokens (lower = more saving)"),
            use_container_width=True)
    with c2:
        st.plotly_chart(
            px.bar(g, x="transform", y="avg_input_per_turn",
                   title="avg input tokens / turn"),
            use_container_width=True)
    st.dataframe(g, use_container_width=True)
else:
    st.info("No proxy calls logged yet.")

# ---- 2. per-turn context growth ----
st.subheader("2 — per-turn context growth")
st.caption("Input tokens vs turn depth, per session — how fast the tail balloons.")
if not calls.empty:
    st.plotly_chart(
        px.line(calls.sort_values("turn"), x="turn", y="input_tokens",
                color="session", line_dash="transform", markers=True,
                title="context size vs turn"),
        use_container_width=True)
else:
    st.info("No proxy calls logged yet.")

# ---- 3. divergence vs noise floor + token savings ----
st.subheader("3 — divergence vs noise floor + token savings")
if not ab.empty:
    floor = noise_floor(ab)
    st.caption(f"Noise floor (identity-vs-identity mean divergence) = {floor:.4f}. "
               "A transform AT the floor is lossless; above it = a loss/bug.")
    agg = ab.groupby("transform").agg(
        divergence=("divergence", "mean"),
        saving=("saving_frac", "mean"),
    ).reset_index()
    c1, c2 = st.columns(2)
    with c1:
        fig = px.bar(agg, x="transform", y="divergence",
                     title="mean divergence per transform")
        fig.add_hline(y=floor, line_dash="dash",
                      annotation_text=f"noise floor {floor:.4f}")
        st.plotly_chart(fig, use_container_width=True)
    with c2:
        st.plotly_chart(
            px.bar(agg, x="transform", y="saving",
                   title="mean input-token saving fraction"),
            use_container_width=True)
    st.dataframe(agg, use_container_width=True)
else:
    st.info("No ab_runner results yet: "
            ".venv/bin/python ab_runner.py reqs.jsonl dedup")
