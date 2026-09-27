"""Result schema v2 + error taxonomy. Raw logs are append-only, never overwritten.

v1 (context-pollution, condition-based) files MUST NOT be read as v2 runs:
every v2 record carries schema_version=2 and v2 run_ids contain no --C0..C4--
segment. v1 results live under archive/.
"""
from __future__ import annotations

from pathlib import Path
import json

SCHEMA_VERSION = 2

ERROR_CATEGORIES = (
    "successful",
    "unresolved",
    "timeout",
    "opencode_error",
    "provider_error",
    "rate_limit",
    "auth_error",
    "infrastructure_error",
    "docker_error",
    "benchmark_error",
    "evaluator_error",
    "invalid_patch",
)
INFRASTRUCTURE_CATEGORIES = {"timeout", "opencode_error", "provider_error",
                             "rate_limit", "auth_error", "infrastructure_error",
                             "docker_error", "benchmark_error", "evaluator_error"}

REQUIRED_FIELDS = (
    "schema_version", "run_id", "experiment_version", "experiment_id", "phase", "timestamp", "task_id",
    "repository", "base_commit", "model", "opencode_model_id",
    "reasoning", "replicate", "prompt_sha256",
    "docker_image", "duration_s", "exit_status", "resolved", "error_category",
)


def validate_result(rec: dict) -> list[str]:
    errs = [f"missing {f}" for f in REQUIRED_FIELDS if f not in rec]
    if rec.get("schema_version") != SCHEMA_VERSION:
        errs.append(f"schema_version must be {SCHEMA_VERSION}, got {rec.get('schema_version')}")
    if rec.get("error_category") not in ERROR_CATEGORIES:
        errs.append(f"bad error_category: {rec.get('error_category')}")
    if rec.get("resolved") not in (True, False, None):
        errs.append("resolved must be true/false/null")
    return errs


def append_raw(rec: dict, raw_path: Path) -> None:
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    with open(raw_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec) + "\n")


def read_all(raw_path: Path) -> list[dict]:
    if not raw_path.exists():
        return []
    rows = [json.loads(ln) for ln in raw_path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    return [r for r in rows if r.get("schema_version", 1) == SCHEMA_VERSION]


def classify(exit_code: int, timed_out: bool, resolved: bool | None,
             stderr_tail: str) -> str:
    if timed_out or exit_code == 124:
        return "timeout"
    low = (stderr_tail or "").lower()
    if "rate limit" in low or "429" in low or "rate_limit" in low:
        return "rate_limit"
    if "unauthorized" in low or "401" in low or "403" in low or "auth" in low and "error" in low:
        return "auth_error"
    if "opencode executable not found" in low or "unknownerror" in low or "unexpected server error" in low:
        return "opencode_error"
    if "api error" in low or "provider" in low and "error" in low or "500" in low or "502" in low or "503" in low:
        return "provider_error"
    if "docker" in low and "error" in low:
        return "docker_error"
    if exit_code != 0 and resolved is None:
        return "infrastructure_error"
    if resolved is True:
        return "successful"
    if resolved is False:
        return "unresolved"
    return "unresolved"
