"""Baselines every forecast must beat: no-information, base rate and momentum.

The classical forecasters are deliberately small, but they must still answer the
question that was asked.  A five-session forecast is mostly a short-term signal;
a twenty-session forecast needs a slower trend input.  Keeping that conditioning
here also gives the LLM crowd a deterministic anchor that cannot forget the
horizon mentioned in its prompt.
"""
from __future__ import annotations

import math


def logistic(x: float) -> float:
    return 1 / (1 + math.exp(-max(min(x, 50), -50)))


def climatology(_features: dict | None = None, horizon: int | None = None) -> float:
    return 0.5


def base_rate(history: list[int], prior: float = 0.5, strength: float = 10) -> float:
    """Shrunk historical outperformance frequency."""
    return (sum(history) + prior * strength) / (len(history) + strength)


def _bounded_signal(signal: float, scale: float, limit: float = 0.2) -> float:
    """Map a return signal to a deliberately weak, bounded probability."""
    return min(0.7, max(0.3, 0.5 + limit * math.tanh(scale * signal)))


def momentum(features: dict, scale: float = 6.0, horizon: int | None = None) -> float:
    """Horizon-conditioned continuation baseline.

    Five sessions use the recent relative move.  Twenty sessions blend the
    20-session and 60-session relative moves and require persistent relative
    direction to move the probability further.  The optional horizon keeps the
    old one-argument baseline API compatible with existing callers and tests.
    """
    if horizon not in (5, 20):
        excess = features.get("excess_ret_20d")
        if excess is None:
            return 0.5
        return 0.3 + 0.4 * logistic(scale * excess)
    short = features.get("excess_ret_5d")
    medium = features.get("excess_ret_20d")
    if horizon == 5:
        if short is None and medium is None:
            return 0.5
        signal = 0.75 * (short or 0.0) + 0.25 * (medium or 0.0)
        consistency = features.get("trend_consistency_20d")
        if consistency is not None:
            signal += 0.02 * (consistency - 0.5)
    else:
        if medium is None:
            return 0.5
        long = features.get("excess_ret_60d")
        signal = 0.65 * medium + 0.35 * (long if long is not None else medium)
        consistency = features.get("trend_consistency_60d")
        if consistency is not None:
            signal += 0.04 * (consistency - 0.5)
    return _bounded_signal(signal, scale)


def reversal(features: dict, scale: float = 10.0, horizon: int | None = None) -> float:
    """Mean-reversion baseline with a weaker, slower twenty-session view."""
    excess = features.get("excess_ret_5d")
    if horizon == 20:
        excess = features.get("excess_ret_20d")
        scale *= 0.35
    if excess is None:
        return 0.5
    return _bounded_signal(-excess, scale, limit=0.18)


BASELINES = {"climatology": climatology, "momentum": momentum, "reversal": reversal}
