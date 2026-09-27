"""Run orchestration on the shared OpenCode harness (schema v2).

Isolation contract (see docs/METHODOLOGY.md):
1. fetch task metadata (agent-visible fields only — never gold)
2. fresh run dir (no reuse; real results never overwritten, resume skips them)
3. worktree at exact base_commit, git status clean (materialized from the
   SWE-bench Docker image; marker file asserts the precondition)
4. byte-identical user prompt for both models (+ SHA256 recorded)
5. NO experimental instruction files injected (natural snapshot; pre-existing
   AGENTS.md/CLAUDE.md/README in the repo are left untouched)
6. `opencode run` with identical flags; only --model differs
7. provider connection allowed; repo shell/tools get no internet
   (container --network none; prompt forbids network)
8. capture --format json events -> usage/cost/tool counts/session id
9. git diff of THIS worktree only -> model.patch
10. evaluate SEPARATELY (gold allowed only there)
11. append to the experiment- and phase-scoped raw JSONL (never overwrite)
"""
from __future__ import annotations

import json
import shutil
import subprocess
import time
from pathlib import Path

from . import EXPERIMENT_VERSION
from .container import materialize_worktree, swebench_image_for_task
from .metrics import classify
from .opencode_harness import build_command, parse_events
from .utils import sanitize, sha256_text, utc_now_iso

SCHEMA_VERSION = 2

PROMPT_WRAPPER = """Implement the requested fix in this repository.

You may inspect and modify files and run relevant tests.

Make the smallest correct change needed to resolve the issue.

Avoid unrelated modifications.

Run relevant tests before finishing.

Do not use network access.

Issue:

{problem_statement}
"""


def build_prompt(problem_statement: str) -> str:
    return PROMPT_WRAPPER.format(problem_statement=problem_statement)


