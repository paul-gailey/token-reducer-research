"""
Transform slot — ONE active transform at a time (clean causal attribution).

Each transform is a function: request_dict -> request_dict, operating on the
OpenAI Chat Completions schema (messages[].content is usually a string; tool
turns use assistant.tool_calls + role:"tool" results).

Select the active one via the RIG_TRANSFORM env var. Default: identity.

Experiment ladder (run serially, one per env setting):
  identity -> calibration. ~0 savings, ~0 divergence above the temp-0 noise
              floor. Proves the rig is honest.
  dedup    -> experiment #1 (lossless). Drops EXACT-duplicate, NON-tool-paired
              messages from history. Conservative: in a tool-calling agent loop
              most messages are tool-paired, so this rarely fires — that low
              ceiling is itself an honest finding.
  prune    -> experiment #2 (LOSSY). Truncates the body of OLD tool-result
              messages. Bites hard in agent loops -> real token savings.
              Expect divergence ABOVE the floor; that's the tradeoff to weigh.

Do NOT compose two transforms in week one — attribution dies.
"""

import os
import hashlib


def identity(req: dict) -> dict:
    """No-op. The calibration baseline."""
    return req


def dedup_exact(req: dict) -> dict:
    """
    Experiment #1: drop EXACT-duplicate text messages from history, keeping the
    FIRST occurrence. LOSSLESS by construction.

    Conservative on purpose:
    - Only string-content messages are eligible.
    - NEVER touches `system`, the final (live) message, or any message involved
      in tool-call pairing (assistant.tool_calls / role:"tool" / tool_call_id) —
      dropping one of those would orphan a tool call and 400 the API.
    - Only byte-identical (role, content) duplicates are removed.

    If this ever changes output at temp 0 beyond the noise floor, that's a BUG.
    """
    messages = req.get("messages", [])
    if len(messages) <= 1:
        return req

    seen = set()
    kept = []
    last_i = len(messages) - 1
    for i, msg in enumerate(messages):
        role = msg.get("role")
        content = msg.get("content")
        tool_paired = (
            bool(msg.get("tool_calls"))
            or "tool_call_id" in msg
            or role == "tool"
        )
        if role == "system" or i == last_i or tool_paired or not isinstance(content, str):
            kept.append(msg)
            continue
        fp = hashlib.sha256(f"{role}\x00{content}".encode("utf-8")).hexdigest()
        if fp in seen:
            continue  # drop exact duplicate
        seen.add(fp)
        kept.append(msg)
    req["messages"] = kept
    return req


def prune_old_tool_outputs(req: dict, keep_last: int = 3,
                           head: int = 400, tail: int = 200) -> dict:
    """
    Experiment #2 (LOSSY): truncate the body of tool-result messages older than
    the last `keep_last`, to head+tail chars with an elision marker. This is
    where the real savings live in an agent loop (big command outputs), and
    where divergence is EXPECTED to rise above the floor — the rig's job is to
    quantify how far, so you can decide if the savings are worth it.
    """
    messages = req.get("messages", [])
    tool_idxs = [i for i, m in enumerate(messages) if m.get("role") == "tool"]
    stale = set(tool_idxs[:-keep_last]) if len(tool_idxs) > keep_last else set()
    for i in stale:
        c = messages[i].get("content")
        if isinstance(c, str) and len(c) > head + tail + 40:
            elided = len(c) - head - tail
            messages[i]["content"] = (
                c[:head] + f"\n...[{elided} chars elided by rig]...\n" + c[-tail:]
            )
    return req


# --- registry + single-slot selector ---
_REGISTRY = {
    "identity": identity,
    "dedup": dedup_exact,
    "prune": prune_old_tool_outputs,
}

_ACTIVE_NAME = os.environ.get("RIG_TRANSFORM", "identity")
ACTIVE_TRANSFORM = _REGISTRY.get(_ACTIVE_NAME, identity)


def transform_name() -> str:
    return _ACTIVE_NAME if _ACTIVE_NAME in _REGISTRY else "identity"
