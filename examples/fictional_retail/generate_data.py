"""Generate the fictional demo: a small grocery chain's daily store sales and three
"trusted reports", each built with a different hidden definition.

    python generate_data.py          # writes sales.csv, targets.csv, answers.json

The reports:
  finance_report  fiscal week (Sun-Sat), comparable stores, net of returns, ex-tax
  merch_report    calendar week (Mon-Sun), all stores, gross, ex-tax
  ops_report      same as finance, but its older weeks were restated up 1.5% after
                  publication. No definition explains that, so the loop should stop with
                  an explained residual rather than fudge the definition to absorb it.

Everything is invented. Seeded, so the output is identical every run.
"""
from __future__ import annotations

import csv
import json
import random
from datetime import date, timedelta
from pathlib import Path

HERE = Path(__file__).parent
rng = random.Random(7)

STORES = [f"S{i:02d}" for i in range(1, 41)]
COMPARABLE = set(STORES[:30])                  # 10 newer stores are not comparable
START, DAYS = date(2026, 1, 3), 7 * 11          # Saturday start, 11 weeks of days
DOW = {0: 0.85, 1: 0.88, 2: 0.92, 3: 1.0, 4: 1.15, 5: 1.35, 6: 1.25}   # Mon..Sun
TAX, RETURNS = 0.08, 0.04


def sales_rows():
    base = {s: rng.uniform(8_000, 16_000) * (0.7 if s not in COMPARABLE else 1.0) for s in STORES}
    for d in range(DAYS):
        day = START + timedelta(days=d)
        trend = 1 + 0.012 * d / 7                 # steady growth so week definitions matter
        for s in STORES:
            g = base[s] * DOW[day.weekday()] * trend * rng.uniform(0.9, 1.1)
            yield {"date": day.isoformat(), "store_id": s, "comparable": s in COMPARABLE,
                   "gross": round(g, 2), "returns": round(g * RETURNS * rng.uniform(0.6, 1.4), 2),
                   "tax": round(g * TAX, 2)}


def weekly(rows, as_of: date, window: str, stores: str, measure: str, tax: str) -> float:
    lo, hi = (as_of - timedelta(days=6), as_of) if window == "fiscal" else (as_of - timedelta(days=5), as_of + timedelta(days=1))
    tot = 0.0
    for r in rows:
        d = date.fromisoformat(r["date"])
        if not (lo <= d <= hi) or (stores == "comparable" and not r["comparable"]):
            continue
        v = r["gross"] - (r["returns"] if measure == "net" else 0) + (r["tax"] if tax == "incl" else 0)
        tot += v
    return tot


REPORTS = {
    "finance_report": dict(params=dict(window="fiscal", stores="comparable", measure="net", tax="ex"),
                           rule="Fiscal week (Sun-Sat), comparable stores, net of returns, excluding tax.", restate=0.0),
    "merch_report": dict(params=dict(window="calendar", stores="all", measure="gross", tax="ex"),
                         rule="Calendar week, all stores, gross sales.", restate=0.0),
    "ops_report": dict(params=dict(window="fiscal", stores="comparable", measure="net", tax="ex"),
                       rule="Comparable stores, net sales, fiscal week.", restate=0.015),
}


def main():
    rows = list(sales_rows())
    with open(HERE / "sales.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader(); w.writerows(rows)
    weeks = [START + timedelta(days=7 * k) for k in range(1, 9)]          # 8 Saturdays
    targets, answers = [], {}
    for name, rep in REPORTS.items():
        for k, wk in enumerate(weeks):
            split = "holdout" if k >= 6 else "fit"
            v = weekly(rows, wk, **rep["params"])
            if split == "fit":                                             # older weeks restated, recent ones not yet
                v *= 1 + rep["restate"]
            targets.append({"target_id": f"{name}-{wk}", "report": name, "metric": "weekly_sales", "as_of": wk.isoformat(),
                            "value": round(v, 0), "unit": "currency", "stated_rule": rep["rule"],
                            "source_file": f"{name}.pdf", "page": str(k + 1), "split": split, "confidence": 1.0})
        answers[f"{name}/weekly_sales"] = {"params": rep["params"], "residual": "restatement" if rep["restate"] else "none"}
    with open(HERE / "targets.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(targets[0]))
        w.writeheader(); w.writerows(targets)
    (HERE / "answers.json").write_text(json.dumps(answers, indent=2))
    print(f"wrote sales.csv ({len(rows)} rows), targets.csv ({len(targets)} targets), answers.json")


if __name__ == "__main__":
    main()
