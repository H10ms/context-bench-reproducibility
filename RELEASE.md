# Public release and data provenance

This repository is a new, clean publication snapshot. The original Git history,
account state, transcripts, patches, evaluator logs, worktrees, caches, smoke,
pilot and unrelated historical experiments are not distributed.

The original source HEAD was `cb60a0388f15704171076c478c996ece48703ff9`;
the freeze references harness commit `6d7298fc2f777a4af23f09c3778940339821125e`.
These are provenance identifiers in the original repository, not commits promised
to exist in this clean repository. The harness, original analysis, configs and
tests are copied byte for byte; their hashes are in `RELEASE_PROVENANCE.json`.
New publication scripts and packaging configuration do not change the frozen analysis.
The original HEAD differs from the frozen harness commit only in the freeze JSON;
the published harness and analysis source therefore also match that frozen commit.

## Raw export

All 136 records and their ordering are retained. For publication only:

| Field | Transformation | Affected records |
|---|---|---:|
| `transcript_path` | `null` | 136 |
| `agent_stderr_path` | `null` | 136 |
| `patch_path` | `null` | 136 |
| `evaluator_log_path` | `null` when present | 121 |
| `opencode_session_id` | `null` | 136 |
| `provider_errors` | generic HTTP 403 message; list length retained | 15 |

No statistical input field, task/model/repetition ID, `run_id`, `retry_of`,
timestamp, verdict, token count, duration, patch metric or prompt hash was changed.
These invariants were compared against the private source during publication.
There are no added or removed records. Error response headers and request tracing
identifiers are omitted. The original private raw is not included.

Original private raw SHA-256 (historical reference, **not** a public-file checksum):
`1a388a6b49b34b1231dee0c8400736650524062cfd71a9ccf22534a33f43d171`.

Public raw SHA-256:
`7511fccf5ff07b9f0312aa845d04b012af98403cd8b257047bcc3cfc7e6d656c`.

The original `article_analysis/article_summary.json` and `table08_invariants.csv`
are retained as historical artifacts. Their raw, pilot and smoke hashes describe
the original campaign, not files that can all be checked in this release.
Use `SHA256SUMS` for files actually distributed here.

## Two different manifest hashes

Unchanged freeze file SHA-256:
`c52033eec533d238aa08d1429a67a772b07050ca40b17fd36ab8447f0464887f`.

Manifest **file-byte** SHA-256:
`8407c864f4e6acb8b9d37b00c78d9a03b420db54ad8de850ee03683785f6d43e`.

Manifest **canonical-content** SHA-256 from the freeze:
`636d9b7042c5a02f24eba7540d428893303d0e4590ee78f3c0723f8ddf490acd`.

The latter hashes each parsed row serialized with Python
`json.dumps(row, sort_keys=True) + "\n"`, preserving row order. It is not the
hash reported by a file hashing utility. `scripts/verify_release.py` checks both.
`.gitattributes` prevents checkout newline conversion from changing frozen bytes.

## What the release can prove

Checksums establish file integrity relative to this published snapshot. They do
not independently timestamp preregistration, authenticate provider identity, prove
the historical Git commits, or independently verify evaluator verdicts.
Recalculation checks the recorded experiment and its published statistics.
The original analysis notes include campaign narrative based on logs omitted here;
that narrative cannot all be independently reconstructed from aggregate raw alone.
