"""Generate three KPIs for one fictional dashboard; run from any directory."""
import csv
from datetime import date, timedelta
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent


def main():
    rows = []
    start = date(2026, 1, 1)
    for day in range(42):
        for store in range(3):
            gross = 1000 + day * 37 + store * 190
            rows.append(dict(date=(start + timedelta(days=day)).isoformat(), comparable=store < 2,
                             gross=gross, returns=round(gross * (0.02 + day * 0.0005 + store * 0.01), 2),
                             orders=20 + day * 2 + store * 7))
    with (HERE / "sales.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    targets, answers = [], {}
    for k in range(1, 6):
        end = start + timedelta(days=7 * k)
        selected = [r for r in rows if end - timedelta(days=6) <= date.fromisoformat(r["date"]) <= end and r["comparable"]]
        values = dict(net_sales=sum(r["gross"] - r["returns"] for r in selected),
                      orders=sum(r["orders"] for r in selected),
                      return_rate=sum(r["returns"] for r in selected) / sum(r["gross"] for r in selected))
        for metric, value in values.items():
            targets.append(dict(target_id=f"{metric}-{end}", report="retail_dashboard", metric=metric,
                                as_of=end.isoformat(), value=value,
                                unit={"net_sales": "currency", "orders": "count", "return_rate": "fraction"}[metric],
                                stated_rule="Fiscal week, comparable stores, net sales; returns divided by gross for return rate.",
                                split="holdout" if k == 5 else "fit"))
            params = dict(window="fiscal", stores="comparable")
            if metric == "net_sales":
                params["measure"] = "net"
            answers[f"retail_dashboard/{metric}"] = dict(params=params, residual="none")
    with (HERE / "targets.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(targets[0]))
        writer.writeheader()
        writer.writerows(targets)
    (HERE / "answers.json").write_text(json.dumps(answers, indent=2), encoding="utf-8")
    print("Generated 3 metrics across 5 periods (including one holdout period).")


if __name__ == "__main__":
    main()
