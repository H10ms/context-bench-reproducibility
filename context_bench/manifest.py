"""Deterministic randomized manifest (schema v2: tasks x models x replicates).

No conditions. Order is shuffled with the fixed experiment seed so Sol/Luna
runs and replicates of one task are interleaved (no model blocks, no adjacent
replicates where avoidable by shuffling). Frozen after creation: `manifest
--verify` checks hash + shape instead of regenerating.
"""
from __future__ import annotations

import hashlib
import json
import random
from pathlib import Path


def plan_runs(tasks: list[str], model_keys: list[str], replicates: int) -> list[dict]:
    runs: list[dict] = []
    for task in tasks:
        for model in model_keys:
            for rep in range(1, replicates + 1):
                runs.append({
                    "task_id": task,
                    "repository": task.split("__")[0],
                    "model": model,
                    "replicate": rep,
                })
    return runs


def run_id_for(task_id: str, model: str, replicate: int, seed: int,
               retry_of: str | None = None, *, experiment_id: str = "",
               phase: str = "", model_id: str = "") -> str:
    base = f"{experiment_id}|{phase}|{seed}|{task_id}|{model}|{model_id}|{replicate}"
    if retry_of:
        base += f"|retry_of={retry_of}"
    h = hashlib.sha256(base.encode()).hexdigest()[:12]
    return f"{task_id}--{model}--r{replicate}--{h}"


def build_manifest(tasks: list[str], model_keys: list[str], replicates: int, seed: int,
                   *, experiment_id: str = "", phase: str = "full",
                   model_ids: dict[str, str] | None = None) -> list[dict]:
    planned = plan_runs(tasks, model_keys, replicates)
    rng = random.Random(seed)
    rng.shuffle(planned)  # deterministic randomized order; frozen after creation
    manifest = []
    for i, p in enumerate(planned):
        manifest.append({
            "seq": i,
            **p,
            "run_id": run_id_for(p["task_id"], p["model"], p["replicate"], seed,
                                 experiment_id=experiment_id, phase=phase,
                                 model_id=(model_ids or {}).get(p["model"], "")),
            "seed": seed,
            "experiment_id": experiment_id,
            "phase": phase,
        })
    return manifest


def manifest_hash(manifest: list[dict]) -> str:
    h = hashlib.sha256()
    for row in manifest:
        h.update((json.dumps(row, sort_keys=True) + "\n").encode())
    return h.hexdigest()


def write_manifest(manifest: list[dict], path: Path) -> None:
    with open(path, "w", encoding="utf-8") as f:
        for row in manifest:
            f.write(json.dumps(row) + "\n")


def read_manifest(path: Path) -> list[dict]:
    rows = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def verify_manifest(manifest: list[dict], tasks: list[str], model_keys: list[str],
                    replicates: int, seed: int, *, experiment_id: str = "",
                    phase: str = "full", model_ids: dict[str, str] | None = None) -> list[str]:
    """Shape + determinism + interleaving checks. Returns list of problems."""
    problems: list[str] = []
    want = len(tasks) * len(model_keys) * replicates
    if len(manifest) != want:
        problems.append(f"expected {want} runs, got {len(manifest)}")
    rebuilt = build_manifest(tasks, model_keys, replicates, seed,
                             experiment_id=experiment_id, phase=phase, model_ids=model_ids)
    if [r["run_id"] for r in rebuilt] != [r.get("run_id") for r in manifest]:
        problems.append("manifest differs from deterministic rebuild (order/ids changed)")
    ids = [r.get("run_id") for r in manifest]
    if len(set(ids)) != len(ids):
        problems.append("duplicate run_ids")
    # interleaving: no long single-model prefix, replicates of one task adjacent rarely
    models = [r.get("model") for r in manifest]
    if models and (all(m == models[0] for m in models[:10]) and len(models) >= 10):
        problems.append("first 10 runs are all one model (not interleaved)")
    adj = sum(1 for a, b in zip(manifest, manifest[1:])
              if a.get("task_id") == b.get("task_id") and a.get("model") == b.get("model"))
    if adj > len(manifest) * 0.2:
        problems.append(f"too many adjacent same-task/same-model pairs: {adj}")
    return problems


def pilot_tasks(all_tasks: list[str]) -> list[str]:
    """Deterministic: first sorted task per repo (recorded in EXPERIMENT_FREEZE / pilot meta)."""
    by_repo: dict[str, list[str]] = {}
    for t in all_tasks:
        by_repo.setdefault(t.split("__")[0], []).append(t)
    return [sorted(by_repo[r])[0] for r in sorted(by_repo)]
