"""Fictional metadata and targets for the configuration discovery workflow."""
import argparse
import csv
import json
from pathlib import Path

from reconloop import Target
from reconloop.extract.csv_targets import write_targets


def generate(out):
    out.mkdir(parents=True, exist_ok=False)
    schema = [dict(name="day", data_type="date"), dict(name="net_sales", data_type="double"),
              dict(name="orders", data_type="integer"), dict(name="raw_volume", data_type="double")]
    (out / "schema.json").write_text(json.dumps(schema, indent=2), encoding="utf-8")
    with (out / "dictionary.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(["table", "column", "description", "unit"])
        writer.writerows([["facts", "net_sales", "Sales after returns", "currency"],
                         ["facts", "orders", "Completed orders", "count"],
                         ["facts", "raw_volume", "Unadjusted source volume", "source_units"]])
    targets = []
    for index, day in enumerate(["2026-01-07", "2026-01-14", "2026-01-21", "2026-01-28"], 1):
        for metric, value, unit in [("sales", 100*index, "currency"), ("orders", 10*index, "count")]:
            targets.append(Target(f"{metric}-{index}", "operations", metric, day, value, unit=unit,
                                   stated_rule="Calendar day totals", split="holdout" if index == 4 else "fit"))
    write_targets(targets, out / "targets.csv")
    return out


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    print(generate(parser.parse_args().out))
