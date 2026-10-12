"""The fixed list of reasons two honest numbers can disagree.

Every change the loop makes must name one of these. A change that cannot be tied
to a named, plausible business reason is a fudge, and the guardrails reject it.
Extend this list for your domain, but keep each entry something a stakeholder
would recognise and accept as a real definitional choice.
"""

CATALOG: dict[str, str] = {
    "time_window": "Different period definition: fiscal vs calendar week, rolling vs fixed, cut-off day.",
    "universe": "Different population: which accounts, stores, customers or entities are counted.",
    "basket": "Different scope of what is counted: products, categories, segments, indications.",
    "measure": "Different measure construction: gross vs net, with or without tax, returns, discounts.",
    "deduplication": "Records counted once vs every time they appear (multi-mapping, repeats).",
    "mapping": "Different hierarchy or assignment: which territory, region or owner a record rolls to.",
    "restatement": "The source was revised after the report was published.",
    "late_data": "Records that arrive after the cut-off and change recent periods.",
    "source": "A different or partial source: a feed the report uses that the platform does not have.",
}

# Residual patterns and the causes they usually point to (used when the loop stops short).
RESIDUAL_HINTS: dict[str, list[str]] = {
    "level_shift": ["restatement", "source", "measure"],
    "drift": ["late_data", "restatement", "mapping"],
    "noisy": ["mapping", "deduplication", "late_data"],
}


def validate(hypothesis: str) -> bool:
    return hypothesis in CATALOG
