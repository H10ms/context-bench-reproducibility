# METHODOLOGY — GPT-6 Sol vs GPT-6 Luna (schema v2)

## Research question
How do GPT-6 Sol (`openai/gpt-6-sol`) and GPT-6 Luna
(`openai/gpt-6-luna`) compare on real-world fix quality and engineering
efficiency? The design does not assume either model is better or more
expensive. It measures resolved tasks, cost per successful fix when meaningful,
duration, tokens/tool calls, patch differences, paired outcomes, and replicate
stability.

The active experiment is `gpt6-sol-vs-luna-swbench-v1`, schema v2, seed
`20260920`.

## Why SWE-bench Verified
500 human-validated real GitHub issues with executable FAIL_TO_PASS /
PASS_TO_PASS tests, fixed `base_commit`, official Docker images. A task counts
as solved **only** when the official evaluator says so — no subjective grading.
30 tasks (6 repos × 5) + 18 reserves, frozen in `config/tasks.yaml` before any
model run and never changed after the first real run.

## Why one OpenCode harness for both models
Both non-fast models run via the same `opencode run` invocation (opencode-ai
1.18.31, agent `build`, `--variant medium`, `--format json`, 1800-second
timeout, same Docker image, same network policy, same prompt). Only `--model`
differs. OpenCode may
add its own system instructions — we do not bypass them; we keep version and
configuration identical and record them per run.

## Why 30 tasks / 2 replicates
30 keeps full cost (~120 runs) payable while covering 6 repositories; 2
replicates expose instability (2/2 stable, 1/2 unstable, 0/2 stable failure)
instead of presenting one stochastic run as truth.

## Why paired comparison
Both models attempt the same tasks, so outcomes are paired per task ×
replicate (both / Sol-only / Luna-only / neither). Rates use paired bootstrap
over task IDs; durations/costs use median + IQR + paired differences.

## Why pricing is separate
Two metrics are never mixed. `actual_cost_usd` is the cost observed in
OpenCode/provider events; it is currently observed as `0`. That value is not an
API price. Comparable public API pricing is unknown, so
`normalized_api_cost_usd` remains `null`. `--allow-unknown-cost` is the approved
workflow for smoke, pilot, and full. Any incremental-cost statistic is reported
only when its numerator and denominator are defined; unknown pricing is never
converted to zero.

## What is identical vs what cannot be
Identical: harness version/flags, prompt bytes, tools, permissions, image,
network policy, reasoning flag, timeout, snapshot, evaluator, run policy.
Cannot be fully identical: provider-internal routing/tool strategies, server
versions behind one model ID, token accounting, silent model updates, and the
fact that `--variant` support is provider-defined (actual behavior recorded
per run; see docs/OPENCODE_HARNESS.md).

## Historical data boundary

The GPT-5.6 Sol/GPT-6 Astra campaign remains historical at `results/pilot`,
`results/v2`, `runs/pilot`, and `runs/v2`; its metadata archive is
`archive/sol-vs-astra-swbench-0.2.0/`. Its infrastructure-validation
performance observations are excluded from the active experiment's raw data,
statistics, plots, and conclusions.
