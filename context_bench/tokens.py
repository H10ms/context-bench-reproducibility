"""Single fixed token-measurement instrument.

We deliberately do NOT use provider-specific tokenizers as the authoritative
scale: the experiment needs one identical 1k/8k/32k ruler for both models.
Instrument: ceil(characters / 4). tiktoken cl100k_base is recorded
opportunistically for reference only.
"""
from __future__ import annotations

import math


def measure(text: str) -> dict:
    chars = len(text)
    measured = math.ceil(chars / 4) if chars else 0
    out = {"measured_tokens": measured, "characters": chars, "words": len(text.split())}
    try:
        import tiktoken  # type: ignore

        enc = tiktoken.get_encoding("cl100k_base")
        out["tiktoken_cl100k"] = len(enc.encode(text))
    except Exception:
        out["tiktoken_cl100k"] = None
    return out


def within_tolerance(actual: int, target: int, pct: float) -> bool:
    if target <= 0:
        return actual == 0
    return abs(actual - target) <= target * pct / 100.0
