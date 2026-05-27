# Token-Reduction Rig — Experiment #1 Findings

*Single-task pilot. Model: `qwen2.5:7b-instruct-q4_K_M` (local, 4-bit, via Ollama). Date: 2026-05-26.*

## Abstract

A transparent OpenAI-compatible proxy was placed between a coding agent
(`mini-swe-agent`) and a local model. One agent task ("create `hello.py` that
prints hello world, then run it") was recorded as 12 chat-completion requests
and **replayed at temperature 0** under three context-shrinking transforms,
each compared call-for-call against an untransformed control. We report
**input-token savings** and **output divergence** (`1 − difflib similarity`)
per transform, anchored to a measured **noise floor**.

**Headline result:** `dedup`, a transform that removes only byte-identical
messages and is documented as "lossless by construction," was **not
behavior-preserving** — on every call where it actually fired, the model's
output diverged well above the noise floor, while the matched control diverged
zero. `prune` (lossy) delivered the largest savings (~16%) with a non-uniform,
quantifiable behavioral cost.

## Method

- **Rig:** `proxy.py` forwards requests to Ollama and meters `prompt_tokens` /
  `completion_tokens` per call. Requests captured via `RIG_DUMP=reqs.jsonl`.
- **A/B protocol** (`ab_runner.py`): for each recorded request, call the model
  twice at `temperature=0` — once with `identity` (control), once with the test
  transform — and compare the two replies. **Divergence is measured per call,
  never per session**, to avoid the butterfly effect of compounding agent loops.
- **Noise floor:** `identity`-vs-`identity` is run first to measure the
  divergence produced by changing *nothing* (temp 0 is not fully deterministic).
- **One transform at a time** — no composition — for clean causal attribution.
- **Sample:** 1 task → 12 replayed requests × 3 transforms = 36 A/B calls.

## Results

| transform  | n  | mean divergence | overall input-token saving | calls where it fired |
|------------|----|-----------------|----------------------------|----------------------|
| `identity` | 12 | 0.0521          | 0.00%                      | — (none)             |
| `dedup`    | 12 | 0.1533          | **1.45%**                  | 9, 10, 11            |
| `prune`    | 12 | 0.2315          | **15.99%**                 | 5, 6, 7, 8, 9, 10, 11 |

![Fig 2 — divergence vs noise floor, and savings](figures/fig2_divergence_savings.png)

### Per-call divergence, aligned by request index

The control (`identity`) column is the key: it tells us which calls are
*intrinsically* deterministic, so we can attribute the rest.

| req `i` | identity | dedup | prune | dedup save% | prune save% |
|--------:|---------:|------:|------:|------------:|------------:|
| 0  | 0.000 | 0.000 | 0.000 |  0.0 |  0.0 |
| 1  | **0.625** | **0.625** | **0.625** |  0.0 |  0.0 |
| 2  | 0.000 | 0.000 | 0.000 |  0.0 |  0.0 |
| 3  | 0.000 | 0.000 | 0.000 |  0.0 |  0.0 |
| 4  | 0.000 | 0.000 | 0.000 |  0.0 |  0.0 |
| 5  | 0.000 | 0.000 | 0.000 |  0.0 | 14.1 |
| 6  | 0.000 | 0.000 | 0.578 |  0.0 | 26.7 |
| 7  | 0.000 | 0.000 | 0.262 |  0.0 | 25.6 |
| 8  | 0.000 | 0.000 | 0.570 |  0.0 | 24.6 |
| 9  | 0.000 | **0.752** | 0.488 |  3.5 | 23.9 |
| 10 | 0.000 | **0.340** | 0.196 |  3.4 | 23.1 |
| 11 | 0.000 | **0.123** | 0.058 |  6.6 | 22.5 |

![Fig 3 — per-call savings vs divergence tradeoff](figures/fig3_tradeoff.png)
![Fig 1 — context growth on the baseline task](figures/fig1_context_growth.png)

## Findings

### 1. The noise floor is real, non-uniform, and indispensable
At temp 0 the model was perfectly deterministic on **11 of 12** requests
(divergence exactly 0.000) but produced one large spike (**0.625**) on request
`i=1` — *reproducibly across all three runs*. Because `identity` isolates it, we
know that spike is intrinsic sampling nondeterminism, not a transform effect.
Without the control column, `dedup`'s mean divergence of 0.153 would be
misread — roughly a third of it is just the shared `i=1` noise. **Divergence is
meaningless except relative to a measured floor.**

### 2. (Headline) "Lossless by construction" ≠ behavior-preserving
`dedup` removes only byte-identical, non-tool-paired messages; its docstring
asserts that divergence above the floor "is a BUG." Yet on the three calls where
it actually removed a duplicate (`i=9,10,11`, saving 3.5 / 3.4 / 6.6% tokens),
divergence was **0.752 / 0.340 / 0.123** — while the matched `identity`
divergence on those exact requests was **0.000**. Since the control proves those
requests deterministic, the drift is **causally attributable to dedup**.
Removing duplicated context measurably changed the model's output.
**Byte-losslessness does not imply behavioral losslessness.**
*(Open: is this a transform bug — dropping a load-bearing message — or genuine
model sensitivity to duplicate context? Resolving this requires diffing the
actual text. See Next Steps #1.)*

### 3. `prune` is a real, quantified, non-uniform lossy win
`prune` gave the largest savings — **15.99% overall**, up to 26.7% on a single
call — at the cost of divergence rising to 0.2–0.58 where it bit. But the cost
is **not uniform**: call `i=5` saved 14.1% at **0.000** divergence (a truncated
old tool-output that genuinely didn't affect the answer), and `i=11` saved 22.5%
at only 0.058. Some truncations are free; others change behavior. The rig's job
is to tell you which.

### 4. Context-reduction savings are back-loaded
Neither transform saved anything on calls 0–4 — early in a task there is nothing
duplicated or stale to remove. `dedup`'s entire effect was on calls 9–11;
`prune` began biting at call 5. Savings **grow with the task**, i.e. they arrive
exactly when the context balloon (Fig 1: input climbed 910 → 3557 tokens while
output stayed flat) hurts most.

## Threats to validity

- **Not a benchmark.** The task was a single *self-authored, synthetic* smoke-test
  ("create hello.py"), with no pass/fail oracle — not a SWE-bench (or other
  benchmark) instance. There is therefore no ground-truth measure of whether any
  transform changed task *correctness*; only text divergence was observed.
- **n = 1 task, 12 calls.** A pilot, not a powered study. No confidence intervals.
- **One small, quantized, local model.** Results may not transfer to larger or
  hosted models; 4-bit quantization may amplify nondeterminism (cf. the `i=1` spike).
- **Divergence ≠ quality.** `difflib` text-diff says outputs *differ*, not that
  they are worse. A diverged reply could be equally correct. Task *success* under
  `dedup`/`prune` was **not** scored — only the `identity` task is known to complete.
- **Floor is run-dependent.** The identity mean (0.0521) is driven almost
  entirely by one spike; a different run could move it.
- **Append-only logs.** Runs separated by `run_id`, aligned by request index `i`;
  identical per-`i` `in_ctrl` values confirm the same `reqs.jsonl` across all three.

## Next steps (open questions)

1. **Diagnose dedup's drift** — dump the control-vs-test *text* on calls 9–11.
   Transform bug, or real sensitivity to duplicate context? (Highest priority.)
2. **Score task success**, not just text diff — does prune's 16% saving still let
   the agent finish the task?
3. **More tasks + more seeds** for statistical power; report the divergence
   *distribution*, not just the mean.
4. **Tune `prune`** (`keep_last`, `head`, `tail`) to find the savings/divergence knee.
5. **Test a hosted model with prompt caching** to compare against cache-read
   economics (the original Anthropic-format rig's metric).
6. **Semantic divergence** (embedding similarity) as a complement to raw text diff.

## Reproduce

```bash
# capture
RIG_TRANSFORM=identity RIG_DUMP=reqs.jsonl .venv/bin/uvicorn proxy:app --port 8787
# (drive a task through mini-swe-agent against http://localhost:8787/v1)

# replay ladder — floor first
.venv/bin/python ab_runner.py reqs.jsonl identity
.venv/bin/python ab_runner.py reqs.jsonl dedup
.venv/bin/python ab_runner.py reqs.jsonl prune
```
Raw data: `ab_results.jsonl` (A/B), `rig_calls.jsonl` (live metering), `reqs.jsonl` (replayed requests).
