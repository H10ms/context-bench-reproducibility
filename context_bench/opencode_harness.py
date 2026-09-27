"""OpenCode harness helpers (pure: no subprocess, no model calls at import).

Observed against opencode-ai 1.18.31 on 2026-09-20 (see docs/OPENCODE_HARNESS.md):
- non-interactive: `opencode run --dir D --model P/M --variant V --agent A
  --format json --title T "prompt"`
- `--format json` emits one JSON object per line: step_start / text /
  tool_use / step_finish / error.
- usage lives in step_finish parts: tokens{total,input,output,reasoning,
  cache{write,read}} + cost. Multiple step_finish events per run: SUM them.
- tool counts: count tool_use events by tool name (bash/edit/write/read/...).
- session id: `sessionID` field of any event -> `opencode export <id>` archive.
- exit codes observed: 0 = finished (reason stop/tool-calls), 1 = server/model
  error (e.g. unknown model -> {"type":"error",...}). Timeout has no CLI flag:
  the harness kills the process (exit 124 marker, error_category timeout).
"""
from __future__ import annotations

import json

TOOL_USE = "tool_use"
STEP_FINISH = "step_finish"


def build_command(opencode_exe: str, workdir: str, model_id: str, variant: str,
                  agent: str, title: str, prompt_via_stdin: bool = True) -> list[str]:
    """Byte-identical for both models except --model. Prompt passed via stdin
    (argv stays short and out of process listings)."""
    cmd = [opencode_exe, "run",
           "--dir", workdir,
           "--model", model_id,
           "--agent", agent,
           "--format", "json",
           "--title", title]
    if variant:
        cmd += ["--variant", variant]
    if not prompt_via_stdin:
        cmd += ["-"]  # placeholder; caller appends prompt text instead
    return cmd


def parse_events(lines: list[str]) -> dict:
    """Fold --format json events into usage/cost/tool/session summary.

    Unknown event types are counted, never crash. All numbers default to None
    when absent (never invented).
    """
    total_in = total_out = total_reasoning = 0
    cache_read = cache_write = 0
    cost = 0.0
    saw_tokens = saw_cost = False
    tools: dict[str, int] = {}
    texts: list[str] = []
    session_id: str | None = None
    finish_reasons: list[str] = []
    errors: list[str] = []
    n_events = 0
    for ln in lines:
        ln = ln.strip()
        if not ln:
            continue
        try:
            ev = json.loads(ln)
        except json.JSONDecodeError:
            continue
        n_events += 1
        if not session_id and isinstance(ev.get("sessionID"), str):
            session_id = ev["sessionID"]
        t = ev.get("type")
        part = ev.get("part", {}) if isinstance(ev.get("part"), dict) else {}
        if t == TOOL_USE:
            name = part.get("tool", "unknown")
            tools[name] = tools.get(name, 0) + 1
        elif t == "text":
            txt = part.get("text", "")
            if isinstance(txt, str) and txt:
                texts.append(txt)
        elif t == STEP_FINISH:
            if isinstance(part.get("reason"), str):
                finish_reasons.append(part["reason"])
            tok = part.get("tokens", {}) if isinstance(part.get("tokens"), dict) else {}
            if any(k in tok for k in ("input", "output", "total", "reasoning")):
                saw_tokens = True
                total_in += int(tok.get("input", 0) or 0)
                total_out += int(tok.get("output", 0) or 0)
                total_reasoning += int(tok.get("reasoning", 0) or 0)
                cache = tok.get("cache", {}) if isinstance(tok.get("cache"), dict) else {}
                cache_read += int(cache.get("read", 0) or 0)
                cache_write += int(cache.get("write", 0) or 0)
            if "cost" in part and part["cost"] is not None:
                try:
                    cost += float(part["cost"])
                    saw_cost = True
                except (TypeError, ValueError):
                    pass
        elif t == "error":
            err = ev.get("error", {})
            errors.append(json.dumps(err)[:500])
    n_tools = sum(tools.values())
    return {
        "n_events": n_events,
        "session_id": session_id,
        "finish_reasons": finish_reasons,
        "errors": errors,
        "input_tokens": total_in if saw_tokens else None,
        "output_tokens": total_out if saw_tokens else None,
        "reasoning_tokens": total_reasoning if saw_tokens else None,
        "total_tokens": (total_in + total_out) if saw_tokens else None,
        "cached_read_tokens": cache_read if saw_tokens else None,
        "cached_write_tokens": cache_write if saw_tokens else None,
        "actual_cost_usd": cost if saw_cost else None,
        "tool_counts": tools,
        "tool_calls": n_tools,
        "shell_commands": tools.get("bash", 0),
        "files_read": tools.get("read", 0) or None,
        "assistant_text_tail": "\n".join(texts[-3:])[-2000:],
    }
