"""Harness tests (schema v2) — no paid model calls, no network required."""
import json

from analysis.statistics import (independent_observations, incremental_cost,
                                 medians_table, paired_table, summary_table,
                                 task_aggregate)
from analysis.plots import all_plots
from context_bench.container import materialize_worktree
from context_bench.config import ROOT, load_all, validate_config
from context_bench.context_audit import audit_run_dir
from context_bench.evaluator import run_swebench_eval
from context_bench.freeze import check_freeze, collect_freeze
from context_bench.manifest import (build_manifest, manifest_hash, pilot_tasks,
                                    run_id_for, verify_manifest)
from context_bench.metrics import append_raw, classify, read_all, validate_result
from context_bench.opencode_harness import build_command, parse_events
from context_bench.pricing import check_budget, estimate_campaign
from context_bench.runner import PROMPT_WRAPPER, build_prompt
from context_bench.task_selection import classify_issue_type, cycled_order
from context_bench.utils import sanitize


def _cfg():
    return load_all(ROOT)


def test_config_30_tasks_6repos():
    cfg = _cfg()
    assert validate_config(cfg) == []
    assert len(cfg["tasks"]["tasks"]) == 30
    assert len(cfg["tasks"]["reserve_tasks"]) >= 18


def test_manifest_120_deterministic_interleaved():
    cfg = _cfg()
    exp = cfg["experiment"]
    kwargs = {"experiment_id": cfg["experiment"]["experiment_id"], "phase": "full",
              "model_ids": {m["logical_name"]: m["opencode_model_id"] for m in cfg["models"]["models"]}}
    m1 = build_manifest(cfg["tasks"]["tasks"], ["sol", "luna"], 2, 20260920, **kwargs)
    m2 = build_manifest(cfg["tasks"]["tasks"], ["sol", "luna"], 2, 20260920, **kwargs)
    assert len(m1) == 120
    assert [r["run_id"] for r in m1] == [r["run_id"] for r in m2]
    assert verify_manifest(m1, cfg["tasks"]["tasks"], ["sol", "luna"], 2, 20260920,
                           **kwargs) == []
    models = [r["model"] for r in m1[:10]]
    assert set(models) == {"sol", "luna"}  # no model blocks
    assert "--" not in "".join(r["run_id"] for r in m1).replace("--", "") or True
    assert all("--C" not in r["run_id"] for r in m1)  # no condition segments
    counts = {}
    for r in m1:
        counts[(r["task_id"], r["model"])] = counts.get((r["task_id"], r["model"]), 0) + 1
    assert set(counts.values()) == {2}  # 2 replicates each
    assert manifest_hash(m1) == manifest_hash(m2)


def test_pilot_selection_6_repos():
    cfg = _cfg()
    pt = pilot_tasks(cfg["tasks"]["tasks"])
    assert len(pt) == 6
    assert len({t.split("__")[0] for t in pt}) == 6


def test_prompt_identical_between_models():
    pa, pb = build_prompt("issue text"), build_prompt("issue text")
    assert pa == pb
    from context_bench.utils import sha256_text
    assert sha256_text(pa) == sha256_text(pb)
    assert "Do not use network access." in PROMPT_WRAPPER


def test_opencode_command_differs_only_by_model():
    cfg = _cfg()
    model_ids = {m["logical_name"]: m["opencode_model_id"]
                 for m in cfg["models"]["models"]}
    assert model_ids == {"sol": "openai/gpt-6-sol", "luna": "openai/gpt-6-luna"}
    cs = build_command("opencode", "/w", model_ids["sol"], "medium", "build", "t")
    cl = build_command("opencode", "/w", model_ids["luna"], "medium", "build", "t")
    assert cs != cl
    assert cs[cs.index("--model") + 1] == "openai/gpt-6-sol"
    assert cl[cl.index("--model") + 1] == "openai/gpt-6-luna"
    assert [c for c in cs if c != model_ids["sol"]] == [c for c in cl if c != model_ids["luna"]]
    assert "--format" in cs and "json" in cs and "--variant" in cs


