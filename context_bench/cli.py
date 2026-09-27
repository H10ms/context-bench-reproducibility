"""CLI (schema v2, GPT-6 Sol-vs-Luna on shared OpenCode harness).

doctor | validate | estimate | manifest --verify | smoke | pilot | freeze |
full --confirm-full-run | analyze | audit | rerun | compare | dry-run
"""
from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

import click

from . import EXPERIMENT_VERSION
from .benchmark import load_for_context
from .config import ROOT, load_all, validate_config
from .container import docker_info
from .context_audit import audit_run_dir
from .freeze import check_freeze, collect_freeze, harness_git
from .manifest import (build_manifest, manifest_hash, pilot_tasks,
                       read_manifest, verify_manifest, write_manifest)
from .metrics import append_raw, read_all
from .opencode_harness import build_command
from .pricing import check_budget, estimate_campaign
from .runner import PROMPT_WRAPPER, build_prompt, run_single
from .task_selection import classify_issue_type
from .utils import sanitize, sha256_text

_CACHED_CFG = None


def _cfg():
    global _CACHED_CFG
    if _CACHED_CFG is None:
        _CACHED_CFG = load_all(ROOT)
    return _CACHED_CFG


def _meta_path(root: Path, exp: dict) -> Path:
    return root / exp["task_metadata_path"]


def _resolve_task_meta(task_id: str, cfg: dict) -> dict:
    """Agent-visible metadata only (parquet fallback inside benchmark). Cached."""
    root, exp = cfg["root"], cfg["experiment"]
    cache_p = _meta_path(root, exp)
    cache = json.loads(cache_p.read_text(encoding="utf-8")) if cache_p.exists() else {}
    if task_id in cache:
        return cache[task_id]
    rec = load_for_context(task_id, exp.get("swebench_hf_id"))
    meta = {"instance_id": task_id, "repo": rec.get("repo"),
            "base_commit": rec.get("base_commit"),
            "problem_statement": rec.get("problem_statement", "")[:20000],
            "version": rec.get("version"), "image": rec.get("image"),
            "environment_setup_commit": rec.get("environment_setup_commit"),
            "difficulty": rec.get("difficulty"),
            **classify_issue_type(rec.get("problem_statement", ""))}
    cache[task_id] = meta
    cache_p.parent.mkdir(parents=True, exist_ok=True)
    cache_p.write_text(json.dumps(cache, indent=2), encoding="utf-8")
    return meta


def _opencode_exe() -> str | None:
    return shutil.which("opencode")


def _opencode_version(exe: str | None) -> str | None:
    if not exe:
        return None
    try:
        p = subprocess.run([exe, "--version"], capture_output=True, text=True, timeout=15)
        out = (p.stdout or p.stderr or "").strip().splitlines()
        return out[0][:40] if out else "unknown"
    except Exception:
        return "probe-failed"


def _opencode_models(exe: str | None) -> list[str]:
    """Catalog only (`opencode models`) — free, no generation. Never raises."""
    if not exe:
        return []
    try:
        env = dict(os.environ, NO_COLOR="1")
        p = subprocess.run([exe, "models"], capture_output=True, text=True,
                           timeout=60, env=env)
        return [l.strip() for l in (p.stdout or "").splitlines() if "/" in l.strip()]
    except Exception:
        return []


def _model_ids(cfg: dict) -> dict[str, str | None]:
    return {m["logical_name"]: m.get("opencode_model_id") for m in cfg["models"]["models"]}


def _model_keys(cfg: dict) -> list[str]:
    return [m["logical_name"] for m in cfg["models"]["models"]]


def _build_manifest(cfg: dict, tasks: list[str], replicates: int, phase: str) -> list[dict]:
    exp = cfg["experiment"]
    return build_manifest(tasks, _model_keys(cfg), replicates, exp["experiment_seed"],
                          experiment_id=exp["experiment_id"], phase=phase,
                          model_ids=_model_ids(cfg))


