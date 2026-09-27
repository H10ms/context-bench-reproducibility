# TASK_SELECTION — how the 30+18 set was fixed (before any model run)

## Target
30 main (6 repos × 5) + ≥18 reserves (≥3/repo), all in SWE-bench Verified
(HF `SWE-bench/SWE-bench_Verified`, 500 rows, snapshot 78f471bf).

## Repository choice
Preferred: django, sympy, matplotlib, scikit-learn, pydata/xarray,
pallets/flask. Verified pool sizes: django 231, sympy 75, sphinx 44,
matplotlib 34, sklearn 32, astropy 22, xarray 22, pytest 19, …, flask **1**.
**flask is impossible (5+3 needed) → substituted with sphinx-doc/sphinx (44).**
No other substitution was needed. The active Sol/Luna task set was fixed
without using model outcomes. Historical Sol/Astra infrastructure-validation
observations are excluded from active data and were not used to revise the
selection.

## Main-task rule
- django/matplotlib/sklearn/sympy: reuse of the 20 IDs validated in the
  previous project stage (fixed before any model output; zero runs executed).
  Their official-difficulty mix: 9× `<15 min`, 2× `15 min–1h`, 8× `1–4h`,
  1× `>4h` — already a spread, so re-picking would only add churn.
- xarray/sphinx: deterministic difficulty-cycled picks
  (`task_selection.cycled_order`): round-robin across official difficulty
  buckets [`<15 min fix`, `15 min - 1 hour`, `1-4 hours`, `>4 hours`],
  sorted instance_ids within bucket. Main = first 5 cycled (each repo gets
  one task per bucket incl. a `>4h` task + one extra easy).
  - xarray: 4075, 2905, 3993, 6992, 4094
  - sphinx: 10323, 10466, 11510, 7590, 10435

## Reserve rule
Old repos: keep 2 previous reserves each + first sorted unused instance_id
(django-10097, matplotlib-14623, sklearn-10297, sympy-11618).
xarray/sphinx: next 3 cycled after the 5 mains.

## issue_type
Keyword heuristic over issue text only (`classify_issue_type`), stored as
`issue_type` + `issue_type_method=heuristic`. Never uses gold patch length or
any fix-derived signal.

## Substitutions
2026-09-20 (pre-first-model-run, same-repo, recorded): 6 carried-over v1
reserve IDs are NOT in SWE-bench Verified at all (v1 never resolution-checked
reserves): django-11039, matplotlib-18811, matplotlib-25778,
scikit-learn-25570, sympy-15609, sympy-15346. Replaced with first sorted
unused same-repo IDs: django-10554, matplotlib-20488, matplotlib-20676,
scikit-learn-10844, sympy-12096, sympy-12419. Rule for any further change:
same-repo reserve only, before the first real model run, reason appended
here. After the first paid run the set is frozen (enforced by
`experiments/gpt6-sol-vs-luna-swbench-v1/EXPERIMENT_FREEZE.json` for full).

## Experiment boundary

The active experiment is `gpt6-sol-vs-luna-swbench-v1` (schema v2, seed
`20260920`) and retains the same 30 main tasks and 18 reserves. The old GPT-5.6
Sol/GPT-6 Astra artifacts at `results/pilot`, `results/v2`, `runs/pilot`, and
`runs/v2`, plus metadata in `archive/sol-vs-astra-swbench-0.2.0/`, are
historical and are not part of the active selection evidence or results.
