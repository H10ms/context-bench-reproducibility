# COSTS — GPT-6 Sol vs GPT-6 Luna (schema v2)

Pricing lives in `config/pricing.yaml` (`price_source`, `price_checked_at`,
per-model `input_per_1m` / `cached_input_per_1m` / `output_per_1m` /
`reasoning_per_1m` + `reasoning_billing_notes`). Comparable pricing for
`openai/gpt-6-sol` and `openai/gpt-6-luna` is currently unknown, so all
per-token prices remain `null`.

## Two metrics, never mixed
- `actual_cost_usd`: cost reported by OpenCode/provider in run events. The
  observed value is `0`; this describes the OpenCode event and is not an API
  price or evidence that inference is free.
- `normalized_api_cost_usd`: observed usage × public per-token price (null
  when pricing is unknown). It remains `null` for this experiment.

## Estimate before spending
```powershell
python -m context_bench estimate
python -m context_bench estimate --max-budget-usd 100
```
Estimates use `expected_input_tokens_per_run` (30k) and
`expected_output_tokens_per_run` (6k). Unknown pricing → estimate `null` +
explicit warning. `full` REQUIRES `--max-budget-usd`; unknown normalized cost
blocks real runs unless `--allow-unknown-cost`. Because pricing is unknown,
`--allow-unknown-cost` is the approved workflow for smoke, pilot, and full; it
does not turn an unknown normalized cost into zero. The full command still
requires `--max-budget-usd` as a launch guard.

## Incremental economics (in `analyze`)
totals per model → `cost_per_resolved` → incremental cost / incremental
resolved → cost per additional resolved task. These statistics are undefined
when normalized prices are unknown or the relevant outcome difference is zero;
the analysis must report that state rather than infer a performance or price
conclusion.

Historical Sol/Astra cost records remain only in the legacy artifact stores and
metadata archive `archive/sol-vs-astra-swbench-0.2.0/`; they are not used to
fill active Sol/Luna pricing or cost fields.