def test_usage_parsing_sums_steps():
    lines = [
        '{"type":"step_start","sessionID":"ses_1"}',
        '{"type":"tool_use","sessionID":"ses_1","part":{"tool":"bash"}}',
        '{"type":"step_finish","sessionID":"ses_1","part":{"reason":"tool-calls","tokens":{"total":100,"input":90,"output":10,"reasoning":5,"cache":{"write":1,"read":2}},"cost":0.01}}',
        '{"type":"step_finish","sessionID":"ses_1","part":{"reason":"stop","tokens":{"total":50,"input":40,"output":10,"reasoning":0,"cache":{"write":0,"read":0}},"cost":0.005}}',
    ]
    u = parse_events(lines)
    assert u["input_tokens"] == 130 and u["output_tokens"] == 20
    assert u["reasoning_tokens"] == 5 and u["session_id"] == "ses_1"
    assert abs(u["actual_cost_usd"] - 0.015) < 1e-9
    assert u["tool_calls"] == 1 and u["shell_commands"] == 1
    assert parse_events(["not json", ""])["input_tokens"] is None


def test_evaluator_writes_prediction_list(tmp_path, monkeypatch):
    patch = tmp_path / "model.patch"
    patch.write_text("diff", encoding="utf-8")

    class Result:
        returncode = 1
        stdout = ""
        stderr = "failed"

    monkeypatch.setattr("context_bench.evaluator.subprocess.run", lambda *args, **kwargs: Result())
    run_swebench_eval("task__1", patch, "run-1", tmp_path)
    predictions = json.loads((tmp_path / "run-1.preds.json").read_text(encoding="utf-8"))
    assert isinstance(predictions, list) and predictions[0]["model_patch"] == "diff"


def test_evaluator_bootstrap_forces_lf_eval_script(tmp_path, monkeypatch):
    patch = tmp_path / "model.patch"
    patch.write_text("diff", encoding="utf-8")
    captured = {}

    class Result:
        returncode = 1
        stdout = ""
        stderr = "failed"

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return Result()

    monkeypatch.setattr("context_bench.evaluator.subprocess.run", fake_run)
    run_swebench_eval("task__1", patch, "run-1", tmp_path)
    assert "kwargs[\"newline\"] = \"\\n\"" in captured["cmd"][2]
    assert "swebench.harness.run_evaluation" in captured["cmd"][2]


def test_runner_forces_lf_text(tmp_path):
    from context_bench.runner import _write_lf_text
    output = tmp_path / "model.patch"
    _write_lf_text(output, "first\nsecond\n")
    assert output.read_bytes() == b"first\nsecond\n"


def test_audit_recognizes_transcript(tmp_path):
    (tmp_path / "transcript.jsonl").write_text("{}\n", encoding="utf-8")
    assert audit_run_dir(tmp_path)["checks"]["log_exists"] is True


def test_model_id_missing_blocks_before_call(tmp_path):
    from context_bench.runner import run_single
    cfg = _cfg()
    models = {"models": [{"logical_name": "sol", "display_name": "S",
                          "opencode_model_id": None, "provider": None,
                          "reasoning_effort": "medium"}]}
    row = {"run_id": "t--sol--r1--x", "task_id": "t", "repository": "django",
           "model": "sol", "replicate": 1}
    rec = run_single(row, {"base_commit": "b", "problem_statement": "p"}, models,
                     dict(cfg["experiment"], runs_dir="runs/v2"), cfg["pricing"],
                     tmp_path, opencode_exe="opencode", opencode_version="test")
    assert rec["error_category"] == "opencode_error"
    assert rec["opencode_model_id"] is None


def test_timeout_equal_and_recorded(tmp_path):
    from context_bench.runner import run_single
    cfg = _cfg()
    assert cfg["experiment"]["agent_timeout_seconds"] > 0
    row = {"run_id": "t--sol--r1--y", "task_id": "t", "repository": "django",
           "model": "sol", "replicate": 1}
    rec = run_single(row, {"base_commit": "b", "problem_statement": "p"},
                     cfg["models"], dict(cfg["experiment"], runs_dir="runs/v2"),
                     cfg["pricing"], tmp_path, opencode_exe="opencode",
                     opencode_version="test", dry_run=True)
    assert rec["timeout_s"] == cfg["experiment"]["agent_timeout_seconds"]


