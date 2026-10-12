"""Checks every proposed change must pass before it is accepted.

The point is to close gaps for reasons a stakeholder would accept, not to hit numbers.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import isfinite

from .hypotheses import CATALOG
from .metricspec import MetricSpec
from .schema import Change


@dataclass
class Policy:
    require_named_hypothesis: bool = True
    require_declared_option: bool = True
    holdout_tolerance: float = 0.0005  # holdout variance may not worsen by more than this (0.05 points)
    min_fit_gain: float = 1e-4         # a change must actually help on the fit set
    max_changes: int = 6               # too many edits = suspicious; stop and ask a human
    min_consistency_gain: float = 0.5  # or: cut the period-to-period spread of the gap by this share


def spread(rows: list[dict]) -> float:
    from statistics import pstdev
    rels = [r["rel"] for r in rows if r.get("split", "fit") == "fit"]
    if any(not isfinite(x) for x in rels):
        return float("inf")
    return pstdev(rels) if len(rels) > 1 else 0.0


def check(change: Change, spec: MetricSpec, fit_before: float, fit_after: float,
          hold_before: float | None, hold_after: float | None, n_accepted: int, policy: Policy,
          rows_before: list[dict] | None = None, rows_after: list[dict] | None = None) -> str:
    """Return '' if the change is acceptable, otherwise the reason it is rejected."""
    if not isfinite(fit_after) or (hold_after is not None and not isfinite(hold_after)):
        return "relative variance is undefined for a nonzero result against a zero target"
    if change.rationale.startswith("INVALID"):
        return "judge proposed an option outside the declared space"
    if policy.require_named_hypothesis and change.hypothesis not in CATALOG:
        return f"hypothesis '{change.hypothesis}' is not in the catalog"
    p = spec.params.get(change.param)
    if policy.require_declared_option and (p is None or change.new not in p.options):
        return "option is not declared in the metric spec"
    if p is not None and change.hypothesis != p.hypothesis:
        return f"hypothesis '{change.hypothesis}' does not match the parameter's declared reason '{p.hypothesis}'"
    if fit_before - fit_after < policy.min_fit_gain:
        # A gap that becomes constant across periods is more explainable than a smaller noisy one
        # (e.g. the true definition plus a restatement). Allow it only if the holdout does not get worse.
        sb, sa = spread(rows_before or []), spread(rows_after or [])
        consistent = sb > 0 and (sb - sa) / sb >= policy.min_consistency_gain
        hold_ok = hold_before is None or hold_after is None or hold_after <= hold_before + 1e-9
        if not (consistent and hold_ok):
            return "does not reduce the fit variance or make the gap more consistent"
    if hold_before is not None and hold_after is not None and hold_after > hold_before + policy.holdout_tolerance:
        return "worsens the holdout; likely fitting noise"
    if n_accepted >= policy.max_changes:
        return "too many changes; stop and review by hand"
    return ""
