"""Judges propose the next change. They never compute variances themselves.

- SearchJudge: deterministic baseline. Tries every allowed single change and picks
  the one that closes the most gap. No model needed; useful as a reference and
  to check that an LLM judge is actually adding value.
- StatedRuleJudge: follows keywords in the report's stated rule, then searches.
- LLMJudge: reasons from the stated rule, the residual shape and the history to
  pick ONE change before anything runs. Plug in any model through `complete()`.
"""
from .base import Judge, JudgeState
from .search import SearchJudge
from .llm import LLMJudge
from .stated_rule import StatedRuleJudge

__all__ = ["Judge", "JudgeState", "SearchJudge", "LLMJudge", "StatedRuleJudge"]
