"""Fictional duplicate events: a share matches even while both components double."""
import csv
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent


def write(name, rows):
    with (HERE / name).open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main():
    events, targets = [], []
    for period, day in enumerate((7, 14, 21, 28), 1):
        date = f"2026-01-{day:02d}"
        for event, category, amount in [(1, "A", 30), (2, "A", 70), (3, "B", 100)]:
            row = dict(event_id=period * 10 + event, event_date=date, category=category, amount=amount * period)
            events.extend([row, dict(row)])
        for metric, value in [("category_volume", 100*period), ("total_volume", 200*period), ("category_share", .5)]:
            targets.append(dict(target_id=f"{metric}-{period}", report="category_dashboard", metric=metric,
                                as_of=date, value=value, unit="fraction" if metric.endswith("share") else "count",
                                split="holdout" if period == 4 else "fit"))
    write("events.csv", events)
    write("targets.csv", targets)
    answers = {f"category_dashboard/{m}": {"params": {"grain": "event"}} for m in
               ("category_volume", "total_volume", "category_share")}
    (HERE / "answers.json").write_text(json.dumps(answers, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
