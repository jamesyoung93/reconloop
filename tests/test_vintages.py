import json

import pytest

from reconloop import MetricSpec, Param, RatioSpec, Target
from reconloop.revisions import compare_vintages, write_revisions
from reconloop.runners.duckdb_runner import DuckDBRunner
from reconloop.sql import alignment, deduplicate, fragment, latest_partition


@pytest.fixture
def runner():
    db = DuckDBRunner({})
    yield db
    db.con.close()


def test_latest_date_and_cycle_are_selected_as_one_partition(runner):
    runner.con.execute("CREATE TABLE snapshots(snapshot_date DATE, cycle INT, amount INT)")
    runner.con.execute("INSERT INTO snapshots VALUES ('2026-01-01',9,999),('2026-01-02',1,10),('2026-01-02',2,20),('2026-01-02',2,30),('2026-01-03',1,200)")
    query = latest_partition("snapshots", ["snapshot_date", "cycle", "amount"], ["snapshot_date", "cycle"],
                             as_of="2026-01-02", cutoff_column="snapshot_date")
    assert runner.run(f"SELECT SUM(amount) AS value FROM ({query}) s") == 50


def test_latest_partition_per_feed_is_not_global(runner):
    runner.con.execute("CREATE TABLE feeds(feed VARCHAR, cycle INT, amount INT)")
    runner.con.execute("INSERT INTO feeds VALUES ('a',1,100),('a',2,10),('b',1,20)")
    query = latest_partition("feeds", ["feed", "cycle", "amount"], ["cycle"], as_of="2026-01-02", partition_by=["feed"])
    assert runner.run(f"SELECT SUM(amount) AS value FROM ({query}) s") == 30


def test_category_grain_retains_distinct_category_membership(runner):
    runner.con.execute("CREATE TABLE events(event_id INT, category VARCHAR, row_id INT, amount INT)")
    runner.con.execute("INSERT INTO events VALUES (1,'A',1,10),(1,'A',2,10),(1,'B',3,10),(2,'A',4,20)")
    cols = ["event_id", "category", "row_id", "amount"]
    category = deduplicate("events", cols, ["event_id", "category"], ["row_id"])
    event = deduplicate("events", cols, ["event_id"], ["row_id"])
    assert runner.run(f"SELECT SUM(amount) AS value FROM ({category}) s") == 40
    assert runner.run(f"SELECT SUM(amount) AS value FROM ({event}) s") == 30


def test_alignment_effective_dates_are_half_open_and_missing_rows_survive(runner):
    runner.con.execute("CREATE TABLE facts(account INT, day DATE, amount INT)")
    runner.con.execute("INSERT INTO facts VALUES (1,'2026-01-01',10),(1,'2026-02-01',20),(2,'2026-02-01',30)")
    runner.con.execute("CREATE TABLE mapping(account INT, territory VARCHAR, valid_from DATE, valid_to DATE)")
    runner.con.execute("INSERT INTO mapping VALUES (1,'North','2026-01-01','2026-02-01'),(1,'South','2026-02-01',NULL)")
    query = alignment("facts", "mapping", ["account", "day", "amount"], "account", "day")
    assert runner.run(f"SELECT SUM(amount) AS value FROM ({query}) s WHERE territory='North'") == 10
    assert runner.run(f"SELECT SUM(amount) AS value FROM ({query}) s WHERE territory='South'") == 20
    assert runner.run(f"SELECT COUNT(*) AS value FROM ({query}) s WHERE territory IS NULL") == 1


@pytest.mark.parametrize("option", [
    {"type": "latest_partition", "source": "facts; DROP TABLE x", "columns": ["amount"], "order_by": ["cycle"]},
    {"type": "deduplicate", "source": "facts", "columns": ["amount"], "keys": [], "order_by": ["cycle"]},
    {"type": "unknown"},
])
def test_structured_fragments_reject_invalid_identifiers_and_grains(option):
    with pytest.raises(ValueError):
        fragment(option, "2026-01-01")


def test_revision_comparison_keeps_non_vintage_choices_fixed(runner, tmp_path):
    metric = MetricSpec("metric", "SELECT {vintage} * {measure} AS value", {
        "vintage": Param("vintage", "data_vintage", "published", {"published": "100", "refreshed": "110"}),
        "measure": Param("measure", "measure", "raw", {"raw": "1", "net": "0.5"})})
    ts = [Target("t", "report", "metric", "2026-01-01", 50)]
    evidence = compare_vintages(metric, ts, runner, parameter="vintage", before="published", after="refreshed", choices={"measure": "net"})
    assert evidence[0]["before"] == 50 and evidence[0]["after"] == 55
    assert evidence[0]["delta"] == 5
    assert evidence[0]["relative_change"] == pytest.approx(.1)
    assert evidence[0]["before_params"]["measure"] == evidence[0]["after_params"]["measure"] == "net"
    write_revisions(evidence, tmp_path)
    assert json.loads((tmp_path / "revisions.json").read_text())[0]["status"] == "revised"


def test_ratio_revision_detects_hidden_component_changes_and_zero_baseline(runner):
    metric = MetricSpec("metric", "", {"v": Param("v", "data_vintage", "old", {"old": "1", "new": "2"})},
                        ratio=RatioSpec("SELECT 10 * {v} AS value", "SELECT 100 * {v} AS value"))
    ts = [Target("t", "report", "metric", "2026-01-01", .1)]
    e = compare_vintages(metric, ts, runner, parameter="v", before="old", after="new")[0]
    assert e["delta"] == 0 and e["status"] == "revised"
    assert e["components"]["numerator"]["delta"] == 10
    metric.ratio = None
    metric.template = "SELECT ({v} - 1) AS value"
    e = compare_vintages(metric, ts, runner, parameter="v", before="old", after="new")[0]
    assert e["relative_change"] is None
