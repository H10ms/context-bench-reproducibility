# Reproducibility

## 1. Check integrity without dependencies

```sh
python scripts/verify_release.py
```

The script checks all `SHA256SUMS` entries, the frozen config bytes, prompt wrapper,
source snapshot and canonical manifest hash. Linux/macOS may additionally use
`sha256sum -c SHA256SUMS` (or `shasum -a 256 -c SHA256SUMS`). In PowerShell,
`Get-FileHash results/experiments/gpt6-sol-vs-luna-swbench-v1/full/raw.jsonl -Algorithm SHA256`
checks the public raw file. Expected hashes and the historical/private distinction
are in [RELEASE.md](RELEASE.md).

## 2. Recalculate without model calls

Use Python 3.11+ and a virtual environment; see README for activation.

```sh
python -m pip install -r requirements-analysis.txt
python scripts/reproduce.py
```

No model/API calls, Docker calls, benchmark downloads or provider authentication
occur during recalculation. Output goes to `reproduced/`; `--output` can select
another directory. The original figures remain unchanged. Newly plotted figures
use the same measurements with a simpler presentation, so their image bytes differ.
Dependencies here pin the release validation environment, not an unrecorded
historical environment. The recorded campaign used Python 3.13.14 on Windows.

### Selection and denominators

1. Validate full phase, experiment identity, exact models and deterministic manifest.
2. Validate unique run IDs, preceding retry parents, no branches, and matching
   task/model/repetition across each retry link.
3. Use the original `independent_observations`: last record in each retry chain.
   Check that all 120 planned combinations occur exactly once (60 per model).
4. Main run-level rates include six null-verdict empty patches in the denominator:
   Sol 33/60, Luna 23/60. Do not replace the primary denominator with 57.
5. Frozen paired analysis drops null verdicts: 55 complete pairs, with categories
   21 both / 11 only Sol / 2 only Luna / 21 neither.
6. Frozen `summary_table` takes each model's maximum non-null success across
   repetitions per task, then retains tasks with data for both models: 29 tasks.
   It resamples these tasks 2000 times using seed 20260920. The RNG sequence also
   includes per-model bootstrap intervals before the paired difference interval;
   preserving this sequence is necessary for the reported exact endpoints.
7. Bootstrap effect is Luna minus Sol: −13.7931 pp, 95% CI [−31.0345, 0.0].
   This estimates the difference in at-least-one-success rates, not run success rates.
8. Exact McNemar uses 13 discordant replicate pairs (11 vs 2), with a two-sided
   binomial probability 0.0224609375. It treats replicate pairs as independent,
   although two repeats share task difficulty. Report that limitation.

The script compares the numeric source article tables with their recomputed values,
allowing only their published rounding. `table08_invariants.csv` is historical:
its private raw/smoke/pilot hashes cannot be checked from public data; see RELEASE.
The two log-derived counts for malformed patches and patch application failures in
table06 cannot be independently reconstructed from raw fields and are explicitly
excluded from verification; the script reports this limitation.
No code is supplied claiming to recreate the original article layout pixel for pixel.

## 3. Original harness and optional fresh experiment

The shared harness is included in `context_bench/`; unchanged analysis lives in
`analysis/`. `config/`, the freeze and manifest specify the historical experiment.
Original technical setup checks are in `scripts/setup.ps1` and `scripts/setup.sh`.
For harness development (separate from the minimal analysis installation):

```sh
python -m pip install -e ".[dev]"
python -m pytest
```

A fresh campaign additionally needs the recorded OpenCode 1.18.31, SWE-bench
5.0.2, Git, Docker with suitable benchmark images, and provider access to the exact
model IDs. Installation commands for recorded tool versions include
`npm install -g opencode-ai@1.18.31` and `python -m pip install swebench==5.0.2`.
Authenticate through the provider's own login flow; never put credentials in Git.
Future availability of the tools/models and identical provider behavior are not guaranteed.

Run a new campaign in a separate working copy with a **new experiment ID** and new
manifest/results/runs/freeze paths in `config/experiment.yaml`. Do not append new
runs to this publication's raw file. Preserve the public source snapshot and record
all deviations (dependencies, images, flags, models, prompt and dates).

After configuring that separate campaign, the original CLI provides `doctor`,
`validate`, `manifest`, `smoke`, `pilot`, `freeze`, `full`, `rerun`, and `analyze`.
Use `python -m context_bench --help` and each command's `--help` for launch guards.
`smoke`, `pilot`, `full`, and `rerun` can invoke models and consume paid resources.
Freeze only after configuration and harness changes are committed. The clean release
has new Git history; the historical freeze SHA must not be presented as the new run's SHA.

The legacy `python -m context_bench analyze --scope full` is also included, but its
task-level summary is not the article's primary 33/60 versus 23/60 table. Prefer
`scripts/reproduce.py` for article verification and clearer denominator reporting.

See [docs/METHODOLOGY.md](docs/METHODOLOGY.md),
[docs/THREATS_TO_VALIDITY.md](docs/THREATS_TO_VALIDITY.md), and
[docs/OPENCODE_HARNESS.md](docs/OPENCODE_HARNESS.md) for the original notes.
References in those historical notes to archives, run directories and local logs
describe the source project; those artifacts are intentionally absent here.
