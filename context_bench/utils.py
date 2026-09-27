"""Shared utilities: hashing, secrets sanitizer, filesystem helpers, timestamps."""
from __future__ import annotations

import hashlib
import os
import re
from datetime import datetime, timezone
from pathlib import Path

SECRET_ENV_VARS = ("MODEL_API_KEY", "OPENAI_API_KEY")
_SECRET_PATTERNS: list[re.Pattern] = []


def _compile_secret_patterns() -> list[re.Pattern]:
    pats: list[re.Pattern] = []
    for var in SECRET_ENV_VARS:
        val = os.environ.get(var, "")
        if val and len(val) >= 8:
            pats.append(re.compile(re.escape(val)))
    # generic long-token shape (sk-..., met-...) redaction as defence in depth
    pats.append(re.compile(r"\bsk-[A-Za-z0-9-_]{8,}\b"))
    return pats


def sanitize(text: str) -> str:
    """Redact secret values from log text. Never prints full keys.

    Covers: env-var values, VAR= assignments, OpenCode/provider config shapes
    ("apiKey": "...", 'api_key': '...', bearer headers), and sk-* tokens.
    """
    global _SECRET_PATTERNS
    _SECRET_PATTERNS = _compile_secret_patterns()
    out = text
    for p in _SECRET_PATTERNS:
        out = p.sub("[REDACTED]", out)
    for var in SECRET_ENV_VARS:
        out = re.sub(rf"({var}\s*=\s*).+", r"\1[REDACTED]", out)
    # OpenCode / provider config formats: {"apiKey": "secret"}, api_key='secret'
    out = re.sub(r'(?i)("api_?key"\s*:\s*")[^"]+(")', r"\1[REDACTED]\2", out)
    out = re.sub(r"(?i)('api_?key'\s*:\s*')[^']+(')", r"\1[REDACTED]\2", out)
    out = re.sub(r"(?i)\b(api_?key\s*=\s*)[^\s,;]+", r"\1[REDACTED]", out)
    # Authorization: Bearer <token>
    out = re.sub(r"(?i)\b(bearer\s+)[A-Za-z0-9\-._~+/=]{8,}", r"\1[REDACTED]", out)
    return out


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def count_stats(text: str) -> dict:
    """bytes / characters / words + fixed measurement tokens (char/4)."""
    from .tokens import measure

    m = measure(text)
    return {
        "bytes": len(text.encode("utf-8")),
        "characters": len(text),
        "words": len(text.split()),
        "measured_tokens": m["measured_tokens"],
    }