def _write_lf_text(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8", newline="")


def _normalized_cost(usage: dict, pricing_entry: dict) -> float | None:
    pin = pricing_entry.get("input_per_1m")
    pout = pricing_entry.get("output_per_1m")
    if pin is None or pout is None:
        return None
    if usage.get("input_tokens") is None or usage.get("output_tokens") is None:
        return None
    return (usage["input_tokens"] / 1e6) * pin + (usage["output_tokens"] / 1e6) * pout


def run_single(manifest_row: dict, task_meta: dict, models_cfg: dict, exp_cfg: dict,
               pricing: dict, root: Path, opencode_exe: str, opencode_version: str,
               dry_run: bool = False) -> dict:
    run_id = manifest_row["run_id"]
    runs_dir = root / exp_cfg["runs_dir"]
    run_dir = runs_dir / run_id
    existing = run_dir / "result.json"
    if existing.exists():
        try:
            prev = json.loads(existing.read_text(encoding="utf-8"))
        except Exception:
            prev = {}
        if prev.get("dry_run") is True:
            shutil.rmtree(run_dir, ignore_errors=True)
        else:
            raise RuntimeError(f"refusing to overwrite completed run {run_id} (resume skips it)")
    run_dir.mkdir(parents=True, exist_ok=True)
    workdir = run_dir / "worktree"
    workdir.mkdir(exist_ok=True)
    prompt = build_prompt(task_meta.get("problem_statement", ""))
    prompt_sha = sha256_text(prompt)
    prompt_file = run_dir / "prompt.md"
    _write_lf_text(prompt_file, prompt)

    logical = manifest_row["model"]  # 'sol' | 'luna'
    entry = next(m for m in models_cfg["models"] if m["logical_name"] == logical)
    model_id = entry.get("opencode_model_id") or ""
    timeout_s = int(exp_cfg.get("agent_timeout_seconds", 1800))
    oc = exp_cfg.get("opencode", {}) or {}
    variant = oc.get("variant") or entry.get("reasoning_effort") or "medium"
    agent = oc.get("agent", "build")
    docker_image = swebench_image_for_task(task_meta.get("image"))
    reasoning_cfg = {"variant": variant, "effort": entry.get("reasoning_effort"),
                     "mapping": entry.get("reasoning_mapping")}

    rec: dict = {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "experiment_version": EXPERIMENT_VERSION,
        "experiment_id": exp_cfg.get("experiment_id"),
        "phase": manifest_row.get("phase"),
        "timestamp": utc_now_iso(),
        "task_id": manifest_row["task_id"],
        "repository": manifest_row["repository"],
        "base_commit": task_meta.get("base_commit", ""),
        "benchmark": exp_cfg.get("benchmark", "SWE-bench_Verified"),
        "model": logical,
        "model_display": entry.get("display_name"),
        "opencode_model_id": model_id or None,
        "model_provider": entry.get("provider"),
        "opencode_version": opencode_version,
        "opencode_agent": agent,
        "reasoning": reasoning_cfg,
        "replicate": manifest_row["replicate"],
        "retry_of": manifest_row.get("retry_of"),
        "prompt_sha256": prompt_sha,
        "docker_image": docker_image,
        "timeout_s": timeout_s,
        "timeout": False,
    }

    if dry_run:
        (run_dir / "worktree_clean.ok").write_text("dry-run; no worktree\n", encoding="utf-8")
        rec.update({"dry_run": True, "exit_status": 0, "duration_s": 0.0,
                    "resolved": None, "error_category": "unresolved",
                    "agent_stdout_path": None, "note": "dry-run: no model call"})
        (run_dir / "result.json").write_text(json.dumps(rec, indent=2), encoding="utf-8")
        return rec

    if not model_id:
        rec.update({"exit_status": 127, "duration_s": 0.0, "resolved": None,
                    "error_category": "opencode_error",
                    "note": f"model '{logical}' has no opencode_model_id (see config/models.yaml); "
                            "run blocked before any model call"})
        (run_dir / "result.json").write_text(json.dumps(rec, indent=2), encoding="utf-8")
        return rec

    try:
        materialize_worktree(docker_image, workdir, task_meta.get("base_commit", ""))
        # No experimental files injected (v2). Pre-existing repo docs stay as-is.
        (run_dir / "worktree_clean.ok").write_text(
            "exact base_commit and clean tree asserted pre-run\n", encoding="utf-8")
    except Exception as e:
        rec.update({"exit_status": 125, "duration_s": 0.0, "resolved": None,
                    "error_category": "docker_error",
                    "note": f"worktree materialization failed: {sanitize(str(e))}"})
        (run_dir / "result.json").write_text(json.dumps(rec, indent=2), encoding="utf-8")
        return rec

    cmd = build_command(opencode_exe, str(workdir), model_id, variant, agent,
                        title=f"{run_id[:60]}")
    (run_dir / "opencode_cmd.txt").write_text(
        sanitize(" ".join(cmd) + " < prompt.md"), encoding="utf-8")
    t0 = time.time()
    timed_out = False
    try:
        p = subprocess.run(cmd, input=prompt, capture_output=True, text=True,
                           timeout=timeout_s, cwd=str(root))
        stdout, stderr, code = p.stdout, p.stderr, p.returncode
    except subprocess.TimeoutExpired as e:
        timed_out = True
        out = e.stdout
        stdout = out.decode() if isinstance(out, bytes) else (out or "")
        stderr, code = "", 124
    except FileNotFoundError:
        stdout, stderr, code = "", "opencode executable not found", 127
    dur = time.time() - t0

    (run_dir / "transcript.jsonl").write_text(sanitize(stdout or ""), encoding="utf-8")
    (run_dir / "agent.stderr.log").write_text(sanitize(stderr or ""), encoding="utf-8")

    usage = parse_events((stdout or "").splitlines())
    # best-effort session export for manual case review (never required)
    if usage.get("session_id"):
        try:
            ex = subprocess.run([opencode_exe, "export", usage["session_id"]],
                                capture_output=True, text=True, timeout=120)
            if ex.returncode == 0 and ex.stdout.strip():
                (run_dir / "session_export.json").write_text(
                    sanitize(ex.stdout), encoding="utf-8")
        except Exception:
            pass

    patch_text = ""
    files_modified: list[str] = []
    try:
        d = subprocess.run(["git", "-C", str(workdir), "diff"], capture_output=True,
                            text=True, timeout=60)
        patch_text = d.stdout or ""
        names = subprocess.run(["git", "-C", str(workdir), "diff", "--name-only"],
                               capture_output=True, text=True, timeout=60)
        files_modified = [line for line in names.stdout.splitlines() if line.strip()]
    except Exception:
        patch_text = ""
    _write_lf_text(run_dir / "model.patch", patch_text)
    if not patch_text.strip():
        error_hint = "invalid_patch" if code == 0 else None
    else:
        error_hint = None

    pricing_entry = (pricing.get("models") or {}).get(logical, {})
    rec.update({
        "duration_s": round(dur, 1),
        "wall_clock_s": round(dur, 1),
        "exit_status": code,
        "timeout": timed_out,
        "resolved": None,  # filled by evaluator stage
        "evaluator_status": None,
        "input_tokens": usage["input_tokens"],
        "cached_input_tokens": usage["cached_read_tokens"],
        "output_tokens": usage["output_tokens"],
        "reasoning_tokens": usage["reasoning_tokens"],
        "total_tokens": usage["total_tokens"],
        "tool_calls": usage["tool_calls"],
        "tool_counts": usage["tool_counts"],
        "shell_command_count": usage["shell_commands"],
        "test_command_count": None,  # derived post-hoc from transcript if needed
        "files_read": usage["files_read"],
        "files_modified": files_modified,
        "lines_added": sum(1 for l in patch_text.splitlines()
                           if l.startswith("+") and not l.startswith("+++")),
        "lines_deleted": sum(1 for l in patch_text.splitlines()
                             if l.startswith("-") and not l.startswith("---")),
        "patch_size": len(patch_text.encode("utf-8")),
        "model_retries": None,
        "provider_errors": usage["errors"] or None,
        "actual_cost_usd": usage["actual_cost_usd"],
        "normalized_api_cost_usd": _normalized_cost(usage, pricing_entry),
        "transcript_path": str(run_dir / "transcript.jsonl"),
        "agent_stderr_path": str(run_dir / "agent.stderr.log"),
        "patch_path": str(run_dir / "model.patch"),
        "evaluator_log_path": None,
        "opencode_session_id": usage["session_id"],
        "finish_reasons": usage["finish_reasons"],
        "error_category": error_hint or classify(code, timed_out, None,
                                                (stderr or "") + "\n" + "\n".join(usage["errors"])),
    })
    (run_dir / "result.json").write_text(json.dumps(rec, indent=2), encoding="utf-8")
    return rec
