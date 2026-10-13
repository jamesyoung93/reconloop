"""Write reconciliation records as JSON (for machines) and Markdown (for people)."""
from __future__ import annotations

import json
from math import isfinite
from pathlib import Path
from urllib.parse import quote

from .schema import ReconRecord, CompoundChange, change_items


def record_filename(report: str, metric: str) -> str:
    # Encode separators and delimiter characters; report labels cannot escape out_dir.
    def component(value):
        return quote(value, safe="").replace("_", "%5F").replace(".", "%2E")
    # Preserve the original readable filenames for ordinary identifiers.
    if all(v and v.isascii() and v.replace("_", "").isalnum() and "__" not in v
           and not v.startswith("_") and not v.endswith("_") for v in (report, metric)):
        return f"{report}__{metric}.json"
    return f"encoded-{component(report)}__{component(metric)}.json"


def _json_safe(value):
    if isinstance(value, float) and not isfinite(value):
        return None
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_json_safe(v) for v in value]
    return value


def write(records: list[ReconRecord], out_dir: str | Path) -> Path:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    for r in records:
        (out / record_filename(r.report, r.metric)).write_text(
            json.dumps(_json_safe(r.to_dict()), indent=2, allow_nan=False), encoding="utf-8")
    md = out / "report.md"
    md.write_text(to_markdown(records), encoding="utf-8")
    return md


def to_markdown(records: list[ReconRecord]) -> str:
    lines = ["# Reconciliation report", ""]
    for report in sorted({r.report for r in records}):
        members = [r for r in records if r.report == report]
        counts = {status: sum(r.status == status for r in members)
                  for status in ("reconciled", "explained_residual", "unresolved")}
        lines.append(f"**{report}**: {len(members)} metrics; " + ", ".join(f"{n} {s}" for s, n in counts.items()) + ".")
    lines.append("")
    lines += ["| Report | Metric | Status | Fit variance | Holdout | Changes |", "|---|---|---|---|---|---|"]
    for r in records:
        n = sum(1 for i in r.iterations if i.accepted)
        h = f"{r.residual.holdout_variance:.2%}" if r.residual.holdout_variance is not None else "–"
        lines.append(f"| {r.report} | {r.metric} | {r.status} | {r.residual.fit_variance:.2%} | {h} | {n} |")
    for r in records:
        lines += ["", f"## {r.report} · {r.metric}", "",
                  f"Status: **{r.status}**. {r.residual.note}", "",
                  f"Start: `{r.start_params}`  ", f"Final: `{r.final_params}`", "", "| Step | Change | Reason | Fit | Holdout | Outcome |",
                  "|---|---|---|---|---|---|"]
        for i in r.iterations:
            if i.change is None:
                lines.append(f"| {i.step} | start | – | {i.fit_variance:.2%} | {fmt(i.holdout_variance)} | – |")
                continue
            outcome = "accepted" if i.accepted else f"rejected: {i.reject_reason}"
            changes = "; ".join(f"{c.param}: {c.old} → {c.new}" for c in change_items(i.change))
            reasons = "; ".join(f"{c.hypothesis}: {c.rationale}" for c in change_items(i.change))
            if isinstance(i.change, CompoundChange):
                reasons += f"; Joint reason: {i.change.rationale}"
            lines.append(f"| {i.step} | {changes} | {reasons} | "
                         f"{i.fit_variance:.2%} | {fmt(i.holdout_variance)} | {outcome} |")
        final = next(i for i in reversed(r.iterations) if i.accepted is not False)
        component_rows = [row for row in final.per_target if row.get("components")]
        if component_rows:
            lines += ["", "| Period | Split | Numerator | Denominator | Scale | Ratio |",
                      "|---|---|---|---|---|---|"]
            for row in component_rows:
                c = row["components"]
                lines.append(f"| {row['as_of']} | {row['split']} | {c['numerator']:.8g} | {c['denominator']:.8g} | {c['scale']:g} | {row['computed']:.8g} |")
        lines += ["", "Final query (first as-of date):", "", "```sql", r.final_query, "```"]
    return "\n".join(lines) + "\n"


def fmt(x):
    return "–" if x is None else f"{x:.2%}"
