from __future__ import annotations

from ..compare import evaluate, score
from ..schema import Change
from .base import JudgeState


class SearchJudge:
    """Greedy one-change-at-a-time search over the declared option space."""

    name = "search"

    def __init__(self, min_gain: float = 1e-4):
        self.min_gain = min_gain

    def propose(self, state: JudgeState, runner) -> Change | None:
        current = state.last.fit_variance
        best = None
        for pname, p in state.spec.params.items():
            for opt in p.options:
                if opt == state.params[pname] or (pname, opt) in state.tried:
                    continue
                trial = dict(state.params, **{pname: opt})
                try:
                    v = score(evaluate(runner, state.spec, trial, state.targets))
                except Exception:
                    # An unusable candidate must not stop the other declared choices.
                    continue
                gain = current - v
                if gain > self.min_gain and (best is None or gain > best[0]):
                    best = (gain, pname, opt, p.hypothesis, v)
        if best is None:
            return None
        gain, pname, opt, hyp, v = best
        return Change(param=pname, old=state.params[pname], new=opt, hypothesis=hyp,
                      rationale=f"Largest single reduction in fit variance ({current:.2%} -> {v:.2%}).",
                      proposed_by=self.name)
