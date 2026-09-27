# Article analysis (technical, NOT a polished article)

Experiment `gpt6-sol-vs-luna-swbench-v1`, harness v0.3.1, freeze `c52033ee...`.
Full raw SHA `1A388A6B...`: 136 physical / 120 canonical observations. No new runs,
no methodology changes; figures/tables here are presentation of frozen outputs plus
straightforward descriptives (ratios/differences labelled as such).

## Experiment snapshot

- 30 SWE-bench Verified tasks (django/matplotlib/scikit-learn/sympy/xarray/sphinx-doc),
  2 repetitions, 2 models (`openai/gpt-6-sol`, `openai/gpt-6-luna`).
- Paired design: same task x repetition for both models; identical OpenCode harness
  (`build` agent, `--variant medium`, reasoning medium, 1800s timeout, prompt wrapper
  `2c24f38e...`, evaluator SWE-bench 5.0.2). Only `--model` differs.
- 120 canonical observations (Sol 60, Luna 60). Pilot/smoke excluded from full stats.

## Primary quality result

- Sol: 33/60 resolved (55.0%); Luna: 23/60 (38.3%). Absolute difference: +16.7pp (Sol).
- Denominator 60 includes 3 empty-patch no-verdict terminals per model. Verdict-only
  rates (33/57 = 57.9% vs 23/57 = 40.4%) are secondary; do not use them as primary.
- Uncertainty immediately: frozen task-level rates Sol 0.621 [0.448, 0.793],
  Luna 0.483 [0.310, 0.655] (task-bootstrap B=2000, seed 20260920, n_tasks=29).
  Intervals overlap substantially. Do NOT say "Sol is definitively better".

## Paired analysis

- 55 complete replicate-pairs: both solved 21, only Sol 11, only Luna 2, neither 21.
  5 pairs excluded by the frozen dropna rule (NONE on at least one side).
- Frozen inferential outputs: paired effect (Luna−Sol) −13.79pp, 95% CI [−31.03, 0.0].
  The CI touches zero: at two-sided 5% the task-clustered analysis does not exclude
  no-difference.
- McNemar exact (frozen-designated): discordant 11 vs 2 → two-sided p ≈ 0.0225
  (one-sided ≈ 0.0112), binomial n=13, H0 p=0.5.
- Reconciliation: McNemar's unit is the replicate-pair treated as independent (n=55,
  effective n=13 discordant), ignoring that two reps share one task (correlated
  difficulty) — narrower, overconfident under clustering. Task-bootstrap resamples
  whole tasks, preserving within-task correlation — wider, clustering-robust, and it
  estimates a different quantity (mean task-level difference vs marginal homogeneity).
  Report both with assumptions; never cherry-pick the friendlier one.

## Efficiency (descriptive only, no new tests)

- Runtime: Sol median 133.1s vs Luna 83.2s (medians differ by ~50s; ratio ≈ 1.60x;
  totals 9516s vs 5491s, ratio ≈ 1.73x). No timeouts.
- Tokens: total median Sol 30694 vs Luna 24460 (ratio ≈ 1.25x; totals ≈ 1.41x);
  input ≈ 1.22x median (28690 vs 23410); output ≈ 1.63x (1893 vs 1165);
  reasoning ≈ 3.6x median (628 vs 174; totals 50415 vs 13369, ≈ 3.77x).
  Tool calls median 21 vs 13.
- Luna used fewer resources on every measured axis in this harness; whether that
  generalises is unsupported.

## Patch behavior

- Sol patches larger: bytes median 2069 vs 1366 (means 3134 vs 1955);
  lines added median 15.5 vs 8.5; deleted 2.0 vs 1.0.
- Size is NOT quality: do not claim larger/smaller patches are better or worse.

## Task-level behavior

- Both consistently successful (9 tasks): django-7530/9296, matplotlib-13989/22719/25287,
  sklearn-14141/9288, sphinx-10323/10466.
- Both consistently fail (9 tasks): django-13212, matplotlib-25479, xarray-3993/6992,
  sphinx-11510/7590, sympy-12489/13852/16597.