def _verify_manifest(cfg: dict, manifest_rows: list[dict]) -> list[str]:
    exp = cfg["experiment"]
    return verify_manifest(manifest_rows, cfg["tasks"]["tasks"], _model_keys(cfg),
                           exp["replicates"], exp["experiment_seed"],
                           experiment_id=exp["experiment_id"], phase="full",
                           model_ids=_model_ids(cfg))


def _swebench_version() -> str | None:
    try:
        import importlib.metadata as md
        return md.version("swebench")
    except Exception:
        return None


# ------------------------------------------------------------------ doctor

@click.group()
def cli():
    pass


@cli.command()
def doctor():
    """Readiness. Never spends money, never prints secrets, never fake-PASSes models."""
    cfg = _cfg()
    exp = cfg["experiment"]
    lines = [f"GPT-6 Sol-vs-Luna harness v{EXPERIMENT_VERSION} (schema 2)",
             f"python {sys.version.split()[0]} on {platform.platform()}"]
    exe = _opencode_exe()
    over = _opencode_version(exe)
    lines.append(f"opencode: {(exe or 'NOT INSTALLED')} version={over}")
    catalog = _opencode_models(exe)
    lines.append(f"opencode models catalog: {len(catalog)} entries (free check, no generation)")
    for m in cfg["models"]["models"]:
        mid = m.get("opencode_model_id")
        if mid and mid in catalog:
            avail = "AVAILABLE in catalog"
        elif mid:
            avail = "NOT in current catalog -> will fail, re-check config"
        else:
            avail = "UNKNOWN (no opencode_model_id configured; see config/models.yaml)"
        lines.append(f"model {m['logical_name']} ({m['display_name']}): id={mid or 'null'} -> {avail}")
    lines.append(f"auth: opencode providers credentials file "
                 f"{'present' if (Path.home() / '.local/share/opencode/auth.json').exists() else 'absent (free-tier implicit access observed 2026-09-20; paid models need login)'}")
    di = docker_info()
    lines.append(f"docker: {di.version or 'missing'} | daemon_ok={di.daemon_ok}")
    lines.append(f"git: {harness_git(cfg['root'])}")
    lines.append(f"swebench: {_swebench_version() or 'NOT INSTALLED'}")
    errs = validate_config(cfg)
    lines.append("config: " + ("OK" if not errs else f"ERRORS: {errs}"))
    pricing = cfg["pricing"]
    known = sum(1 for m in (pricing.get("models") or {}).values()
                if m.get("input_per_1m") is not None and m.get("output_per_1m") is not None)
    lines.append(f"pricing: {known}/2 models have normalized prices "
                 f"(source={pricing.get('price_source')}, checked={pricing.get('price_checked_at')})")
    import shutil as _sh
    _du = _sh.disk_usage(str(cfg["root"]))
    lines.append(f"disk free: {_du.free // (1024**3)} GiB")
    for d in (exp["runs_smoke_dir"], exp["runs_pilot_dir"], exp["runs_dir"],
              str(Path(exp["results_smoke_raw"]).parent),
              str(Path(exp["results_pilot_raw"]).parent),
              str(Path(exp["results_raw"]).parent)):
        p = cfg["root"] / d
        try:
            p.mkdir(parents=True, exist_ok=True)
            lines.append(f"writable: {d} OK")
        except Exception as e:
            lines.append(f"writable: {d} FAIL {e}")
    lines.append(f"reasoning: {exp.get('reasoning_effort')} (same --variant for both models)")
    lines.append(f"timeout: {exp.get('agent_timeout_seconds')}s (identical for both models)")
    click.echo("\n".join(lines))


# ------------------------------------------------------------------ validate

