"""Task selection for the GPT-6 Sol-vs-Luna experiment (schema v2).

Rules (declared BEFORE any model run; see docs/TASK_SELECTION.md):
1. 30 main tasks, 6 repos x 5. Reserves: >=3 per repo (18 total).
2. Reuse the 20 previously validated IDs for django/matplotlib/scikit-learn/sympy:
   they were fixed before ANY model output existed (results/raw.jsonl never
   created), so keeping them cannot bias toward observed outcomes.
3. New repos (xarray, sphinx): deterministic difficulty-cycled picks from
   sorted instance_ids. Cycle order across official `difficulty` buckets
   ['<15 min fix', '15 min - 1 hour', '1-4 hours', '>4 hours'] guarantees a
   mix including hard tasks. Main = first 5 cycled; reserves = next 3.
4. Extra 4th-repo reserves: first sorted unused instance_id per repo.
5. NEVER uses gold fields (patch/test_patch/FAIL_TO_PASS). Only
   instance_id/repo/difficulty/problem_statement (latter is agent-visible).
6. issue_type is a keyword HEURISTIC over the issue text, labeled as such.
"""
from __future__ import annotations

DIFFICULTY_BUCKETS = ["<15 min fix", "15 min - 1 hour", "1-4 hours", ">4 hours"]

# (label, keywords in lowercased issue text). First match wins; heuristic only.
ISSUE_TYPE_RULES: list[tuple[str, tuple[str, ...]]] = [
    ("regression", ("regression", "used to work", "broke in", "previously")),
    ("validation", ("validation", "validate", "invalid input", " ValueError", "raises")),
    ("parsing", ("pars", "tokeniz", "lexer", "syntax", "decode")),
    ("api_behavior", ("api", "deprecat", "signature", "argument", "keyword argument")),
    ("edge_case", ("edge case", "corner case", "empty", "boundary", "off-by-one")),
    ("algorithmic_data", ("algorithm", "performance", "slow", "memory", "complexity", "incorrect result")),
    ("framework_internal", ("internal", "registry", "dispatch", "metaclass", "descriptor")),
    ("bug_fix", ()),
]


def classify_issue_type(problem_statement: str) -> dict:
    """Keyword heuristic. Returns label + matched keyword + heuristic flag."""
    text = (problem_statement or "").lower()
    for label, keywords in ISSUE_TYPE_RULES:
        for kw in keywords:
            if kw and kw in text:
                return {"issue_type": label, "issue_type_method": "heuristic",
                        "issue_type_evidence": kw}
    return {"issue_type": "bug_fix", "issue_type_method": "heuristic",
            "issue_type_evidence": "fallback: no rule matched"}


def cycled_order(instance_ids_by_bucket: dict[str, list[str]]) -> list[str]:
    """Deterministic round-robin across difficulty buckets (sorted within bucket)."""
    buckets = [b for b in DIFFICULTY_BUCKETS if b in instance_ids_by_bucket]
    order: list[str] = []
    i = 0
    while len(order) < sum(len(v) for v in instance_ids_by_bucket.values()):
        progressed = False
        for b in buckets:
            bucket = sorted(instance_ids_by_bucket[b])
            if i < len(bucket) and bucket[i] not in order:
                order.append(bucket[i])
                progressed = True
        i += 1
        if not progressed:
            break
    return order


def manifest_id(task_id: str, model: str, replicate: int, seed: int) -> str:
    import hashlib

    h = hashlib.sha256(f"{seed}|{task_id}|{model}|{replicate}".encode()).hexdigest()[:12]
    return f"{task_id}--{model}--r{replicate}--{h}"
