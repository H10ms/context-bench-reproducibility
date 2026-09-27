"""Paired GPT-6 Sol-vs-Luna statistics (schema v2).

- resolved: paired bootstrap over TASK IDs (never over runs as independent),
  difference in percentage points, McNemar on replicate pairs.
- duration/cost/tokens: median + IQR + paired difference.
- cost: actual vs normalized kept separate; incremental cost per additional
  resolved guarded against zero/negative denominators.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

MODELS = ["sol", "luna"]
BOOTSTRAP_B = 2000


def independent_observations(df: pd.DataFrame) -> pd.DataFrame:
    """Keep one terminal record per retry chain for statistical analysis."""
    if df.empty or "run_id" not in df.columns or "retry_of" not in df.columns:
        return df.copy()
    rows = df.copy()
    by_id = {str(r["run_id"]): r for _, r in rows.iterrows()}

    def root_id(row: pd.Series) -> str:
        current = str(row["run_id"])
        parent = row.get("retry_of")
        seen = {current}
        while pd.notna(parent) and str(parent) in by_id and str(parent) not in seen:
            current = str(parent)
            seen.add(current)
            parent = by_id[current].get("retry_of")
        return current

    rows["_retry_root"] = rows.apply(root_id, axis=1)
    rows["_raw_order"] = range(len(rows))
    rows = rows.sort_values("_raw_order").drop_duplicates("_retry_root", keep="last")
    return rows.drop(columns=["_retry_root", "_raw_order"])


def _resolved_long(df: pd.DataFrame) -> pd.DataFrame:
    df = independent_observations(df)
    if df.empty or "resolved" not in df.columns:
        return pd.DataFrame(columns=["task_id", "replicate", "model", "resolved"])
    d = df.dropna(subset=["resolved"]).copy()
    d["resolved"] = d["resolved"].astype(bool)
    return d


def paired_table(df: pd.DataFrame) -> pd.DataFrame:
    """One row per task x replicate: sol/luna resolved + category."""
    d = _resolved_long(df)
    if d.empty:
        return pd.DataFrame(columns=["task_id", "replicate", "sol", "luna", "category"])
    piv = d.pivot_table(index=["task_id", "replicate"], columns="model",
                        values="resolved", aggfunc="max")
    for m in MODELS:
        if m not in piv.columns:
            piv[m] = pd.NA
    piv = piv.dropna(subset=MODELS).astype({m: bool for m in MODELS}).reset_index()

    def cat(r):
        s, luna = bool(r.get("sol")), bool(r.get("luna"))
        if s and luna:
            return "both solved"
        if s:
            return "only Sol"
        if luna:
            return "only Luna"
        return "neither"
    piv["category"] = piv.apply(cat, axis=1)
    return piv[["task_id", "replicate", "sol", "luna", "category"]]


def task_aggregate(df: pd.DataFrame) -> pd.DataFrame:
    """Per task: Sol k/2, Luna k/2 + stability labels."""
    pt = paired_table(df)
    if pt.empty:
        return pd.DataFrame()
    g = pt.groupby("task_id").agg(sol_solved=("sol", "sum"), luna_solved=("luna", "sum"),
                                  n=("sol", "size")).reset_index()

    def stab(k):
        return "stable success" if k == 2 else ("unstable" if k == 1 else "stable failure")
    g["sol_stability"] = g["sol_solved"].apply(stab)
    g["luna_stability"] = g["luna_solved"].apply(stab)
    return g


def summary_table(df: pd.DataFrame, bootstrap_b: int = BOOTSTRAP_B,
                  seed: int = 20260920) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=["model", "n_tasks", "n_runs", "resolved_rate",
                                     "diff_pp_vs_other", "ci_low", "ci_high"])
    d = _resolved_long(df)
    base = d.groupby(["task_id", "model"])["resolved"].max().unstack()
    for m in MODELS:
        if m not in base.columns:
            base[m] = pd.NA
    base = base.dropna(subset=MODELS)
    if base.empty:
        return pd.DataFrame(columns=["model", "n_tasks", "n_runs", "resolved_rate",
                                     "diff_pp_vs_other", "ci_low", "ci_high"])
    tasks = sorted(base.index)
    d = d[d["task_id"].isin(tasks)]
    rng = np.random.default_rng(seed)
    rows = []
    for m in MODELS:
        vals = base[m].fillna(False).astype(float)
        rate = float(vals.mean())
        boots = [float(vals.loc[rng.choice(tasks, size=len(tasks), replace=True)].mean())
                 for _ in range(bootstrap_b)]
        rows.append({"model": m, "n_tasks": len(tasks),
                     "n_runs": int((d["model"] == m).sum()),
                     "resolved_rate": rate,
                     "ci_low": float(np.percentile(boots, 2.5)),
                     "ci_high": float(np.percentile(boots, 97.5))})
    s = pd.DataFrame(rows)
    diff = s.set_index("model")["resolved_rate"]
    s["diff_pp_vs_other"] = s["model"].map(
        lambda m: (diff[m] - diff["luna" if m == "sol" else "sol"]) * 100)
    # paired bootstrap on the per-task DIFFERENCE (luna - sol), task-level max over replicates
    per_task_diff = (base["luna"].fillna(False).astype(float)
                     - base["sol"].fillna(False).astype(float)).loc[tasks]
    mean_diff = float(per_task_diff.mean())
    bdiff = [float(per_task_diff.loc[rng.choice(tasks, size=len(tasks), replace=True)].mean())
             for _ in range(bootstrap_b)]
    s.attrs["paired_diff_pp"] = mean_diff * 100
    s.attrs["paired_diff_ci"] = (float(np.percentile(bdiff, 2.5)) * 100,
                                 float(np.percentile(bdiff, 97.5)) * 100)
    # McNemar on replicate pairs (sol vs luna discordant cells)
    pt = paired_table(d)
    b = int(((pt["sol"]) & (~pt["luna"])).sum())   # sol only
    c = int(((~pt["sol"]) & (pt["luna"])).sum())   # luna only
    s.attrs["mcnemar"] = {"sol_only_pairs": b, "luna_only_pairs": c,
                          "note": "discordant replicate-pairs; exact test in analysis notebook"}
    return s


def medians_table(df: pd.DataFrame) -> pd.DataFrame:
    df = independent_observations(df)
    if df.empty:
        return pd.DataFrame()
    num = ["duration_s", "input_tokens", "output_tokens", "total_tokens",
           "tool_calls", "lines_added", "actual_cost_usd", "normalized_api_cost_usd"]
    rows = []
    for m in MODELS:
        sub = df[df["model"] == m]
        r: dict = {"model": m, "n": int(len(sub))}
        for col in num:
            vals = sub[col].dropna() if col in sub else pd.Series(dtype=float)
            r[f"median_{col}"] = float(vals.median()) if len(vals) else None
            r[f"q1_{col}"] = float(vals.quantile(0.25)) if len(vals) else None
            r[f"q3_{col}"] = float(vals.quantile(0.75)) if len(vals) else None
        for cost_col, out_col in (("actual_cost_usd", "actual"), ("normalized_api_cost_usd", "normalized")):
            values = sub[cost_col].dropna() if cost_col in sub else pd.Series(dtype=float)
            tot = float(values.sum()) if len(values) else None
            nres = int((sub["resolved"] == True).sum()) if "resolved" in sub else 0
            r[f"total_{out_col}_cost"] = tot
            r[f"n_resolved"] = nres
            r[f"cost_per_resolved_{out_col}"] = (tot / nres) if nres and tot is not None else None
        rows.append(r)
    return pd.DataFrame(rows)


def incremental_cost(df: pd.DataFrame) -> dict:
    """Luna-vs-Sol incremental economics. Guards zero/negative denominators."""
    med = medians_table(df)
    if med.empty:
        return {"status": "no-data"}
    out: dict = {"status": "ok"}
    for cost_col in ("actual", "normalized"):
        s = med.set_index("model")
        try:
            y_raw = s.loc["luna", f"total_{cost_col}_cost"]
            x_raw = s.loc["sol", f"total_{cost_col}_cost"]
            nr_y = int(s.loc["luna", "n_resolved"])
            nr_x = int(s.loc["sol", "n_resolved"])
        except KeyError:
            out[cost_col] = {"status": "missing-model-rows"}
            continue
        if pd.isna(y_raw) or pd.isna(x_raw):
            out[cost_col] = {"status": "unknown-cost",
                             "note": "cost ratio not computed because comparable pricing is unavailable"}
            continue
        y, x = float(y_raw), float(x_raw)
        d_cost, d_res = y - x, nr_y - nr_x
        if d_res <= 0:
            out[cost_col] = {"status": "luna_resolves_no_more",
                             "incremental_cost": d_cost, "incremental_resolved": d_res,
                             "note": "no additional resolved tasks: ratio undefined, not computed"}
        else:
            out[cost_col] = {"status": "ok", "incremental_cost": d_cost,
                             "incremental_resolved": d_res,
                             "cost_per_additional_resolved": d_cost / d_res}
    return out