@cli.command()
def validate():
    """Free/local gates. No model calls. Writes validation_report.md."""
    cfg = _cfg()
    root, exp = cfg["root"], cfg["experiment"]
    report: list[str] = [f"# validation_report v{EXPERIMENT_VERSION} (schema 2)", ""]
    ok = True

    p = subprocess.run([sys.executable, "-m", "pytest", "-q"], capture_output=True,
                       text=True, cwd=str(root))
    report.append(f"## 1. project tests: {'PASS' if p.returncode == 0 else 'FAIL'}")
    report.append(f"```\n{sanitize((p.stdout or '')[-1500:] + (p.stderr or '')[-1500:])}\n```")
    ok &= p.returncode == 0

    errs = validate_config(cfg)
    report.append(f"## 2. config: {'OK' if not errs else 'ERRORS: ' + str(errs)}")
    ok &= not errs

    task_ids = cfg["tasks"]["tasks"]
    reserves = cfg["tasks"].get("reserve_tasks", [])
    missing = [t for t in task_ids + reserves if not _task_ok(t, cfg)]
    report.append(f"## 3. benchmark: {len(task_ids) - len([m for m in missing if m in task_ids])}/30 main valid, "
                  f"{len(reserves) - len([m for m in missing if m in reserves])}/{len(reserves)} reserves valid")
    if missing:
        ok = False
        report.append(f"MISSING (substitute same-repo reserve pre-first-run, record in TASK_SELECTION.md): {missing}")
    else:
        report.append("all 30 main + 18 reserves resolvable (Hub or offline parquet cache).")

    di = docker_info()
    report.append(f"## 4. docker: {di.version} daemon_ok={di.daemon_ok} (start Docker Desktop before runs)")

    exe = _opencode_exe()
    over = _opencode_version(exe)
    catalog = _opencode_models(exe)
    report.append(f"## 5. opencode: exe={bool(exe)} version={over} catalog={len(catalog)} models")
    ids = _model_ids(cfg)
    unconfigured = [k for k, v in ids.items() if not v]
    unavailable = [k for k, v in ids.items() if not v or v not in catalog]
    report.append(f"model IDs: {ids} (unconfigured={unconfigured or 'none'}, "
                  f"unavailable={unavailable or 'none'}; "
                   "smoke/pilot/full refuse paid runs until IDs resolve)")
    ok &= bool(exe) and not unavailable

    mf = _build_manifest(cfg, task_ids, exp["replicates"], "full")
    probs = _verify_manifest(cfg, mf)
    report.append(f"## 6. manifest: {len(mf)} runs, verify={probs or 'OK'}, hash={manifest_hash(mf)[:16]}")
    ok &= not probs

    try:
        pa, pb = build_prompt("x"), build_prompt("x")
        assert pa == pb and len(sha256_text(pa)) == 64
        cmd_s = build_command("opencode", "/w", ids["sol"], "medium", "build", "t")
        cmd_l = build_command("opencode", "/w", ids["luna"], "medium", "build", "t")
        assert [c for c in cmd_s if c != ids["sol"]] == [c for c in cmd_l if c != ids["luna"]]
        import context_bench.runner as _r
        import inspect as _i
        src = _i.getsource(_r)
        assert "load_with_gold" not in src
        report.append("## 7. prompt/harness parity: identical wrapper, only --model differs, no gold in runner")
    except Exception as e:
        ok = False
        report.append(f"## 7. prompt/harness parity: FAIL {e}")

    try:
        row = mf[0]
        rec = run_single(row, {"base_commit": "DRY", "problem_statement": "dry"},
                         cfg["models"], exp, cfg["pricing"], root,
                         opencode_exe="opencode", opencode_version="dry", dry_run=True)
        report.append(f"## 8. dry-run: OK ({rec['run_id']})")
    except Exception as e:
        ok = False
        report.append(f"## 8. dry-run: FAIL {e}")

    report.append(f"## 9. evaluator sanity: swebench=={_swebench_version() or 'NOT installed (records evaluator_error, never fakes resolved)'}")
    report.append("")
    report.append(f"OVERALL: {'READY (no paid calls made)' if ok else 'BLOCKED — fix above before any model call'}")
    (root / "validation_report.md").write_text("\n".join(report), encoding="utf-8")
    click.echo("\n".join(report))
    if not ok:
        raise SystemExit(1)


def _task_ok(tid: str, cfg: dict) -> bool:
    try:
        m = _resolve_task_meta(tid, cfg)
        return bool(m.get("base_commit"))
    except Exception:
        return False


