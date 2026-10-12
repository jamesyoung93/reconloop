from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from ..metricspec import MetricSpec
from ..schema import Change, Iteration, Target


@dataclass
class JudgeState:
    spec: MetricSpec
    params: dict[str, str]
    targets: list[Target]            # fit targets only; the judge never sees the holdout
    last: Iteration
    history: list[Iteration]
    tried: set[tuple[str, str]]      # (param, option) pairs already tried
    residual_pattern: str


class Judge(Protocol):
    name: str

    def propose(self, state: JudgeState, runner) -> Change | None:
        """Return one change to try, or None if there is nothing defensible left."""
        ...