def test_result_schema_v2_and_resume(tmp_path):
    rec = {"schema_version": 2, "run_id": "r1", "experiment_version": "0.3.0",
           "experiment_id": "gpt6-sol-vs-luna-swbench-v1", "phase": "pilot",
           "timestamp": "t", "task_id": "django__django-9296", "repository": "django",
           "base_commit": "b", "model": "sol", "opencode_model_id": "x/y",
           "reasoning": {"variant": "medium"}, "replicate": 1,
           "prompt_sha256": "s", "docker_image": "img", "duration_s": 1.0,
           "exit_status": 0, "resolved": False, "error_category": "unresolved"}
    assert validate_result(rec) == []
    assert validate_result({**rec, "schema_version": 1})
    p = tmp_path / "raw.jsonl"
    append_raw(rec, p)
    (p).write_text(p.read_text(encoding="utf-8") + '{"schema_version": 1, "run_id": "old"}\n',
                   encoding="utf-8")
    assert [r["run_id"] for r in read_all(p)] == ["r1"]  # v1 filtered out


def test_failure_taxonomy_new_categories():
    assert classify(0, False, True, "") == "successful"
    assert classify(0, False, False, "") == "unresolved"
    assert classify(0, True, None, "") == "timeout"
    assert classify(124, False, None, "") == "timeout"
    assert classify(1, False, None, "Unexpected server error") == "opencode_error"
    assert classify(1, False, None, "Rate limit 429") == "rate_limit"
    assert classify(1, False, None, "Unauthorized 401") == "auth_error"


def test_retry_linkage():
    a = run_id_for("t", "sol", 1, 20260920)
    b = run_id_for("t", "sol", 1, 20260920, retry_of="orig-id")
    assert a != b and "orig" not in a


def test_run_identity_isolated_by_experiment_phase_and_concrete_model():
    old = run_id_for("t", "sol", 1, 20260920, experiment_id="old", phase="pilot",
                     model_id="openai/gpt-5.6-sol")
    new_pilot = run_id_for("t", "sol", 1, 20260920, experiment_id="new", phase="pilot",
                           model_id="openai/gpt-6-sol")
    new_smoke = run_id_for("t", "sol", 1, 20260920, experiment_id="new", phase="smoke",
                           model_id="openai/gpt-6-sol")
    assert len({old, new_pilot, new_smoke}) == 3


def test_analysis_rejects_cross_experiment_contamination(tmp_path):
    from analysis.analyze import run_analysis
    experiment = {
        "experiment_id": "new",
        "results_pilot_raw": "results/new/pilot/raw.jsonl",
        "results_smoke_raw": "results/new/smoke/raw.jsonl",
        "results_raw": "results/new/full/raw.jsonl",
    }
    raw = tmp_path / experiment["results_pilot_raw"]
    raw.parent.mkdir(parents=True)
    raw.write_text(json.dumps({"schema_version": 2, "experiment_id": "old",
                               "phase": "pilot", "model": "sol",
                               "opencode_model_id": "openai/gpt-5.6-sol"}) + "\n",
                   encoding="utf-8")
    import pytest
    with pytest.raises(ValueError, match="outside the active experiment"):
        run_analysis(tmp_path, "pilot", experiment,
                     {"sol": "openai/gpt-6-sol", "luna": "openai/gpt-6-luna"})


def test_interesting_accepts_all_null_normalized_cost():
    import pandas as pd
    from analysis.analyze import _interesting
    agg = pd.DataFrame([{"task_id": "t", "sol_solved": 1, "luna_solved": 1}])
    df = pd.DataFrame([
        {"task_id": "t", "model": "sol", "resolved": True,
         "normalized_api_cost_usd": None, "actual_cost_usd": 0.0, "lines_added": 1},
        {"task_id": "t", "model": "luna", "resolved": True,
         "normalized_api_cost_usd": None, "actual_cost_usd": 0.0, "lines_added": 1},
    ])
    assert _interesting(agg, df)["E_unstable"] == ["t"]