# ------------------------------------------------------------------ estimate

@cli.command()
@click.option("--max-budget-usd", type=float, default=None)
def estimate(max_budget_usd):
    cfg = _cfg()
    exp = cfg["experiment"]
    keys = _model_keys(cfg)
    est = {
        "smoke_4_runs": estimate_campaign(cfg["pricing"], keys, 2,
                                          exp["expected_input_tokens_per_run"],
                                          exp["expected_output_tokens_per_run"]),
        "pilot_12_runs": estimate_campaign(cfg["pricing"], keys, 6,
                                           exp["expected_input_tokens_per_run"],
                                           exp["expected_output_tokens_per_run"]),
        "full_120_runs": estimate_campaign(cfg["pricing"], keys, 60,
                                           exp["expected_input_tokens_per_run"],
                                           exp["expected_output_tokens_per_run"]),
    }
    click.echo(json.dumps(est, indent=2))
    if est["full_120_runs"]["unknown"]:
        click.echo("WARNING: normalized pricing unknown — fill config/pricing.yaml before spending. "
                   "Actual OpenCode-reported cost is collected per-run when available (null until then).")
    if max_budget_usd is not None:
        ok, msg = check_budget(est["full_120_runs"]["total_estimated_usd"], max_budget_usd)
        click.echo(f"budget(full): {msg}")
        if not ok:
            raise SystemExit(2)


# ------------------------------------------------------------------ manifest

@cli.command()
@click.option("--verify", is_flag=True, default=False, help="Verify frozen manifest.")
@click.option("--rebuild", is_flag=True, default=False, help="Rebuild manifest file (pre-freeze only).")
def manifest(verify, rebuild):
    cfg = _cfg()
    exp = cfg["experiment"]
    mp = cfg["root"] / exp["manifest_path"]
    if rebuild:
        mf = _build_manifest(cfg, cfg["tasks"]["tasks"], exp["replicates"], "full")
        mp.parent.mkdir(parents=True, exist_ok=True)
        write_manifest(mf, mp)
        click.echo(f"rebuilt {len(mf)} runs -> {mp} hash={manifest_hash(mf)}")
        return
    if verify:
        if not mp.exists():
            raise click.ClickException("no manifest file; run `manifest --rebuild` first (pre-freeze).")
        mf = read_manifest(mp)
        probs = _verify_manifest(cfg, mf)
        click.echo(f"manifest: {len(mf)} runs hash={manifest_hash(mf)}")
        if probs:
            raise click.ClickException(f"VERIFY FAILED: {probs}")
        click.echo("VERIFY OK")
        return
    raise click.ClickException("specify --verify or --rebuild")


# ------------------------------------------------------------------ runners

def _paid_guard(cfg: dict, rows: list[dict], label: str, max_budget_usd: float | None,
                n_expected: int, allow_unknown_cost: bool) -> dict:
    exp = cfg["experiment"]
    ids = _model_ids(cfg)
    missing = [k for k, v in ids.items() if not v]
    if missing:
        raise click.ClickException(
            f"{label}: model(s) {missing} have no opencode_model_id (config/models.yaml). "
            "Refusing paid runs. Run `opencode models`, fill IDs, re-run validate.")
    catalog = _opencode_models(_opencode_exe())
    unavailable = [k for k, v in ids.items() if v not in catalog]
    if unavailable:
        raise click.ClickException(
            f"{label}: model(s) {unavailable} are not in the current OpenCode catalog. Refusing paid runs.")
    est = estimate_campaign(cfg["pricing"], _model_keys(cfg), n_expected // 2,
                            exp["expected_input_tokens_per_run"],
                            exp["expected_output_tokens_per_run"])
    click.echo(f"{label}: models={ids} tasks={sorted({r['task_id'] for r in rows})}")
    click.echo(f"{label}: {len(rows)} planned runs, timeout={exp['agent_timeout_seconds']}s, "
               f"reasoning={exp['reasoning_effort']}")
    click.echo(f"{label}: normalized estimate=${est['total_estimated_usd']} "
               f"(unknown={est['unknown']})")
    if est["unknown"] and not allow_unknown_cost:
        raise click.ClickException(f"{label}: normalized cost unknown — fill pricing or pass --allow-unknown-cost.")
    if max_budget_usd is not None:
        ok, msg = check_budget(est["total_estimated_usd"], max_budget_usd,
                               allow_unknown_cost)
        click.echo(f"{label}: budget {msg}")
        if not ok:
            raise SystemExit(2)
    return est


