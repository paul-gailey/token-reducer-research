"""
A/B divergence runner (OpenAI / Ollama).

Replays recorded OpenAI-format request bodies (JSONL) directly against the
local upstream TWICE at temperature 0:
  A) with the active transform applied
  B) with identity (no transform)
and reports per-call divergence + TOKEN savings (cost is ~0 locally).

KEY DESIGN DECISIONS (from the spec):
- Divergence is measured PER API CALL, never per whole agent session.
  (Agentic runs compound trivial perturbations into huge but meaningless
   divergence — the butterfly effect. One call in, one response out.)
- Temp 0 is not fully deterministic, so run identity-vs-identity FIRST to
  measure the NOISE FLOOR. Real divergence = above that floor.

Capture requests by booting the proxy with RIG_DUMP=reqs.jsonl, then driving
mini-swe-agent through it.

Usage:
  python3 ab_runner.py reqs.jsonl identity   # NOISE FLOOR first
  python3 ab_runner.py reqs.jsonl dedup
"""

import json
import os
import sys
import time
import difflib
import httpx

from transforms import _REGISTRY

UPSTREAM_BASE = os.environ.get("RIG_UPSTREAM_BASE", "http://localhost:11434/v1").rstrip("/")
API = f"{UPSTREAM_BASE}/chat/completions"
AB_LOG = os.environ.get("RIG_AB_LOG", "ab_results.jsonl")
HEADERS = {
    "content-type": "application/json",
    # Ollama ignores auth; any non-empty token keeps OpenAI clients happy.
    "authorization": "Bearer " + (os.environ.get("OPENAI_API_KEY") or "ollama"),
}


def _text_of(resp: dict) -> str:
    return "".join(
        (c.get("message", {}) or {}).get("content") or ""
        for c in resp.get("choices", [])
    )


def _in_tokens(resp: dict) -> int:
    return (resp.get("usage", {}) or {}).get("prompt_tokens", 0)


def _divergence(a: str, b: str) -> float:
    """1 - similarity ratio. 0.0 = identical, 1.0 = totally different."""
    if not a and not b:
        return 0.0
    return 1.0 - difflib.SequenceMatcher(None, a, b).ratio()


def call(req: dict) -> dict:
    body = dict(req)
    body["temperature"] = 0      # force determinism as far as possible
    body["stream"] = False       # we want the final object
    r = httpx.post(API, json=body, headers=HEADERS, timeout=600.0)
    r.raise_for_status()
    return r.json()


def run(requests_path: str, transform_name: str):
    transform = _REGISTRY[transform_name]
    identity = _REGISTRY["identity"]
    reqs = [json.loads(l) for l in open(requests_path) if l.strip()]
    run_id = str(int(time.time()))

    print(f"running {len(reqs)} requests: identity vs '{transform_name}' @ temp 0\n")
    rows = []
    for i, req in enumerate(reqs):
        ctrl = call(identity(json.loads(json.dumps(req))))      # B = control
        test = call(transform(json.loads(json.dumps(req))))     # A = transform

        div = _divergence(_text_of(ctrl), _text_of(test))
        in_ctrl, in_test = _in_tokens(ctrl), _in_tokens(test)
        saving = (in_ctrl - in_test) / in_ctrl if in_ctrl else 0.0
        row = {"ts": time.time(), "run_id": run_id, "transform": transform_name,
               "i": i, "divergence": div, "saving_frac": saving,
               "in_ctrl": in_ctrl, "in_test": in_test}
        rows.append(row)
        with open(AB_LOG, "a") as f:
            f.write(json.dumps(row) + "\n")
        print(f"call {i:>3}: divergence={div:.4f}  in-token saving={saving*100:>5.1f}%  "
              f"({in_ctrl} -> {in_test} tok)")

    n = len(rows) or 1
    avg_div = sum(r["divergence"] for r in rows) / n
    tot_ctrl = sum(r["in_ctrl"] for r in rows) or 1
    tot_test = sum(r["in_test"] for r in rows)
    print("\n" + "=" * 52)
    print(f"transform:         {transform_name}")
    print(f"avg divergence:    {avg_div:.4f}")
    print(f"input-token saved: {(1 - tot_test/tot_ctrl)*100:>6.1f}%  "
          f"({tot_ctrl} -> {tot_test} tok)")
    print(f"wrote {len(rows)} rows -> {AB_LOG} (run_id={run_id})")
    print("=" * 52)
    print("\nInterpret:")
    print(" - Run identity-vs-identity FIRST for the NOISE FLOOR (often ~0 at temp 0 locally).")
    print(" - 'dedup' should sit AT the floor (lossless). Above it => bug.")
    print(" - 'prune' is lossy: divergence triages whether the savings are worth it.")


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("usage: python3 ab_runner.py <requests.jsonl> <transform_name>")
        print(f"available transforms: {list(_REGISTRY)}")
        sys.exit(1)
    run(sys.argv[1], sys.argv[2])
