"""
Token-reduction research rig — core proxy (OpenAI / Ollama re-shape).

A transparent localhost proxy for the OpenAI-compatible Chat Completions API.
- Point a harness at it with model=openai/<model> + api_base=http://localhost:8787/v1
- It applies ONE swappable transform to each request (default: identity)
- Forwards to a local OpenAI-compatible upstream (Ollama), streaming back UNBUFFERED
- Parses a COPY of the stream out-of-band to meter token usage per call

Design rules (unchanged from the original Anthropic rig):
- Never buffer the response to read it. Pass SSE chunks through as they arrive.
- Transform is a single pure-ish function request_dict -> request_dict.
- Metering reads OpenAI usage: prompt_tokens (input) + completion_tokens (output).
  NOTE: local models report no prompt-cache-read tokens, so there is no
  cache_read_ratio here — context-growth and token-savings replace it.

Routes BOTH /v1/chat/completions and /chat/completions (litellm uses whichever
matches your api_base; with .../v1 it sends /v1/chat/completions).
"""

import json
import os
import time
import hashlib
import httpx
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse, JSONResponse

from rig import rig_env  # noqa: F401 — loads .env into os.environ; MUST precede the rig imports below
from rig.transforms import ACTIVE_TRANSFORM, transform_name
from rig.meter import record_call

# OpenAI-compatible upstream. Ollama's default is http://localhost:11434/v1
UPSTREAM_BASE = os.environ.get("RIG_UPSTREAM_BASE", "http://localhost:11434/v1").rstrip("/")
LISTEN_PORT = int(os.environ.get("RIG_PORT", "8787"))
# If set, dump each ORIGINAL request body as JSONL here (feed to ab_runner.py).
DUMP_PATH = os.environ.get("RIG_DUMP")

app = FastAPI()
client = httpx.AsyncClient(timeout=httpx.Timeout(600.0))

# One run id per proxy process; calls are grouped by `session` (first-message
# fingerprint) so per-turn context growth is plottable across a task.
RUN_ID = str(int(time.time()))


def _session_id(req: dict) -> str:
    """Stable per-session fingerprint from the first (seed) message."""
    msgs = req.get("messages") or []
    if not msgs:
        return "empty"
    first = msgs[0].get("content", "") if isinstance(msgs[0], dict) else msgs[0]
    if not isinstance(first, str):
        first = json.dumps(first, sort_keys=True, default=str)
    return hashlib.sha256(first.encode("utf-8")).hexdigest()[:12]


def _msg_text(content) -> str:
    """OpenAI content is usually a str; can be a list of parts (multimodal)."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(p.get("text", "") for p in content
                       if isinstance(p, dict) and p.get("type") == "text")
    return ""


def parse_sse_for_usage(raw_event_block: str, acc: dict):
    """
    Parse a copy of an OpenAI SSE chunk. Pulls streamed text + final usage.
    OpenAI streams text in choices[].delta.content; usage appears only in the
    terminal chunk when stream_options.include_usage=true (the proxy injects it).
    """
    for line in raw_event_block.splitlines():
        if not line.startswith("data:"):
            continue
        payload = line[len("data:"):].strip()
        if not payload or payload == "[DONE]":
            continue
        try:
            obj = json.loads(payload)
        except json.JSONDecodeError:
            continue
        u = obj.get("usage")
        if u:
            acc["input_tokens"] = u.get("prompt_tokens", 0)
            acc["output_tokens"] = u.get("completion_tokens", 0)
            acc["model"] = obj.get("model")
        for ch in obj.get("choices", []) or []:
            delta = ch.get("delta", {}) or {}
            if delta.get("content"):
                acc.setdefault("text", "")
                acc["text"] += delta["content"]


async def _handle(request: Request):
    body = await request.body()
    try:
        req = json.loads(body)
    except json.JSONDecodeError:
        return JSONResponse({"error": "invalid json"}, status_code=400)

    if DUMP_PATH:
        with open(DUMP_PATH, "a") as f:
            f.write(json.dumps(req) + "\n")

    # --- THE TRANSFORM SLOT (one function, swappable) ---
    original_req = req
    transformed_req = ACTIVE_TRANSFORM(json.loads(json.dumps(req)))  # deep-copy in
    tname = transform_name()

    fwd_headers = {
        k: v for k, v in request.headers.items()
        if k.lower() not in ("host", "content-length")
    }

    is_stream = bool(transformed_req.get("stream", False))
    if is_stream:
        # ask the upstream to include usage in the terminal chunk
        transformed_req.setdefault("stream_options", {})["include_usage"] = True

    started = time.time()
    url = f"{UPSTREAM_BASE}/chat/completions"
    session = _session_id(original_req)
    n_messages = len(transformed_req.get("messages", []))

    if not is_stream:
        # Simple path: forward, read, meter, return.
        resp = await client.post(url, json=transformed_req, headers=fwd_headers)
        try:
            data = resp.json()
        except Exception:
            return JSONResponse(
                {"error": "upstream returned non-json", "body": resp.text[:500]},
                status_code=502,
            )
        usage = data.get("usage", {}) or {}
        record_call(
            transform=tname,
            usage={
                "input_tokens": usage.get("prompt_tokens", 0),
                "output_tokens": usage.get("completion_tokens", 0),
                "model": data.get("model"),
            },
            latency=time.time() - started,
            text=_extract_text(data),
            n_messages=n_messages,
            session=session,
            run_id=RUN_ID,
        )
        return JSONResponse(data, status_code=resp.status_code)

    # --- STREAMING PATH: pass through unbuffered, parse a copy out-of-band ---
    async def stream_gen():
        acc = {}
        async with client.stream(
            "POST", url, json=transformed_req, headers=fwd_headers
        ) as upstream:
            buffer = ""
            async for chunk in upstream.aiter_bytes():
                yield chunk  # pass through IMMEDIATELY (no latency added)
                buffer += chunk.decode("utf-8", errors="ignore")
                while "\n\n" in buffer:
                    event_block, buffer = buffer.split("\n\n", 1)
                    parse_sse_for_usage(event_block, acc)
        record_call(
            transform=tname,
            usage={
                "input_tokens": acc.get("input_tokens", 0),
                "output_tokens": acc.get("output_tokens", 0),
                "model": acc.get("model"),
            },
            latency=time.time() - started,
            text=acc.get("text", ""),
            n_messages=n_messages,
            session=session,
            run_id=RUN_ID,
        )

    return StreamingResponse(stream_gen(), media_type="text/event-stream")


@app.post("/v1/chat/completions")
async def chat_v1(request: Request):
    return await _handle(request)


@app.post("/chat/completions")
async def chat_bare(request: Request):
    return await _handle(request)


def _extract_text(data: dict) -> str:
    parts = []
    for ch in data.get("choices", []) or []:
        msg = ch.get("message", {}) or {}
        parts.append(_msg_text(msg.get("content")))
    return "".join(parts)


@app.get("/health")
async def health():
    return {"ok": True, "transform": transform_name(), "upstream": UPSTREAM_BASE}