def _execute(rows: list[dict], cfg: dict, label: str, raw_rel: str, runs_rel: str,
             resume: bool) -> None:
    root, exp = cfg["root"], cfg["experiment"]
    raw_path = root / raw_rel
    done = {r.get("run_id") for r in read_all(raw_path)} if resume and raw_path.exists() else set()
    exe = _opencode_exe() or "opencode"
    over = _opencode_version(exe) or "unknown"
    click.echo(f"{label}: {len(rows)} planned, {len(done)} done (resume={resume}), opencode={over}")
    exp_view = dict(exp, runs_dir=runs_rel)
    for row in rows:
        if row["run_id"] in done:
            click.echo(f"skip {row['run_id']} (already done)")
            continue
        meta = _resolve_task_meta(row["task_id"], cfg)
        rec = run_single(row, meta, cfg["models"], exp_view, cfg["pricing"], root,
                         opencode_exe=exe, opencode_version=over)
        # Separate evaluation stage (gold allowed ONLY here, session is over).
        if not rec.get("dry_run") and rec.get("exit_status") == 0:
            from .evaluator import run_swebench_eval
            ev = run_swebench_eval(row["task_id"], root / runs_rel / row["run_id"] / "model.patch",
                                   row["run_id"], root / runs_rel / row["run_id"])
            rec["resolved"] = ev.get("resolved")
            rec["evaluator_status"] = ev.get("evaluator", "error")
            rec["evaluator_log_path"] = ev.get("log")
            rec["error_category"] = ("successful" if ev.get("resolved") is True
                                     else "unresolved" if ev.get("resolved") is False
                                     else "evaluator_error")
            (root / runs_rel / row["run_id"] / "result.json").write_text(
                json.dumps(rec, indent=2), encoding="utf-8")
        append_raw(rec, raw_path)
        click.echo(f"done {rec['run_id']} exit={rec['exit_status']} err={rec['error_category']}")


@cli.command()
@click.option("--dry-run", is_flag=True, default=False)
@click.option("--allow-unknown-cost", is_flag=True, default=False)
def smoke(dry_run, allow_unknown_cost):
    """2 tasks x 2 models x 1 rep = 4 REAL runs (paid confirmation unless --dry-run)."""
    cfg = _cfg()
    exp = cfg["experiment"]
    tasks = exp["smoke_tasks"]
    rows = _build_manifest(cfg, tasks, 1, "smoke")
    if dry_run:
        for row in rows:
            run_single(row, {"base_commit": "DRY", "problem_statement": "dry"},
                       cfg["models"], dict(exp, runs_dir=exp["runs_smoke_dir"]), cfg["pricing"],
                       cfg["root"], opencode_exe="opencode", opencode_version="dry",
                       dry_run=True)
        click.echo(f"smoke dry-run OK ({len(rows)} runs, no model calls)")
        return
    _paid_guard(cfg, rows, "smoke", None, 4, allow_unknown_cost)
    if not click.confirm("Proceed with 4 PAID smoke runs?", default=False):
        raise click.ClickException("aborted by user")
    _execute(rows, cfg, "smoke", exp["results_smoke_raw"], exp["runs_smoke_dir"], resume=False)


