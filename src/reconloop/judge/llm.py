from __future__ import annotations

import json
import re
from typing import Callable

from ..hypotheses import CATALOG
from ..schema import Change
from .base import JudgeState

PROMPT = """You are reconciling a computed metric against figures from a trusted report.
Your job is to propose ONE change to the metric definition that best explains the gap.
You do not compute anything. The numbers below were computed by code.

Metric: {metric}
Report: {report}
What the report says its rule is: {stated_rule}

Current definition: {current}
Allowed choices (you may only pick from these):
{space}

Fit results for the current definition (gold vs computed, relative variance):
{rows}
Mean absolute variance: {fit:.2%}. Shape of the gap: {pattern}.

Changes already tried: {tried}
Previous accepted changes: {accepted}

Reasons a gap can exist (your hypothesis must be one of these keys):
{catalog}

Rules:
- Prefer the change the stated rule points to. Use the shape of the gap as evidence
  (a constant % gap suggests a definitional or restatement difference; a growing one suggests late data).
- If no allowed change is defensible, answer with "param": null and explain the most likely
  remaining cause in "rationale".

Answer with JSON only:
{{"param": "<param or null>", "value": "<option>", "hypothesis": "<key>", "rationale": "<one or two sentences>"}}
"""


class LLMJudge:
    """Model-driven judge. `complete` is any function that takes a prompt and returns text.

    Examples:
        LLMJudge(lambda p: my_client.chat(p))
        LLMJudge(databricks_endpoint_call)   # wrap a serving endpoint
    """

    name = "llm"

    def __init__(self, complete: Callable[[str], str]):
        self.complete = complete
        self.last_prompt = ""
        self.last_reply = ""

    def build_prompt(self, state: JudgeState) -> str:
        spec = state.spec
        space = "\n".join(f"- {k} [{p.hypothesis}]: " + ", ".join(
            f"{o}" + (f" ({p.describe[o]})" if o in p.describe else "") for o in p.options)
            for k, p in spec.params.items())
        rows = "\n".join(f"- {r['as_of']}: gold {r['gold']:,.0f} vs computed {r['computed']:,.0f} ({r['rel']:+.2%})"
                         for r in state.last.per_target if r["split"] == "fit")
        accepted = [f"{i.change.param}: {i.change.old} -> {i.change.new}" for i in state.history if i.change and i.accepted]
        t0 = state.targets[0] if state.targets else None
        return PROMPT.format(metric=spec.name, report=t0.report if t0 else "", stated_rule=t0.stated_rule if t0 else "",
                             current=spec.describe(state.params), space=space, rows=rows, fit=state.last.fit_variance,
                             pattern=state.residual_pattern, tried=sorted(state.tried) or "none",
                             accepted=accepted or "none",
                             catalog="\n".join(f"- {k}: {v}" for k, v in CATALOG.items()))

    def propose(self, state: JudgeState, runner) -> Change | None:
        self.last_prompt = self.build_prompt(state)
        self.last_reply = self.complete(self.last_prompt)
        m = re.search(r"\{.*\}", self.last_reply, re.S)
        if not m:
            return None
        try:
            d = json.loads(m.group(0))
        except json.JSONDecodeError:
            return None
        if not isinstance(d, dict) or not d.get("param"):
            return None
        if any(not isinstance(d.get(k, ""), str) for k in ("param", "value", "hypothesis", "rationale")):
            return Change(param="", old="", new="", hypothesis="",
                          rationale="INVALID: proposal fields must be strings", proposed_by=self.name)
        p = state.spec.params.get(d["param"])
        if p is None or d.get("value") not in p.options:
            return Change(param=str(d.get("param")), old="", new=str(d.get("value")),
                          hypothesis=str(d.get("hypothesis", "")), rationale="INVALID: " + str(d.get("rationale", "")),
                          proposed_by=self.name)
        return Change(param=d["param"], old=state.params[d["param"]], new=d["value"],
                      hypothesis=d.get("hypothesis", p.hypothesis), rationale=d.get("rationale", ""),
                      proposed_by=self.name)
