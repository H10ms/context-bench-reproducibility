"""15 figures for the GPT-6 Sol-vs-Luna experiment. Real data only."""
from __future__ import annotations

from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

MODELS = ["sol", "luna"]
NAMES = ["01_resolved_rate", "02_cost_per_resolved", "03_median_cost_per_run",
         "04_median_walltime", "05_token_usage", "06_tool_calls", "07_patch_size",
         "08_stability", "09_per_task_heatmap", "10_paired_outcomes",
         "11_cost_vs_success", "12_duration_vs_success", "13_repo_resolved",
         "14_failure_categories", "15_cumulative_spend"]


def _save(fig, path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)


def _nodata(out: Path):
    for name in NAMES:
        fig, ax = plt.subplots(figsize=(8, 3))
        ax.text(0.5, 0.5, "no data yet — run pilot/full first", ha="center")
        ax.set_title(name)
        ax.axis("off")
        _save(fig, out / f"{name}.png")


def all_plots(df: pd.DataFrame, summary: pd.DataFrame, medians: pd.DataFrame,
              paired: pd.DataFrame, taskagg: pd.DataFrame, out: Path):
    out.mkdir(parents=True, exist_ok=True)
    if df.empty or summary.empty:
        _nodata(out)
        return
    cost_col = "normalized_api_cost_usd" if df["normalized_api_cost_usd"].notna().any() \
        else "actual_cost_usd"
    outcomes = df.dropna(subset=["resolved"]).copy()
    outcomes["resolved"] = outcomes["resolved"].astype(bool)

    fig, ax = plt.subplots(figsize=(6, 4))  # 1
    s = summary.set_index("model").reindex(MODELS)
    ax.bar(MODELS, s["resolved_rate"], yerr=[s["resolved_rate"] - s["ci_low"],
                                             s["ci_high"] - s["resolved_rate"]], capsize=4)
    ax.set_title("Resolved rate GPT-6 Sol vs Luna (bootstrap 95% CI over tasks)")
    _save(fig, out / "01_resolved_rate.png")

    fig, ax = plt.subplots(figsize=(6, 4))  # 2
    m = medians.set_index("model").reindex(MODELS)
    normalized = [m.loc[x, "cost_per_resolved_normalized"] for x in MODELS]
    ax.bar(MODELS, [v if pd.notna(v) else float("nan") for v in normalized])
    ax.set_title("Cost per resolved task (normalized)")
    _save(fig, out / "02_cost_per_resolved.png")

    fig, ax = plt.subplots(figsize=(6, 4))  # 3
    ax.bar(MODELS, [m.loc[x, "median_actual_cost_usd"] for x in MODELS])
    ax.set_title("Median cost per run (actual)")
    _save(fig, out / "03_median_cost_per_run.png")

    fig, ax = plt.subplots(figsize=(6, 4))  # 4
    ax.bar(MODELS, [m.loc[x, "median_duration_s"] for x in MODELS])
    ax.set_title("Median wall-clock time (s)")
    _save(fig, out / "04_median_walltime.png")

    fig, ax = plt.subplots(figsize=(7, 4))  # 5
    x = range(len(MODELS))
    ax.bar([i - 0.2 for i in x], [m.loc[mo, "median_input_tokens"] for mo in MODELS],
           width=0.4, label="input")
    ax.bar([i + 0.2 for i in x], [m.loc[mo, "median_output_tokens"] for mo in MODELS],
           width=0.4, label="output")
    ax.set_xticks(list(x), MODELS)
    ax.legend()
    ax.set_title("Median input/output tokens")
    _save(fig, out / "05_token_usage.png")

    fig, ax = plt.subplots(figsize=(6, 4))  # 6
    ax.bar(MODELS, [m.loc[x, "median_tool_calls"] for x in MODELS])
    ax.set_title("Median tool calls")
    _save(fig, out / "06_tool_calls.png")

    fig, ax = plt.subplots(figsize=(7, 4))  # 7
    outcomes.boxplot(column="lines_added", by="model", ax=ax)
    ax.set_title("Patch size (lines added)")
    _save(fig, out / "07_patch_size.png")

    fig, ax = plt.subplots(figsize=(7, 4))  # 8
    if not taskagg.empty:
        stab = pd.DataFrame({
            "sol": taskagg["sol_stability"].value_counts(),
            "luna": taskagg["luna_stability"].value_counts()}).fillna(0)
        stab.plot(kind="bar", ax=ax)
        ax.set_title("Stability: tasks solved 0/2, 1/2, 2/2")
    _save(fig, out / "08_stability.png")

    fig, ax = plt.subplots(figsize=(8, max(4, outcomes["task_id"].nunique() * 0.3)))  # 9
    piv = outcomes.pivot_table(index="task_id", columns="model", values="resolved",
                          aggfunc="max").reindex(columns=MODELS)
    ax.imshow(piv.astype(float).values, aspect="auto")
    ax.set_xticks(range(len(MODELS)), MODELS)
    ax.set_yticks(range(len(piv.index)), piv.index)
    ax.set_title("Per-task resolved (best over replicates)")
    _save(fig, out / "09_per_task_heatmap.png")

    fig, ax = plt.subplots(figsize=(7, 4))  # 10
    if not paired.empty:
        paired["category"].value_counts().plot(kind="bar", ax=ax)
        ax.set_title("Paired outcomes per task x replicate")
    _save(fig, out / "10_paired_outcomes.png")

    fig, ax = plt.subplots(figsize=(7, 4))  # 11
    for mo in MODELS:
        sub = outcomes[outcomes["model"] == mo]
        ax.scatter(sub[cost_col], sub["resolved"].astype(int), label=mo, alpha=0.6)
    ax.legend()
    ax.set_title("Cost vs success")
    _save(fig, out / "11_cost_vs_success.png")

    fig, ax = plt.subplots(figsize=(7, 4))  # 12
    for mo in MODELS:
        sub = outcomes[outcomes["model"] == mo]
        ax.scatter(sub["duration_s"], sub["resolved"].astype(int), label=mo, alpha=0.6)
    ax.legend()
    ax.set_title("Duration vs success")
    _save(fig, out / "12_duration_vs_success.png")

    fig, ax = plt.subplots(figsize=(9, 4))  # 13
    rp = outcomes.groupby(["repository", "model"])["resolved"].mean().unstack().reindex(columns=MODELS)
    rp.plot(kind="bar", ax=ax)
    ax.set_title("Repository-level resolved rate")
    _save(fig, out / "13_repo_resolved.png")

    fig, ax = plt.subplots(figsize=(8, 4))  # 14
    df["error_category"].value_counts().plot(kind="bar", ax=ax)
    ax.set_title("Failure categories")
    _save(fig, out / "14_failure_categories.png")

    fig, ax = plt.subplots(figsize=(8, 4))  # 15
    d = df.sort_values("timestamp")
    for mo in MODELS:
        sub = d[d["model"] == mo]
        ax.plot(range(len(sub)), sub[cost_col].fillna(0).cumsum(), label=mo)
    ax.legend()
    ax.set_title("Cumulative spend over runs")
    _save(fig, out / "15_cumulative_spend.png")