@cli.command()
@click.option("--max-budget-usd", type=float, default=None)
@click.option("--resume", is_flag=True, default=False)
@click.option("--dry-run", is_flag=True, default=False)
@click.option("--allow-unknown-cost", is_flag=True, default=False)
def pilot(max_budget_usd, resume, dry_run, allow_unknown_cost):
    """6 tasks x 2 models x 1 rep = 12 experiment- and phase-scoped runs."""
    cfg = _cfg()
    exp = cfg["experiment"]
    tasks = pilot_tasks(cfg["tasks"]["tasks"])
    rows = _build_manifest(cfg, tasks, exp["pilot_replicates"], "pilot")
    pilot_meta = cfg["root"] / Path(exp["results_pilot_raw"]).parent / "pilot_tasks.json"
    pilot_meta.parent.mkdir(parents=True, exist_ok=True)
    pilot_meta.write_text(
        json.dumps({"tasks": tasks, "seed": exp["experiment_seed"]}, indent=2), encoding="utf-8")
    if dry_run:
        for row in rows:
            run_single(row, {"base_commit": "DRY", "problem_statement": "dry"},
                       cfg["models"], dict(exp, runs_dir=exp["runs_pilot_dir"]), cfg["pricing"],
                       cfg["root"], opencode_exe="opencode", opencode_version="dry",
                       dry_run=True)
        click.echo(f"pilot dry-run OK ({len(rows)} runs, no model calls)")
        return
    git = harness_git(cfg["root"])
    if git["dirty"]:
        click.echo(f"WARNING: harness working tree dirty ({git['dirty_count']} entries) — pilot continues, full will refuse.")
    _paid_guard(cfg, rows, "pilot", max_budget_usd, 12, allow_unknown_cost)
    if not click.confirm("Proceed with 12 PAID pilot runs?", default=False):
        raise click.ClickException("aborted by user")
    _execute(rows, cfg, "pilot", exp["results_pilot_raw"], exp["runs_pilot_dir"], resume=resume)


@cli.command()
def freeze():
    """Write EXPERIMENT_FREEZE.json (after pilot, before full)."""
    cfg = _cfg()
    exp = cfg["experiment"]
    mp = cfg["root"] / exp["manifest_path"]
    if not mp.exists():
        mf = _build_manifest(cfg, cfg["tasks"]["tasks"], exp["replicates"], "full")
        mp.parent.mkdir(parents=True, exist_ok=True)
        write_manifest(mf, mp)
    mf = read_manifest(mp)
    exe = _opencode_exe() or "opencode"
    fr = collect_freeze(cfg, mf, _opencode_version(exe) or "unknown",
                        _swebench_version(), cfg["models"]["models"])
    (cfg["root"] / exp.get("freeze_path", "EXPERIMENT_FREEZE.json")).write_text(
        json.dumps(fr, indent=2), encoding="utf-8")
    click.echo(json.dumps({k: fr[k] for k in ("manifest_hash", "manifest_runs", "opencode_version",
                                             "harness_git_sha", "frozen_at")}, indent=2))


