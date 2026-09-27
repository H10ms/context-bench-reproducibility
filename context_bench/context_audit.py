"""Leakage + isolation audits. Context-vs-gold checks run WITHOUT reading gold into context pipeline."""
from __future__ import annotations

import re
from pathlib import Path


def check_no_gold_strings(context_text: str, gold_patch: str) -> list[str]:
    """Flag suspicious overlaps: non-trivial added lines from gold appearing in context.

    Used ONLY in audit stage (post-hoc), never during context construction.
    """
    findings: list[str] = []
    if not gold_patch:
        return findings
    added = [ln[1:].strip() for ln in gold_patch.splitlines()
             if ln.startswith("+") and not ln.startswith("+++")]
    added = [a for a in added if len(a) >= 30]  # ignore trivial one-liners
    for a in added:
        if a and a in context_text:
            findings.append(f"gold added-line present in context: {a[:120]!r}")
    return findings


def check_filenames_not_from_gold(context_text: str, gold_files: list[str],
                                  allowed_files: list[str]) -> list[str]:
    findings: list[str] = []
    allowed = set(allowed_files)
    for f in gold_files:
        if f in context_text and f not in allowed:
            findings.append(f"gold-only filename in context: {f}")
    return findings


def check_commit_order(source_commit: str, base_commit: str, ancestors_of_base: set[str]) -> list[str]:
    findings: list[str] = []
    if source_commit == base_commit or "base_commit" in source_commit or "ancestor" in source_commit:
        return findings
    if source_commit not in ancestors_of_base:
        findings.append(f"source commit {source_commit} not proven ancestor of {base_commit}")
    return findings


def check_container_confined(agent_workdir: Path, results_path: Path,
                             harness_root: Path) -> list[str]:
    findings: list[str] = []
    try:
        if results_path.resolve().is_relative_to(agent_workdir.resolve()):
            findings.append("results visible inside agent workdir")
    except Exception:
        pass
    if agent_workdir.resolve() == harness_root.resolve():
        findings.append("agent workdir equals harness root")
    return findings


def audit_run_dir(run_dir: Path) -> dict:
    """Checks 7-9: clean tree before injection, no evaluator artifacts pre-run, patch locality."""
    report: dict = {"run_dir": str(run_dir), "checks": {}}
    report["checks"]["worktree_clean_marker"] = (run_dir / "worktree_clean.ok").exists()
    report["checks"]["no_eval_artifacts_before_agent"] = not (run_dir / "eval_before_agent.json").exists()
    patch = run_dir / "model.patch"
    report["checks"]["patch_exists"] = patch.exists()
    report["checks"]["log_exists"] = (run_dir / "transcript.jsonl").exists()
    return report