- Mixed/unstable: xarray-2905/4075, sklearn-25102/25232/25973, sphinx-10435, sympy-13878.
- Clear disagreement: django-11138/16631 (Sol-only), sympy-13878 (crossed reps).
- Partially unverdicted: matplotlib-24177, xarray-4094, sympy-14248.
- No repository ranking; no causal claims (e.g. "sympy is hard because...") beyond data.

## Reliability / infrastructure

- 136 physical vs 120 canonical: 16 append-only retries (13 provider 403/gateway,
  1 interrupted evaluator with real patch, 2 chained re-403s), each with `retry_of`
  lineage; 2 superseded mid-chain records excluded from canonical by frozen rule.
- One session interruption + Docker daemon outage mid-campaign → штатный `--resume`
  (71 done skipped, 49 completed, 0 auth errors in resumed batch).
- Terminal canonical: provider errors 0, timeouts 0, non-zero exits 0, patch
  application failures 0, malformed 0. Canonical dataset is exactly 120 (all-once
  coverage of task x model x repetition).

## Empty patches

- 6 no-verdict terminals (Sol 3, Luna 3): genuine sessions (7–28 tool calls) with zero
  file changes; evaluator reports "empty patches", resolved=None. NOT retried — frozen
  policy forbids retrying model results/bad patches. Frozen stats drop them
  (`_resolved_long` dropna) → 55/60 paired units, task n=29. They are model outcomes,
  kept separate from infrastructure failures.

## Cost limitation

- `actual_cost_usd = 0.0` everywhere (subscription/ChatGPT Plus OpenCode path).
- `normalized_api_cost_usd = null` everywhere → `unknown-cost`.
- FORBIDDEN framings: "Sol/Luna costs $0", "one model is cheaper in API usage".
- Correct: no comparable normalized pricing was configured, so monetary API-cost
  comparison is unavailable; token-consumption comparison IS valid.

## Threats to validity

- Only 30 tasks / six repos / two repetitions — small, narrow sample.
- SWE-bench Verified tasks, not arbitrary production work.
- OpenCode agent + harness + prompt are part of the measured system.
- Provider/model behavior may drift over time; single time window (2026-09-23/24).
- No normalized API-cost comparison possible.
- 5/60 pairs unavailable for paired binary analysis (NONE handling per frozen rule).
- 16 infrastructure retries (documented lineage, but campaign was not pristine).
- Task selection/environment limits (offline parquet fallback, pre-pulled images).
- Runtime/token gaps are harness-conditional descriptives, not universal properties.

## What the data supports

- Sol had a higher observed resolve rate in this experiment (33/60 vs 23/60).
- On 55 complete pairs: 21/21/11/2 split; discordant pairs favour Sol 11:2.
- Luna consumed fewer tokens/time per run on every measured axis here.
- Task-bootstrap CI for the paired difference includes zero — uncertainty is large.
- McNemar exact two-sided p ≈ 0.022 on discordant pairs (assumes pair independence).

## What the data does NOT support

- "Sol is definitively/universally better" (CI includes 0; n=30 tasks).
- "Statistical significance" as a single claim (two frozen procedures disagree in
  strength; report both + assumptions).
- Any cost/price conclusion (no normalized pricing).
- "Larger/smaller patches are better".
- Repository difficulty rankings or causal task explanations.
- Generalisation beyond this harness/window/repetition count.

## Claim discipline

| Claim | Evidence | Strength | Safe wording |
|---|---|---|---|
| Sol had higher observed resolve rate | 33/60 vs 23/60 canonical | Directly supported (descriptive) | "In this 120-observation experiment Sol resolved 33/60 vs Luna 23/60" |
| Sol is always better | None (n=30, CI incl. 0) | Unsupported | Do not write |
| Sol is statistically significantly better | McNemar p≈0.022 BUT bootstrap CI incl. 0; conflicting assumptions | Contested — report both | "Discordant-pair exact test gives p≈0.022; the task-clustered 95% CI includes zero — evidence is mixed, not decisive" |
| Sol used more tokens here | Medians/totals all axes | Supported descriptively | "Per-run medians: total 30694 vs 24460; reasoning 628 vs 174" |
| Luna is cheaper | No normalized pricing | Unsupported | "Monetary comparison unavailable; token use was lower for Luna" |
| Sol is slower in this harness | Runtime medians/totals | Supported descriptively | "Median wall time 133s vs 83s under identical 1800s cap" |