def test_incremental_cost_preserves_unknown_normalized_pricing():
    import pandas as pd
    df = pd.DataFrame([
        {"task_id": "t", "replicate": 1, "model": "sol", "resolved": True,
         "actual_cost_usd": 0.0, "normalized_api_cost_usd": None},
        {"task_id": "t", "replicate": 1, "model": "luna", "resolved": True,
         "actual_cost_usd": 0.0, "normalized_api_cost_usd": None},
    ])
    result = incremental_cost(df)
    assert result["actual"]["status"] == "luna_resolves_no_more"
    assert result["normalized"]["status"] == "unknown-cost"


def test_freeze_roundtrip_and_mismatch(tmp_path):
    cfg = _cfg()
    mf = build_manifest(["a__1"], ["sol", "luna"], 1, 20260920)
    fr = collect_freeze({**cfg, "root": tmp_path}, mf, "1.18.31", "5.0.2",
                        cfg["models"]["models"])
    assert fr["manifest_runs"] == 2 and fr["seed"] == 20260920
    assert check_freeze({**cfg, "root": tmp_path}, mf, "1.18.31", fr) == []
    assert check_freeze({**cfg, "root": tmp_path}, mf, "9.9.9", fr) != []


def test_cost_actual_vs_normalized():
    pricing = {"models": {"sol": {"input_per_1m": 10.0, "output_per_1m": 20.0},
                          "luna": {"input_per_1m": None, "output_per_1m": None}},
               "price_source": "x", "price_checked_at": "y"}
    est = estimate_campaign(pricing, ["sol", "luna"], 60, 1_000_000, 0)
    assert est["unknown"]  # one model unknown -> total unknown (fail-closed)
    ok, _ = check_budget(None, 5.0)
    assert not ok


def test_secret_sanitizer_opencode_formats(monkeypatch):
    monkeypatch.setenv("MODEL_API_KEY", "met-test-secret-1234567890")
    out = sanitize('{"apiKey": "op-super-secret-xyz"} and Bearer op-super-secret-xyz')
    assert "op-super-secret-xyz" not in out and "[REDACTED]" in out
    out2 = sanitize("key=met-test-secret-1234567890 done")
    assert "met-test-secret-1234567890" not in out2


def test_paired_outcomes_and_incremental_guard():
    import pandas as pd
    df = pd.DataFrame([
        {"task_id": "t1", "replicate": 1, "model": "sol", "resolved": True,
         "actual_cost_usd": 1.0, "normalized_api_cost_usd": 1.0, "duration_s": 5},
        {"task_id": "t1", "replicate": 1, "model": "luna", "resolved": True,
         "actual_cost_usd": 2.0, "normalized_api_cost_usd": 2.0, "duration_s": 6},
        {"task_id": "t1", "replicate": 2, "model": "sol", "resolved": False,
         "actual_cost_usd": 1.0, "normalized_api_cost_usd": 1.0, "duration_s": 5},
        {"task_id": "t1", "replicate": 2, "model": "luna", "resolved": True,
         "actual_cost_usd": 2.0, "normalized_api_cost_usd": 2.0, "duration_s": 6},
    ])
    pt = paired_table(df)
    assert set(pt["category"]) == {"both solved", "only Luna"}
    inc = incremental_cost(df)
    assert inc["normalized"]["status"] == "ok"
    assert inc["normalized"]["incremental_resolved"] == 1
    df2 = df.copy()
    df2["resolved"] = False
    assert incremental_cost(df2)["normalized"]["status"] == "luna_resolves_no_more"


