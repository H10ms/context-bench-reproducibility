"""Analysis entrypoint (schema v2): raw.jsonl -> CSVs + paired stats + 15 plots + case bundles.

Never invents data. Interesting-pair selection (A-F) is rule-based on measured
outcomes only; bundles contain raw artifacts for MANUAL review — no
LLM-generated verdicts.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import pandas as pd

from .statistics import (incremental_cost, medians_table, paired_table,
                         summary_table, task_aggregate)
from .plots import all_plots


def load_results(raw_path: Path) -> pd.DataFrame:
    if not raw_path.exists():
        return pd.DataFrame()
    rows = [json.loads(ln) for ln in raw_path.read_text(encoding="utf-8").splitlines()
            if ln.strip()]
    rows = [r for r in rows if r.get("schema_version", 1) == 2]
    return pd.DataFrame(rows)


def _interesting(agg: pd.DataFrame, df: pd.DataFrame) -> dict[str, list[str]]:
    if agg.empty:
        return {}
    groups: dict[str, list[str]] = {"A_luna2_sol0": [], "B_sol2_luna0": [], "C_both2": [],
                                    "D": [], "E_unstable": [], "F_neither": []}
    for _, r in agg.iterrows():
        t = r["task_id"]
        s, luna = int(r["sol_solved"]), int(r["luna_solved"])
        if luna == 2 and s == 0:
            groups["A_luna2_sol0"].append(t)
        if s == 2 and luna == 0:
            groups["B_sol2_luna0"].append(t)
        if s == 2 and luna == 2:
            groups["C_both2"].append(t)
        if s == 1 or luna == 1:
            groups["E_unstable"].append(t)
        if s == 0 and luna == 0:
            groups["F_neither"].append(t)
    # D: both solved (>=1) with big cost/patch gaps
    for t in df["task_id"].unique():
        sub = df[df["task_id"] == t]
        if sub[sub["model"] == "sol"]["resolved"].any() and sub[sub["model"] == "luna"]["resolved"].any():
            for col in ("normalized_api_cost_usd", "actual_cost_usd", "lines_added"):
                if col in sub:
                    numeric = pd.to_numeric(sub[col], errors="coerce")
                    v = numeric.groupby(sub["model"]).median().dropna()
                    if len(v) == 2 and v.max() and v.min() and v.max() / max(v.min(), 1e-9) >= 3:
                        groups["D"].append(t)
                        break
    groups["D"] = sorted(set(groups["D"]))
    return groups


def _bundle(task_id: str, df: pd.DataFrame, root: Path, cases_dir: Path) -> None:
    d = cases_dir / task_id
    if d.exists():
        shutil.rmtree(d)
    (d / "sol").mkdir(parents=True)
    (d / "luna").mkdir(parents=True)
    comp = {"task_id": task_id, "models": {}}
    for m in ("sol", "luna"):
        sub = df[(df["task_id"] == task_id) & (df["model"] == m)].sort_values("replicate")
        comp["models"][m] = []
        for _, r in sub.iterrows():
            entry = {"replicate": int(r.get("replicate", 0)), "resolved": bool(r.get("resolved", False)),
                     "error_category": r.get("error_category"),
                     "actual_cost_usd": r.get("actual_cost_usd"),
                     "normalized_api_cost_usd": r.get("normalized_api_cost_usd"),
                     "duration_s": r.get("duration_s"),
                     "input_tokens": r.get("input_tokens"), "output_tokens": r.get("output_tokens"),
                     "reasoning_tokens": r.get("reasoning_tokens"),
                     "tool_calls": r.get("tool_calls"),
                     "lines_added": r.get("lines_added"), "lines_deleted": r.get("lines_deleted")}
            for key in ("transcript_path", "patch_path", "evaluator_log_path"):
                src = r.get(key)
                if src and Path(str(src)).exists():
                    dst = d / m / f"r{entry['replicate']}_{Path(str(src)).name}"
                    shutil.copy2(src, dst)
                    entry[key] = str(dst.relative_to(root))
                else:
                    entry[key] = None
            comp["models"][m].append(entry)
    (d / "comparison.json").write_text(json.dumps(comp, indent=2), encoding="utf-8")


def run_analysis(root: Path, scope: str = "full", experiment: dict | None = None,
                 models: dict[str, str | None] | None = None) -> dict:
    if experiment is None:
        raise ValueError("active experiment configuration is required")
    raw_keys = {"smoke": "results_smoke_raw", "pilot": "results_pilot_raw",
                "full": "results_raw"}
    raw = root / experiment[raw_keys[scope]]
    proc = raw.parent / "processed"
    proc.mkdir(parents=True, exist_ok=True)
    figs = raw.parent / "figures"
    df = load_results(raw)
    if not df.empty:
        required = {"experiment_id", "phase", "model", "opencode_model_id"}
        missing = required - set(df.columns)
        if missing:
            raise ValueError(f"raw results lack experiment isolation fields: {sorted(missing)}")
        expected_id = experiment["experiment_id"]
        bad_identity = df[df["experiment_id"] != expected_id]
        bad_phase = df[df["phase"] != scope]
        expected_models = models or {}
        bad_models = df[df.apply(
            lambda r: expected_models.get(r.get("model")) != r.get("opencode_model_id"), axis=1)]
        if not bad_identity.empty or not bad_phase.empty or not bad_models.empty:
            raise ValueError("raw results contain records outside the active experiment/phase/model mapping")
    summary = summary_table(df)
    med = medians_table(df)
    paired = paired_table(df)
    agg = task_aggregate(df)
    incr = incremental_cost(df)
    summary.to_csv(proc / "summary.csv", index=False)
    med.to_csv(proc / "medians.csv", index=False)
    paired.to_csv(proc / "paired.csv", index=False)
    agg.to_csv(proc / "per_task.csv", index=False)
    (proc / "incremental_cost.json").write_text(json.dumps(incr, indent=2,
        default=str), encoding="utf-8")
    (proc / "mcnemar.json").write_text(json.dumps(getattr(summary, "attrs", {}).get(
        "mcnemar", {}), indent=2), encoding="utf-8")
    if not df.empty:
        df.to_csv(proc / "all_runs.csv", index=False)
    all_plots(df, summary, med, paired, agg, figs)
    # case bundles for manual review
    cases_dir = root / "analysis" / "cases" / experiment["experiment_id"] / scope
    interesting = _interesting(agg, df)
    (proc / "interesting_tasks.json").write_text(json.dumps(interesting, indent=2),
                                                 encoding="utf-8")
    for tids in interesting.values():
        for t in tids:
            _bundle(t, df, root, cases_dir)
    return {"experiment_id": experiment["experiment_id"], "scope": scope, "n_runs": len(df),
            "paired_diff_pp": getattr(summary, "attrs", {}).get("paired_diff_pp"),
            "paired_diff_ci": getattr(summary, "attrs", {}).get("paired_diff_ci"),
            "incremental": incr,
            "figures": str(figs)}