@cli.command(name="full")
@click.option("--confirm-full-run", is_flag=True, default=False)
@click.option("--resume", is_flag=True, default=False)
@click.option("--max-budget-usd", type=float, default=None, required=False)
@click.option("--allow-dirty-harness", is_flag=True, default=False)
@click.option("--break-freeze", is_flag=True, default=False)
@click.option("--allow-unknown-cost", is_flag=True, default=False)
def full(confirm_full_run, resume, max_budget_usd, allow_dirty_harness,
         break_freeze, allow_unknown_cost):
    """30 x 2 x 2 = 120 runs. Requires --confirm-full-run AND --max-budget-usd."""
    if not confirm_full_run:
        raise click.ClickException("refusing 120-run launch without --confirm-full-run (see README).")
    if max_budget_usd is None:
        raise click.ClickException("full requires --max-budget-usd (cost guard is mandatory).")
    cfg = _cfg()
    exp = cfg["experiment"]
    git = harness_git(cfg["root"])
    if git["dirty"] and not allow_dirty_harness:
        raise click.ClickException(
            f"harness tree dirty ({git['dirty_count']} entries). Commit first or pass --allow-dirty-harness "
            "(diff will be archived in run metadata).")
    if git["dirty"] and allow_dirty_harness:
        d = subprocess.run(["git", "diff"], capture_output=True, text=True, timeout=60,
                           cwd=str(cfg["root"]))
        (cfg["root"] / "EXPERIMENT_FREEZE.dirty.diff").write_text(
            sanitize(d.stdout or ""), encoding="utf-8")
    mp = cfg["root"] / exp["manifest_path"]
    if not mp.exists():
        mf = _build_manifest(cfg, cfg["tasks"]["tasks"], exp["replicates"], "full")
        mp.parent.mkdir(parents=True, exist_ok=True)
        write_manifest(mf, mp)
    mf = read_manifest(mp)
    assert len(mf) == 120, f"manifest must fix 120 runs, got {len(mf)}"
    fp = cfg["root"] / exp.get("freeze_path", "EXPERIMENT_FREEZE.json")
    exe = _opencode_exe() or "opencode"
    over = _opencode_version(exe) or "unknown"
    if not fp.exists() and not break_freeze:
        raise click.ClickException("no EXPERIMENT_FREEZE.json — run `freeze` after pilot first (or --break-freeze).")
    if fp.exists():
        freeze = json.loads(fp.read_text(encoding="utf-8"))
        problems = check_freeze(cfg, mf, over, freeze)
        if problems and not break_freeze:
            raise click.ClickException(f"freeze mismatch {problems} — investigate or pass --break-freeze (recorded).")
        if problems:
            with open(cfg["root"] / "EXPERIMENT_FREEZE.breaks.jsonl", "a", encoding="utf-8") as f:
                f.write(json.dumps({"at": problems, "over": over}) + "\n")
    _paid_guard(cfg, mf, "full", max_budget_usd, 120, allow_unknown_cost)
    _execute(mf, cfg, "full", exp["results_raw"], exp["runs_dir"], resume=resume)


# ------------------------------------------------------------------ analyze / audit / rerun / compare

@cli.command()
@click.option("--scope", type=click.Choice(["smoke", "pilot", "full"]), default="full")
def analyze(scope):
    from analysis.analyze import run_analysis
    cfg = _cfg()
    res = run_analysis(ROOT, scope=scope, experiment=cfg["experiment"],
                       models=_model_ids(cfg))
    click.echo(json.dumps(res, indent=2))


@cli.command()
@click.argument("run_id")
def audit(run_id):
    """Blindness/leakage checks for one run (gold read ONLY here, never in runner)."""
    cfg = _cfg()
    root = cfg["root"]
    run_dir = None
    for base in (cfg["experiment"]["runs_smoke_dir"], cfg["experiment"]["runs_pilot_dir"],
                 cfg["experiment"]["runs_dir"]):
        cand = root / base / run_id
        if cand.exists():
            run_dir = cand
            break
    if run_dir is None:
        raise click.ClickException(f"unknown run_id: {run_id}")
    meta_p = run_dir / "result.json"
    meta = json.loads(meta_p.read_text(encoding="utf-8")) if meta_p.exists() else {}
    out = {"run_id": run_id, "schema": meta.get("schema_version"),
           "dir_checks": audit_run_dir(run_dir)}
    try:
        from .benchmark import load_with_gold
        from .context_audit import check_no_gold_strings
        task = meta.get("task_id")
        if task:
            gold = load_with_gold(task)
            prompt = (run_dir / "prompt.md").read_text(encoding="utf-8") \
                if (run_dir / "prompt.md").exists() else ""
            out["gold_string_overlap"] = check_no_gold_strings(prompt, gold.get("patch", ""))
            out["note"] = "gold read ONLY inside audit; runner never sees it"
    except Exception as e:
        out["gold_check"] = f"skipped: {sanitize(str(e))}"
    click.echo(json.dumps(out, indent=2))