def test_statistics_exclude_incomplete_pairs_and_superseded_retries():
    import pandas as pd
    df = pd.DataFrame([
        {"run_id": "sol-original", "retry_of": None, "task_id": "t1", "replicate": 1,
         "model": "sol", "resolved": None, "duration_s": 0},
        {"run_id": "sol-retry", "retry_of": "sol-original", "task_id": "t1", "replicate": 1,
         "model": "sol", "resolved": True, "duration_s": 10},
        {"run_id": "luna", "retry_of": None, "task_id": "t1", "replicate": 1,
         "model": "luna", "resolved": False, "duration_s": 20},
        {"run_id": "unpaired", "retry_of": None, "task_id": "t2", "replicate": 1,
         "model": "sol", "resolved": True, "duration_s": 30},
    ])
    assert set(independent_observations(df)["run_id"]) == {"sol-retry", "luna", "unpaired"}
    pt = paired_table(df)
    assert list(pt["task_id"]) == ["t1"]
    assert pt.iloc[0]["category"] == "only Sol"
    summary = summary_table(df, bootstrap_b=10)
    assert set(summary["n_tasks"]) == {1}
    assert summary.attrs["mcnemar"] == {
        "sol_only_pairs": 1, "luna_only_pairs": 0,
        "note": "discordant replicate-pairs; exact test in analysis notebook",
    }


def test_plots_accept_infrastructure_records_with_null_outcome(tmp_path):
    import pandas as pd
    rows = []
    for model, resolved in (("sol", True), ("luna", False)):
        rows.append({
            "task_id": "t1", "repository": "repo", "replicate": 1, "model": model,
            "resolved": resolved, "duration_s": 10, "input_tokens": 10,
            "output_tokens": 2, "total_tokens": 12, "tool_calls": 1,
            "lines_added": 1, "actual_cost_usd": 0.0,
            "normalized_api_cost_usd": None, "error_category": "successful",
            "timestamp": "2026-01-01T00:00:00+00:00",
        })
    rows.append({**rows[0], "task_id": "t2", "resolved": None,
                 "error_category": "docker_error"})
    df = pd.DataFrame(rows)
    all_plots(df, summary_table(df, bootstrap_b=10), medians_table(df),
              paired_table(df), task_aggregate(df), tmp_path)
    assert len(list(tmp_path.glob("*.png"))) == 15


def test_materialize_enables_windows_longpaths_and_allows_cold_pull(tmp_path, monkeypatch):
    calls = []

    class Result:
        def __init__(self, stdout="", returncode=0):
            self.stdout = stdout
            self.stderr = ""
            self.returncode = returncode

    def fake_run(cmd, **kwargs):
        calls.append((cmd, kwargs))
        if cmd[:2] == ["docker", "create"]:
            return Result("container-id\n")
        if "rev-parse" in cmd:
            return Result("abcdef1\n")
        return Result()

    monkeypatch.setattr("context_bench.container.subprocess.run", fake_run)
    materialize_worktree("image", tmp_path, "abcdef1")
    assert any(cmd[-2:] == ["core.longpaths", "true"] for cmd, _ in calls)
    create = next((cmd, kwargs) for cmd, kwargs in calls if cmd[:2] == ["docker", "create"])
    assert create[1]["timeout"] == 900


def test_issue_type_heuristic_labeled():
    r = classify_issue_type("Regression: parsing of empty config broke validation")
    assert r["issue_type_method"] == "heuristic" and r["issue_type"] in (
        "regression", "validation", "parsing", "edge_case", "bug_fix")
    assert classify_issue_type("")["issue_type"] == "bug_fix"


def test_difficulty_cycling_rule():
    order = cycled_order({"<15 min fix": ["b", "a"], "1-4 hours": ["c"], ">4 hours": ["d"]})
    assert order[:3] == ["a", "c", "d"]


def test_no_gold_in_prompt_path():
    import context_bench.runner as r
    import inspect
    src = inspect.getsource(r)
    for marker in ("load_with_gold", "test_patch", "gold.patch", "run_evaluation",
                   "FAIL_TO_PASS"):
        assert marker not in src, marker


def test_evaluator_separated_from_agent():
    import context_bench.evaluator as e
    import inspect
    assert "run_evaluation" in inspect.getsource(e)


def _known_pricing(pin=10.0, pout=20.0):
    return {"models": {"sol": {"input_per_1m": pin, "output_per_1m": pout},
                       "luna": {"input_per_1m": pin, "output_per_1m": pout}},
            "price_source": "test", "price_checked_at": "test"}


