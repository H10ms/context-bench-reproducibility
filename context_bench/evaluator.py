"""Evaluator wrapper. Gold patch used HERE ONLY, after agent session ends."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


_SWEBENCH_BOOTSTRAP = r"""
import runpy
from pathlib import Path

_write_text = Path.write_text

def _write_lf_eval_script(self, data, *args, **kwargs):
    if self.name == "eval.sh":
        kwargs["newline"] = "\n"
    return _write_text(self, data, *args, **kwargs)

Path.write_text = _write_lf_eval_script
runpy.run_module("swebench.harness.run_evaluation", run_name="__main__")
"""


def run_swebench_eval(instance_id: str, model_patch: Path, run_id: str,
                      out_dir: Path, timeout_s: int = 1200) -> dict:
    """Invoke official harness if installed; else record evaluator_error (never fake resolved)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    log = out_dir / f"{run_id}.eval.log"
    preds = out_dir / f"{run_id}.preds.json"
    preds.write_text(json.dumps([
        {"instance_id": instance_id, "model_patch": model_patch.read_text(encoding="utf-8")
         if model_patch.exists() else "", "model_name_or_path": run_id}]),
        encoding="utf-8")
    cmd = [sys.executable, "-c", _SWEBENCH_BOOTSTRAP,
           "--dataset_name", "SWE-bench/SWE-bench_Verified",
           "--predictions_path", str(preds),
           "--max_workers", "1",
           "--run_id", run_id,
           "--report_dir", str(out_dir)]
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_s)
        log.write_text(f"$ {' '.join(cmd)}\n--- stdout ---\n{p.stdout}\n--- stderr ---\n{p.stderr}\n",
                       encoding="utf-8")
        resolved = None
        # harness writes report; best-effort parse
        for cand in out_dir.rglob("*.json"):
            if cand == preds:
                continue
            try:
                data = json.loads(cand.read_text(encoding="utf-8"))
                if isinstance(data, dict) and instance_id in data:
                    resolved = data[instance_id].get("resolved")
                elif isinstance(data, dict) and instance_id in data.get("resolved_ids", []):
                    resolved = True
                elif isinstance(data, dict) and instance_id in data.get("unresolved_ids", []):
                    resolved = False
            except Exception:
                continue
        return {"resolved": resolved, "log": str(log), "returncode": p.returncode,
                "evaluator": "swebench.harness.run_evaluation"}
    except FileNotFoundError:
        log.write_text("swebench harness not installed; resolved=null evaluator_error", encoding="utf-8")
        return {"resolved": None, "log": str(log), "returncode": 127,
                "evaluator": "missing", "error": "swebench not installed"}
    except subprocess.TimeoutExpired:
        log.write_text("evaluator timeout", encoding="utf-8")
        return {"resolved": None, "log": str(log), "returncode": 124,
                "evaluator": "timeout"}


def gold_sanity_check(instance_id: str) -> dict:
    """Separate gold-patch sanity stage. Never feeds info back into contexts/prompts."""
    return {"instance_id": instance_id, "note": "apply gold patch in an isolated container and run FAIL_TO_PASS; see docs/REPRODUCIBILITY.md"}