@cli.command()
@click.argument("run_id")
def rerun(run_id):
    """Safe rerun of an infrastructure failure: new run_id, retry_of linkage, original kept."""
    cfg = _cfg()
    exp = cfg["experiment"]
    orig = None
    raw_rel = None
    scopes = ((exp["results_smoke_raw"], exp["runs_smoke_dir"]),
              (exp["results_pilot_raw"], exp["runs_pilot_dir"]),
              (exp["results_raw"], exp["runs_dir"]))
    runs_rel = None
    for rel, candidate_runs in scopes:
        for r in read_all(cfg["root"] / rel):
            if r.get("run_id") == run_id:
                orig, raw_rel, runs_rel = r, rel, candidate_runs
                break
    if orig is None:
        raise click.ClickException(f"run_id not found in results: {run_id}")
    from .manifest import run_id_for
    new_id = run_id_for(orig["task_id"], orig["model"], orig["replicate"],
                        exp["experiment_seed"], retry_of=run_id,
                        experiment_id=exp["experiment_id"], phase=orig["phase"],
                        model_id=orig["opencode_model_id"])
    row = {"task_id": orig["task_id"], "repository": orig["repository"],
           "model": orig["model"], "replicate": orig["replicate"],
           "run_id": new_id, "retry_of": run_id, "seed": exp["experiment_seed"],
           "experiment_id": exp["experiment_id"], "phase": orig["phase"]}
    _execute([row], cfg, f"rerun(of {run_id})", raw_rel, runs_rel, resume=False)
    click.echo(f"rerun {new_id} retry_of={run_id} (original preserved)")


@cli.command()
@click.argument("task_id")
def compare(task_id):
    """Side-by-side GPT-6 Sol vs Luna for one task in the active experiment."""
    cfg = _cfg()
    exp = cfg["experiment"]
    rows = []
    for rel in (exp["results_smoke_raw"], exp["results_pilot_raw"], exp["results_raw"]):
        rows += [r for r in read_all(cfg["root"] / rel) if r.get("task_id") == task_id]
    if not rows:
        raise click.ClickException(f"no results for {task_id} (run smoke/pilot/full first)")
    out = {"task_id": task_id, "models": {}}
    for m in ("sol", "luna"):
        sub = sorted([r for r in rows if r.get("model") == m],
                     key=lambda r: r.get("replicate", 0))
        out["models"][m] = [{
            "replicate": r.get("replicate"), "resolved": r.get("resolved"),
            "error_category": r.get("error_category"),
            "actual_cost_usd": r.get("actual_cost_usd"),
            "normalized_api_cost_usd": r.get("normalized_api_cost_usd"),
            "duration_s": r.get("duration_s"),
            "input_tokens": r.get("input_tokens"), "output_tokens": r.get("output_tokens"),
            "reasoning_tokens": r.get("reasoning_tokens"),
            "tool_calls": r.get("tool_calls"),
            "lines_added": r.get("lines_added"), "lines_deleted": r.get("lines_deleted"),
            "evaluator_status": r.get("evaluator_status"),
            "transcript": r.get("transcript_path"), "patch": r.get("patch_path"),
        } for r in sub]
    pairs = []
    for rep in (1, 2):
        s = next((r for r in rows if r.get("model") == "sol" and r.get("replicate") == rep), {})
        luna = next((r for r in rows if r.get("model") == "luna" and r.get("replicate") == rep), {})
        sR, lR = s.get("resolved"), luna.get("resolved")
        cat = ("both solved" if sR and lR else "only Sol" if sR else
               "only Luna" if lR else "neither" if sR is False and lR is False else "pending")
        pairs.append({"replicate": rep, "sol": sR, "luna": lR, "category": cat})
    out["pairs"] = pairs
    click.echo(json.dumps(out, indent=2))


@cli.command("dry-run")
def dry_run():
    """Harness exercise: 2 tasks x 2 models x 1 rep, no model calls."""
    cfg = _cfg()
    exp = cfg["experiment"]
    rows = _build_manifest(cfg, exp["smoke_tasks"], 1, "smoke")
    for row in rows:
        run_single(row, {"base_commit": "DRY", "problem_statement": "dry"},
                   cfg["models"], dict(exp, runs_dir=exp["runs_smoke_dir"]), cfg["pricing"],
                   cfg["root"], opencode_exe="opencode", opencode_version="dry",
                   dry_run=True)
    click.echo(f"dry-run OK ({len(rows)} runs)")


def main():
    cli()


if __name__ == "__main__":
    main()
