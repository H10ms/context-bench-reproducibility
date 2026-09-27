"""SWE-bench Verified access layer.

GOLD-PATCH SEPARATION (critical):
- This module exposes TWO strict access modes.
- Context-building code may ONLY call `load_for_context()` which strips
  gold patch / test patch / oracle fields BEFORE returning.
- `load_with_gold()` exists solely for the post-run evaluator / sanity checks
  and must never be imported by any agent-prompt construction code
  (enforced by unit test `test_no_gold_in_prompt_path`).
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
import json

GOLD_FIELDS = ("patch", "test_patch")
FORBIDDEN_CONTEXT_FIELDS = ("patch", "test_patch", "gold", "solution", "oracle", "fail_to_pass")


def _load_parquet_row(instance_id: str) -> dict | None:
    """Offline fallback: read the cached Hub parquet directly (no Hub round-trip).

    Used when the Hub is flaky (observed 2026-09-20: intermittent
    DatasetNotFoundError despite warm cache). Only agent-visible fields are
    returned; gold columns are dropped before return, same as load_for_context.
    """
    hub = Path.home() / ".cache" / "huggingface" / "hub"
    cands = sorted(hub.glob("datasets--SWE-bench--SWE-bench_Verified/snapshots/*/data/*.parquet"))
    if not cands:
        return None
    import pandas as pd

    df = pd.read_parquet(cands[0], columns=["instance_id", "repo", "base_commit",
                                            "problem_statement", "version",
                                            "image", "environment_setup_commit",
                                            "difficulty"])
    hit = df[df["instance_id"] == instance_id]
    if hit.empty:
        return None
    return hit.iloc[0].to_dict()


def _load_dataset(hf_id: str = "SWE-bench/SWE-bench_Verified"):
    from datasets import load_dataset  # lazy: keeps unit tests offline-capable

    ds = load_dataset(hf_id, split="test")
    return ds


@lru_cache(maxsize=1)
def _cached(hf_id: str = "SWE-bench/SWE-bench_Verified"):
    return _load_dataset(hf_id)


def load_for_context(instance_id: str, hf_id: str = "SWE-bench/SWE-bench_Verified") -> dict:
    """Return ONLY agent-visible fields: base_commit, problem_statement, repo, version, image..."""
    try:
        ds = _cached(hf_id)
        rows = ds.filter(lambda r: r["instance_id"] == instance_id)
        if len(rows) == 0:
            raise KeyError(f"task not found in {hf_id}: {instance_id}")
        r = dict(rows[0])
    except Exception:
        row = _load_parquet_row(instance_id)
        if row is None:
            raise KeyError(f"task not found in {hf_id}: {instance_id}")
        r = row
    for f in GOLD_FIELDS:
        r.pop(f, None)
    # Belt & braces: never leak eval test lists into context either
    r.pop("FAIL_TO_PASS", None)
    r.pop("PASS_TO_PASS", None)
    return r


def load_with_gold(instance_id: str, hf_id: str = "SWE-bench/SWE-bench_Verified") -> dict:
    """EVALUATOR ONLY. Returns full record incl. gold patch + test patch."""
    ds = _cached(hf_id)
    rows = ds.filter(lambda r: r["instance_id"] == instance_id)
    if len(rows) == 0:
        raise KeyError(f"task not found in {hf_id}: {instance_id}")
    return dict(rows[0])


def task_exists(instance_id: str, hf_id: str = "SWE-bench/SWE-bench_Verified") -> bool:
    try:
        load_for_context(instance_id, hf_id)
        return True
    except Exception:
        return False


def snapshot_metadata(cache_path: Path) -> dict:
    if cache_path.exists():
        return json.loads(cache_path.read_text(encoding="utf-8"))
    return {}
