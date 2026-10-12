from __future__ import annotations

import re

from ..schema import Change
from .base import JudgeState
from .search import SearchJudge


class StatedRuleJudge:
    """Follows what the report says it does, then falls back to search.

    For each parameter, if the report's stated rule mentions one of an option's keywords
    and that option is not the current one, propose it. This is the cheap, deterministic
    version of what an LLM judge does by reading the rule; it is also a good baseline to
    check that a model judge is beating something simple.
    """

    name = "stated_rule"

    def __init__(self, fallback=None):
        self.fallback = fallback or SearchJudge()

    def propose(self, state: JudgeState, runner) -> Change | None:
        rule = (state.targets[0].stated_rule if state.targets else "").lower()
        for pname, p in state.spec.params.items():
            for opt, words in p.keywords.items():
                if opt == state.params[pname] or (pname, opt) in state.tried:
                    continue
                hit = next((w for w in words if re.search(r"\b" + re.escape(w.lower()) + r"\b", rule)), None)
                if hit:
                    return Change(param=pname, old=state.params[pname], new=opt, hypothesis=p.hypothesis,
                                  rationale=f"Report states '{hit}'.", proposed_by=self.name)
        # Do not let the fallback undo a choice the report explicitly states.
        pinned = set(state.tried)
        for pname, p in state.spec.params.items():
            cur_words = p.keywords.get(state.params[pname], [])
            if any(re.search(r"\b" + re.escape(w.lower()) + r"\b", rule) for w in cur_words):
                pinned |= {(pname, o) for o in p.options if o != state.params[pname]}
        from dataclasses import replace
        return self.fallback.propose(replace(state, tried=pinned), runner)
