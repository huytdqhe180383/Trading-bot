"""
Estimate agent token costs for this repository.

Rates are per 1M tokens. API rates produce USD estimates; Codex rates
produce Codex credit estimates.
"""

from __future__ import annotations

import argparse
from typing import Mapping


BASELINE_INPUT_TOKENS = 55_802
BASELINE_OUTPUT_TOKENS = 10_000

API_USD_RATES: dict[str, tuple[float, float]] = {
    "gpt-5.4-mini": (0.75, 4.50),
    "gpt-5.4": (2.50, 15.00),
    "gpt-5.5": (5.00, 30.00),
}

CODEX_CREDIT_RATES: dict[str, tuple[float, float]] = {
    "gpt-5.4-mini": (18.75, 113.00),
    "gpt-5.3-codex": (43.75, 350.00),
    "gpt-5.4": (62.50, 375.00),
    "gpt-5.5": (125.00, 750.00),
}


def estimate_agent_cost(
    *,
    input_tokens: int,
    output_tokens: int,
    input_rate_per_million: float,
    output_rate_per_million: float,
) -> float:
    """Return the cost for one model/rate pair."""
    return (
        (input_tokens / 1_000_000) * input_rate_per_million
        + (output_tokens / 1_000_000) * output_rate_per_million
    )


def _estimate_group(
    *,
    input_tokens: int,
    output_tokens: int,
    rates: Mapping[str, tuple[float, float]],
) -> dict[str, float]:
    return {
        model: estimate_agent_cost(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            input_rate_per_million=input_rate,
            output_rate_per_million=output_rate,
        )
        for model, (input_rate, output_rate) in rates.items()
    }


def estimate_all_models(
    *,
    input_tokens: int = BASELINE_INPUT_TOKENS,
    output_tokens: int = BASELINE_OUTPUT_TOKENS,
) -> dict[str, dict[str, float]]:
    """Estimate API USD and Codex credit costs for the baseline model set."""
    return {
        "api_usd": _estimate_group(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            rates=API_USD_RATES,
        ),
        "codex_credits": _estimate_group(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            rates=CODEX_CREDIT_RATES,
        ),
    }


def _print_estimates(estimates: dict[str, dict[str, float]]) -> None:
    print("API USD")
    for model, cost in estimates["api_usd"].items():
        print(f"  {model}: ${cost:.3f}")

    print("\nCodex credits")
    for model, credits in estimates["codex_credits"].items():
        print(f"  {model}: {credits:.2f} credits")


def main() -> None:
    parser = argparse.ArgumentParser(description="Estimate agent token costs.")
    parser.add_argument("--input-tokens", type=int, default=BASELINE_INPUT_TOKENS)
    parser.add_argument("--output-tokens", type=int, default=BASELINE_OUTPUT_TOKENS)
    args = parser.parse_args()

    estimates = estimate_all_models(
        input_tokens=args.input_tokens,
        output_tokens=args.output_tokens,
    )
    _print_estimates(estimates)


if __name__ == "__main__":
    main()