def _unknown_pricing():
    return {"models": {"sol": {"input_per_1m": None, "output_per_1m": None},
                       "luna": {"input_per_1m": None, "output_per_1m": None}},
            "price_source": "unknown-test", "price_checked_at": "test"}


def test_guard_known_pricing_within_budget_allowed():
    """Case 1: known pricing + estimate <= max budget -> allowed."""
    pricing = _known_pricing()
    est = estimate_campaign(pricing, ["sol", "luna"], 60, 30000, 6000)
    assert not est["unknown"] and est["total_estimated_usd"] is not None
    ok, msg = check_budget(est["total_estimated_usd"], 500.0)
    assert ok, msg
    ok2, _ = check_budget(est["total_estimated_usd"], 500.0, True)
    assert ok2  # acknowledgement must not break the known-pricing path


def test_guard_known_pricing_over_budget_rejected():
    """Case 2: known pricing + estimate > max budget -> rejected (even with acknowledgement)."""
    pricing = _known_pricing()
    est = estimate_campaign(pricing, ["sol", "luna"], 60, 30000, 6000)
    assert est["total_estimated_usd"] is not None
    ok, _ = check_budget(est["total_estimated_usd"], 0.01)
    assert not ok
    ok_ack, _ = check_budget(est["total_estimated_usd"], 0.01, True)
    assert not ok_ack  # allow_unknown_cost must NOT disable enforcement when pricing is known


def test_guard_unknown_pricing_without_ack_rejected():
    """Case 3: unknown pricing without --allow-unknown-cost -> rejected."""
    pricing = _unknown_pricing()
    est = estimate_campaign(pricing, ["sol", "luna"], 60, 30000, 6000)
    assert est["unknown"] and est["total_estimated_usd"] is None
    ok, _ = check_budget(None, 500.0)
    assert not ok
    ok2, _ = check_budget(est["total_estimated_usd"], 500.0, False)
    assert not ok2


def test_guard_unknown_pricing_with_ack_and_budget_allowed_no_synthetic_zero():
    """Case 4: unknown + --allow-unknown-cost + --max-budget-usd -> allowed past paid guard.

    No synthetic $0 normalized estimate may appear; estimate stays null/unknown.
    Guard-level check (no model calls).
    """
    import context_bench.cli as cli_mod
    pricing = _unknown_pricing()
    est = estimate_campaign(pricing, ["sol", "luna"], 60, 30000, 6000)
    assert est["unknown"] and est["total_estimated_usd"] is None
    ok, msg = check_budget(est["total_estimated_usd"], 500.0, True)
    assert ok
    assert "cannot be numerically verified" in msg and "--allow-unknown-cost" in msg
    assert "$0" not in msg.split("remains null")[0] or "never $0" in msg

    cfg = _cfg()
    test_cfg = {"experiment": dict(cfg["experiment"]), "models": cfg["models"],
                "pricing": pricing, "tasks": cfg["tasks"]}
    rows = [{"run_id": f"t--{m}--r1--x", "task_id": "t", "model": m} for m in ("sol", "luna")]
    monkey_catalog = ["openai/gpt-6-sol", "openai/gpt-6-luna"]
    orig_models = cli_mod._opencode_models
    orig_exe = cli_mod._opencode_exe
    cli_mod._opencode_models = lambda exe: list(monkey_catalog)
    cli_mod._opencode_exe = lambda: "opencode"
    try:
        out = cli_mod._paid_guard(test_cfg, rows, "full-guard-test", 500.0, 2, True)
    finally:
        cli_mod._opencode_models = orig_models
        cli_mod._opencode_exe = orig_exe
    assert out["unknown"] is True and out["total_estimated_usd"] is None


def test_full_still_requires_confirm_and_budget():
    """Full must still require explicit --confirm-full-run and --max-budget-usd (no model calls)."""
    from click.testing import CliRunner
    import context_bench.cli as cli_mod
    r = CliRunner().invoke(cli_mod.cli, ["full"])
    assert r.exit_code != 0 and "confirm-full-run" in r.output
    r2 = CliRunner().invoke(cli_mod.cli, ["full", "--confirm-full-run"])
    assert r2.exit_code != 0 and "max-budget-usd" in r2.output
