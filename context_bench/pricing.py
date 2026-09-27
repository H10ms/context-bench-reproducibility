"""Cost estimation + budget guard. Unknown prices stay unknown (null)."""
from __future__ import annotations


def per_run_estimate(pricing: dict, model_key: str, exp_in: int, exp_out: int) -> dict:
    entry = (pricing.get("models") or {}).get(model_key, {})
    pin = entry.get("input_per_1m")
    pout = entry.get("output_per_1m")

    # Context tokens are input tokens; use expected input/output knobs.
    unknown = pin is None or pout is None
    cost = None if unknown else (exp_in / 1e6) * pin + (exp_out / 1e6) * pout
    return {
        "model": model_key,
        "expected_input_tokens": exp_in,
        "expected_output_tokens": exp_out,
        "input_per_1m": pin,
        "output_per_1m": pout,
        "estimated_usd": cost,
        "unknown": unknown,
        "price_source": pricing.get("price_source"),
        "price_checked_at": pricing.get("price_checked_at"),
    }


def estimate_campaign(pricing: dict, model_keys: list[str], n_runs_per_model: int,
                      exp_in: int, exp_out: int) -> dict:
    per_model = [per_run_estimate(pricing, k, exp_in, exp_out) for k in model_keys]
    total = None if any(p["unknown"] for p in per_model) else sum(
        p["estimated_usd"] * n_runs_per_model for p in per_model
    )
    return {
        "per_model_per_run": per_model,
        "n_runs_per_model": n_runs_per_model,
        "total_estimated_usd": total,
        "unknown": total is None,
    }


def check_budget(total_estimate: float | None, max_budget_usd: float | None,
                 allow_unknown_cost: bool = False) -> tuple[bool, str]:
    if max_budget_usd is None:
        return True, "no budget cap set"
    if total_estimate is None:
        if allow_unknown_cost:
            return True, (
                "normalized pricing unknown; budget cannot be numerically verified; "
                "proceeding because --allow-unknown-cost was explicitly supplied "
                f"(max-budget-usd ${max_budget_usd:.2f} recorded as launch parameter only, "
                "not verified; normalized estimate remains null/unknown, never $0)"
            )
        return False, (
            "cannot verify budget: pricing unknown. "
            "Fill config/pricing.yaml or pass explicit acknowledgement."
        )
    if total_estimate > max_budget_usd:
        return False, f"estimate ${total_estimate:.2f} exceeds cap ${max_budget_usd:.2f}"
    return True, f"estimate ${total_estimate:.2f} within cap ${max_budget_usd:.2f}"
