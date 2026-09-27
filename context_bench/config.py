"""Configuration loading + validation (no secrets ever read from disk). Schema v2."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parent.parent
EXPECTED_REPOS = {"django": 5, "matplotlib": 5, "scikit-learn": 5,
                  "sympy": 5, "pydata": 5, "sphinx-doc": 5}


def load_yaml(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def load_all(root: Path | None = None) -> dict[str, Any]:
    root = root or ROOT
    exp = load_yaml(root / "config" / "experiment.yaml")
    tasks = load_yaml(root / "config" / "tasks.yaml")
    models = load_yaml(root / "config" / "models.yaml")
    pricing_path = root / exp.get("pricing_config", "config/pricing.yaml")
    pricing = load_yaml(pricing_path) if pricing_path.exists() else {}
    return {"experiment": exp, "tasks": tasks, "models": models, "pricing": pricing, "root": root}


def validate_config(cfg: dict) -> list[str]:
    errors: list[str] = []
    exp = cfg.get("experiment", {})
    tasks = cfg.get("tasks", {}).get("tasks", [])
    reserves = cfg.get("tasks", {}).get("reserve_tasks", [])
    models = cfg.get("models", {}).get("models", [])
    if exp.get("schema_version") != 2:
        errors.append(f"schema_version must be 2, got {exp.get('schema_version')}")
    if exp.get("experiment_seed") != 20260920:
        errors.append(f"experiment_seed must be 20260920, got {exp.get('experiment_seed')}")
    if exp.get("replicates") != 2:
        errors.append("replicates must be 2")
    if "conditions" in exp:
        errors.append("v2 experiment must not define conditions (C0-C4 retired)")
    if len(tasks) != 30:
        errors.append(f"expected 30 tasks, got {len(tasks)}")
    if len(set(tasks)) != len(tasks):
        errors.append("task list contains duplicates")
    if len(reserves) < 18:
        errors.append(f"expected >=18 reserve tasks, got {len(reserves)}")
    for repo, n in EXPECTED_REPOS.items():
        got = sum(1 for t in tasks if t.split("__")[0] == repo)
        if got != n:
            errors.append(f"repo {repo}: expected {n} tasks, got {got}")
        got_r = sum(1 for t in reserves if t.split("__")[0] == repo)
        if got_r < 3:
            errors.append(f"repo {repo}: expected >=3 reserves, got {got_r}")
    if set(tasks) & set(reserves):
        errors.append("main and reserve task sets overlap")
    if len(models) != 2:
        errors.append(f"expected 2 models, got {len(models)}")
    names = {m.get("logical_name") for m in models}
    if names != {"sol", "luna"}:
        errors.append(f"models.yaml must define sol + luna, got {names}")
    ids = {m.get("opencode_model_id") for m in models}
    if ids != {"openai/gpt-6-sol", "openai/gpt-6-luna"}:
        errors.append(f"active model IDs must be non-fast GPT-6 Sol + Luna, got {ids}")
    if any(str(mid).endswith("-fast") for mid in ids):
        errors.append("fast model variants are forbidden")
    if not exp.get("experiment_id"):
        errors.append("experiment_id is required")
    variants = {m.get("reasoning_effort") for m in models}
    if len(variants) != 1:
        errors.append(f"reasoning_effort must be identical for both models, got {variants}")
    to = exp.get("agent_timeout_seconds")
    if not isinstance(to, int) or to <= 0:
        errors.append("agent_timeout_seconds must be a positive int")
    return errors
