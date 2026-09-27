"""EXPERIMENT_FREEZE machinery: capture all inputs before full; enforce on launch.

Freeze records: harness git SHA (+dirty diff), OpenCode version, swebench
version, 30 tasks, manifest hash, models (logical + exact OpenCode IDs),
reasoning, timeout, prompt-wrapper SHA, config hashes, pricing snapshot,
environment metadata, timestamp.
"""
from __future__ import annotations

import hashlib
import json
import platform
import subprocess
import sys
from pathlib import Path

from .manifest import manifest_hash
from .runner import PROMPT_WRAPPER
from .utils import sha256_text


def _run(cmd: list[str], cwd: Path, timeout: int = 15) -> str:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                           cwd=str(cwd))
        return (p.stdout or "").strip()
    except Exception:
        return ""


def file_sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def harness_git(root: Path) -> dict:
    sha = _run(["git", "rev-parse", "HEAD"], root)
    status = _run(["git", "status", "--short"], root)
    dirty = [l for l in status.splitlines() if l.strip()]
    return {"sha": sha or None, "dirty": bool(dirty), "dirty_count": len(dirty)}


def collect_freeze(cfg: dict, manifest: list[dict], opencode_version: str,
                   swebench_version: str | None, models_snapshot: list[dict]) -> dict:
    root: Path = cfg["root"]
    exp = cfg["experiment"]
    git = harness_git(root)
    config_files = ["config/experiment.yaml", "config/models.yaml",
                    "config/tasks.yaml", "config/pricing.yaml"]
    freeze = {
        "experiment_name": exp.get("experiment_name"),
        "experiment_version": exp.get("experiment_version"),
        "schema_version": exp.get("schema_version"),
        "seed": exp.get("experiment_seed"),
        "harness_git_sha": git["sha"],
        "harness_dirty_at_freeze": git["dirty"],
        "opencode_version": opencode_version,
        "swebench_version": swebench_version,
        "tasks": list(cfg["tasks"]["tasks"]),
        "manifest_hash": manifest_hash(manifest),
        "manifest_runs": len(manifest),
        "models": models_snapshot,
        "reasoning": exp.get("reasoning_effort"),
        "opencode_agent": (exp.get("opencode") or {}).get("agent"),
        "opencode_variant": (exp.get("opencode") or {}).get("variant"),
        "timeout_s": exp.get("agent_timeout_seconds"),
        "prompt_wrapper_sha256": sha256_text(PROMPT_WRAPPER),
        "config_hashes": {f: file_sha(root / f) for f in config_files
                          if (root / f).exists()},
        "pricing_snapshot": cfg.get("pricing"),
        "environment": {"python": sys.version.split()[0], "platform": platform.platform()},
        "frozen_at": __import__("datetime").datetime.now(
            __import__("datetime").timezone.utc).isoformat(),
    }
    return freeze


def check_freeze(cfg: dict, manifest: list[dict], opencode_version: str,
                 freeze: dict) -> list[str]:
    """Recompute volatile inputs; return list of mismatches (empty = match)."""
    problems: list[str] = []
    if freeze.get("manifest_hash") != manifest_hash(manifest):
        problems.append("manifest hash differs from freeze")
    if freeze.get("tasks") != list(cfg["tasks"]["tasks"]):
        problems.append("task list differs from freeze")
    if freeze.get("opencode_version") != opencode_version:
        problems.append(f"opencode version {opencode_version} != frozen {freeze.get('opencode_version')}")
    if freeze.get("prompt_wrapper_sha256") != sha256_text(PROMPT_WRAPPER):
        problems.append("prompt wrapper changed since freeze")
    root: Path = cfg["root"]
    for f, h in (freeze.get("config_hashes") or {}).items():
        if not (root / f).exists():
            problems.append(f"config file missing: {f}")
        elif file_sha(root / f) != h:
            problems.append(f"config file changed: {f}")
    exp = cfg["experiment"]
    if freeze.get("timeout_s") != exp.get("agent_timeout_seconds"):
        problems.append("timeout changed since freeze")
    if freeze.get("reasoning") != exp.get("reasoning_effort"):
        problems.append("reasoning setting changed since freeze")
    return problems
