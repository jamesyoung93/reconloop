"""Generate entirely fictional snapshots, category memberships, and dated alignments."""
import csv
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent


def write_csv(name, rows):
    with (HERE / name).open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main():
    facts, targets = [], []
    for snapshot, cycle in [("2026-01-31", 1), ("2026-01-31", 2), ("2026-02-07", 1)]:
        for period, day in enumerate((7, 14, 21, 28), 1):
            events = [(1, 1, "Focus", 30, ["Category A", "Category B"]),
                      (2, 1, "Other", 20, ["Category A"]),
                      (3, 2, "Focus", 50, ["Category B"]),
                      (4, 2, "Other", 100, ["Category A"])]
            if snapshot == "2026-02-07":
                events[0] = (1, 1, "Focus", 36, ["Category A", "Category B"])
                events.append((5, 2, "Other", 10, ["Category A"]))
            for event, account, product, amount, categories in events:
                for category in categories:
                    for repeat in range(2):
                        facts.append(dict(row_id=len(facts) + 1, event_id=period * 10 + event,
                                          category=category, account=account, event_date=f"2026-01-{day:02d}",
                                          product=product, amount=amount * period * (0.9 if cycle == 1 and snapshot == "2026-01-31" else 1),
                                          snapshot_date=snapshot, cycle=cycle))
    write_csv("facts.csv", facts)
    assignments = []
    for vintage in ("2026-01-01", "2026-02-01"):
        for account in (1, 2):
            assignments.append(dict(account=account, territory="North" if account == (1 if vintage == "2026-01-01" else 2) else "South",
                                    valid_from="2025-01-01", valid_to="2027-01-01", alignment_date=vintage))
    write_csv("assignments.csv", assignments)
    values = {"total_volume": 200, "category_volume": 150, "category_share": .2,
              "territory_volume": 50, "territory_share": .6}
    answers = {}
    for metric, value in values.items():
        total = metric == "total_volume"
        territory = metric.startswith("territory")
        share = metric.endswith("share")
        rule = "Publication snapshot; " + ("all categories, once per event" if total else "Category A, once per category")
        if territory:
            rule += "; North territory with publication alignment"
        choices = dict(data_vintage="published", category_filter="all" if total else "selected",
                       deduplication="event" if total else "event_category", mapping="dated",
                       territory_filter="north" if territory else "all")
        if territory:
            choices["alignment_vintage"] = "published"
        answers[f"operations_dashboard/{metric}"] = {"params": choices}
        for period, day in enumerate((7, 14, 21, 28), 1):
            targets.append(dict(target_id=f"{metric}-{period}", report="operations_dashboard", metric=metric,
                                as_of=f"2026-01-{day:02d}", value=value if share else value * period,
                                unit="fraction" if share else "count", stated_rule=rule,
                                split="holdout" if period == 4 else "fit"))
    write_csv("targets.csv", targets)
    (HERE / "answers.json").write_text(json.dumps(answers, indent=2), encoding="utf-8")
    print(f"Generated five metrics across four periods in {HERE}")


if __name__ == "__main__":
    main()
