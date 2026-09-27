# OPENCODE_HARNESS — recon findings (opencode-ai 1.18.31, 2026-09-20, Windows 10)

## Installation
`opencode` was NOT on PATH. npm registry has no `opencode` / `@sst/opencode`
(anymore); the current package is **`opencode-ai`** (installed version
1.18.31 via `npm install -g opencode-ai`).

## Non-interactive run
`opencode run --dir <workdir> --model <provider/model> --variant medium
--agent build --format json --title <run_id>` + prompt on **stdin**.
Proven with `opencode/muse-spark-1.3-contributor-free`: exit 0, cost 0.

## Model selection
`-m/--model provider/model`. Config `model` key equivalent. CLI flag wins.

## Reasoning effort
No universal flag. Provider-specific **`--variant`** (OpenAI built-ins:
none/minimal/low/medium/high/xhigh) or config
`provider.<p>.models.<m>.options.reasoningEffort`. Harness passes the SAME
`--variant medium` to both models; per-run metadata records the mapping, and
smoke will reveal immediately if a model rejects it (no silent fallback).

## Tools / permissions
Default: allow-all. Verified headless: `read`, `write`, `bash` tools execute
in `opencode run` with NO approval prompts (probe created a file and ran
`echo` successfully). No `--auto` flag needed; config `permission` untouched
so both models face identical policy.

## Usage / cost / logs
`--format json` emits one JSON object per line: `step_start`, `text`,
`tool_use{tool,input,output}`, `step_finish{tokens{total,input,output,
reasoning,cache{write,read}}, cost}`, `error`. Multiple step_finish events
per run are SUMMED. `sessionID` in every event → `opencode export <id>`
archived best-effort. `opencode stats` exists for aggregate checks.

## Exit codes / timeout
Observed: 0 = finished (`reason` stop/tool-calls); 1 = server/model error
(`{"type":"error",...}`, e.g. unknown model). No CLI timeout flag → harness
`subprocess` timeout (exit marker 124, `timeout: true`).

## Network isolation model
The OpenCode process MUST reach its provider (network allowed for the
harness). The evaluated repo worktree runs with `--network none` semantics
at the container stage and the prompt forbids network use; shell tools get
no proxy/env to reach GitHub. Documented limitation: a determined agent
could still exfiltrate via the provider channel only as text — it cannot
`git fetch` future commits or browse the web from the sandbox.

## Model availability on this machine
Both target models are available through the OpenAI provider authenticated via
ChatGPT Plus. The active experiment uses the exact IDs `openai/gpt-6-sol` and
`openai/gpt-6-luna`; it does not use `-fast` variants. The remaining shared
settings are agent `build`, variant `medium`, format `json`, and timeout 1800
seconds.

The older `openai/gpt-5.6-sol`/GPT-6 Astra harness records are historical. They
are retained in the legacy artifact locations documented in the README and are
not inputs to active Sol/Luna runs or analysis.
