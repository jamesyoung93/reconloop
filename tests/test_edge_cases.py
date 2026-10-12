"""Regression checks for input validation, audit records, and judge boundaries."""
import json
import runpy
import shutil
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from reconloop import MetricSpec, Param, Target, reconcile
from reconloop.extract import load_targets
from reconloop.guardrails import Policy
from reconloop.judge import LLMJudge, SearchJudge
from reconloop.record import record_filename, write
from reconloop.runners.duckdb_runner import DuckDBRunner
from reconloop.runners.spark_runner import SparkRunner
from reconloop.scoring import score_dir
from reconloop.session import ReconSession


def target(**kwargs):
    return Target(**(dict(target_id="fit", report="report", metric="metric",
                         as_of="2026-01-01", value=100) | kwargs))


def spec():
    return MetricSpec("metric", "SELECT {measure} AS value", {
        "measure": Param("measure", "measure", "old", {"old": "110", "new": "100"})})


@pytest.fixture
def runner():
    result = DuckDBRunner({})
    yield result
    result.con.close()


@pytest.mark.parametrize("bad", [
    {"value": float("nan")}, {"value": float("inf")}, {"confidence": -1},
    {"confidence": float("nan")}, {"split": "typo"}, {"as_of": "2026-01-01'; DROP TABLE x;--"},
    {"as_of": "20260101"}, {"report": ""},
])
def test_invalid_targets_fail_early(bad):
    with pytest.raises(ValueError):
        target(**bad)


@pytest.mark.parametrize("targets", [[], [target(split="holdout")],
                                     [target(), target()], [target(metric="other")]])
def test_invalid_target_sets_cannot_reconcile(targets, runner):
    with pytest.raises(ValueError):
        reconcile(spec(), targets, runner, SearchJudge(), log=lambda *a: None)
    session = ReconSession({"metric": spec()}, targets, runner)
    with pytest.raises(ValueError):
        session.open("report", "metric")


@pytest.mark.parametrize("sql", ["SELECT NULL AS value", "SELECT 1 AS value WHERE FALSE",
                                 "SELECT 1 AS value UNION ALL SELECT 2", "SELECT 1 AS value, 2 AS extra",
                                 "SELECT 'nan'::DOUBLE AS value", "SELECT 1 AS wrong_name"])
def test_duckdb_rejects_invalid_scalar_results(sql, runner):
    with pytest.raises(ValueError):
        runner.run(sql)
    assert sql not in runner.cache


def test_duckdb_handles_quoted_paths_and_identifiers(tmp_path):
    path = tmp_path / "retail's data.csv"
    path.write_text("amount\n12\n", encoding="utf-8")
    db = DuckDBRunner({'sales"data': path})
    try:
        assert db.run('SELECT SUM(amount) AS value FROM "sales""data"') == 12
        assert db.run("SELECT 0 AS value") == 0
    finally:
        db.con.close()


@pytest.mark.parametrize("values,valid", [([], False), ([None], False), ([1, 2], False),
                                         ([float("inf")], False), ([0], True)])
def test_spark_scalar_contract_without_a_cluster(values, valid):
    frame = SimpleNamespace(columns=["value"], take=lambda n: [{"value": v} for v in values][:n])
    spark = SparkRunner(SimpleNamespace(sql=lambda sql: frame))
    if valid:
        assert spark.run("query") == 0
    else:
        with pytest.raises(ValueError):
            spark.run("query")


def test_failing_holdout_is_unresolved_in_both_apis(runner):
    metric = spec()
    targets = [target(), target(target_id="hidden", value=300, split="holdout", as_of="2026-01-02")]
    record = reconcile(metric, targets, runner, SearchJudge(), start={"measure": "new"}, log=lambda *a: None)
    assert record.status == "unresolved"
    assert "Holdout is outside tolerance" in record.residual.note
    session = ReconSession({"metric": metric}, targets, runner)
    assert "300" not in session.open("report", "metric", start={"measure": "new"})
    assert session.close().status == "unresolved"


def test_custom_judge_only_receives_fit_data_and_cannot_mutate_history(runner):
    targets = [target(), target(target_id="hidden", split="holdout", value=123456)]

    class Inspector:
        def propose(self, state, db):
            assert all(t.split == "fit" for t in state.targets)
            for iteration in state.history + [state.last]:
                assert iteration.holdout_variance is None
                assert all(r["split"] == "fit" for r in iteration.per_target)
            state.last.per_target[0]["gold"] = -99
            state.spec.params["measure"].options["old"] = "0"
            return None

    record = reconcile(spec(), targets, runner, Inspector(), log=lambda *a: None)
    assert record.iterations[0].per_target[0]["gold"] == 100
    assert "110" in record.final_query


def test_zero_target_is_unresolved_and_json_is_standard(tmp_path, runner):
    record = reconcile(spec(), [target(value=0)], runner, SearchJudge(), log=lambda *a: None)
    assert record.status == "unresolved"
    write([record], tmp_path)
    data = json.loads((tmp_path / "report__metric.json").read_text(encoding="utf-8"),
                      parse_constant=lambda value: pytest.fail(f"invalid JSON constant: {value}"))
    assert data["residual"]["fit_variance"] is None


@pytest.mark.parametrize("report", ["../outside", "..\\outside", "C:\\outside", "Finance / Café", "a__b"])
def test_record_labels_cannot_escape_output_directory(tmp_path, runner, report):
    record = reconcile(spec(), [target(report=report)], runner, SearchJudge(), log=lambda *a: None)
    out = tmp_path / "out"
    write([record], out)
    files = list(out.iterdir())
    assert len(files) == 2
    assert all(p.is_file() and p.parent == out for p in files)
    assert json.loads((out / record_filename(report, "metric")).read_text(encoding="utf-8"))["report"] == report


def test_bad_sql_is_recorded_as_rejected_even_with_zero_minimum_gain(runner):
    metric = spec()
    metric.params["measure"].options["new"] = "missing_column"
    judge = LLMJudge(lambda prompt: '{"param":"measure","value":"new"}')
    rec = reconcile(metric, [target()], runner, judge, Policy(min_fit_gain=0), max_iter=1, log=lambda *a: None)
    assert rec.iterations[-1].accepted is False
    assert "execution failed" in rec.iterations[-1].reject_reason
    session = ReconSession({"metric": metric}, [target()], runner)
    session.open("report", "metric")
    assert session.try_change("measure", "new", "measure", "trial").startswith("REJECTED")
    assert session.close().final_params == {"measure": "old"}


@pytest.mark.parametrize("reply", ['{"param": ["measure"], "value": "new"}',
                                   '{"param": "measure", "value": {}}',
                                   '{"param": "measure", "value": "new", "rationale": null}'])
def test_bad_llm_field_types_are_rejected(reply, runner):
    record = reconcile(spec(), [target()], runner, LLMJudge(lambda prompt: reply), max_iter=1, log=lambda *a: None)
    assert record.iterations[-1].accepted is False


def test_search_skips_broken_candidate(runner):
    metric = spec()
    metric.params["measure"].options = {"old": "110", "broken": "missing", "new": "100"}
    rec = reconcile(metric, [target()], runner, SearchJudge(), log=lambda *a: None)
    assert rec.status == "reconciled"


def test_session_respects_config_start_and_cannot_discard_open_pair(tmp_path, runner):
    config = tmp_path / "config.toml"
    csv = tmp_path / "targets.csv"
    csv.write_text("target_id,report,metric,as_of,value\nfit,report,metric,2026-01-01,100\n", encoding="utf-8")
    config.write_text('''[targets]
file = "targets.csv"
[start.metric]
measure = "new"
[metrics.metric]
template = "SELECT {measure} AS value"
[metrics.metric.params.measure]
hypothesis = "measure"
default = "old"
[metrics.metric.params.measure.options]
old = "110"
new = "100"
''', encoding="utf-8")
    session = ReconSession.from_config(str(config), runner=runner)
    session.open("report", "metric")
    with pytest.raises(RuntimeError, match="close"):
        session.open("report", "metric")
    assert session.close().start_params == {"measure": "new"}


def test_partial_start_fills_defaults_and_validates(runner):
    metric = spec()
    metric.params["extra"] = Param("extra", "measure", "default", {"default": "0"})
    rec = reconcile(metric, [target()], runner, SearchJudge(), start={"measure": "new"}, log=lambda *a: None)
    assert rec.start_params == {"measure": "new", "extra": "default"}
    with pytest.raises(ValueError, match="unknown"):
        metric.initial_choices({"typo": "new"})


@pytest.mark.parametrize("contents", ["", "wrong,headers\n", "target_id,report,metric,as_of,value\n"])
def test_empty_or_invalid_csv_is_rejected(tmp_path, contents):
    path = tmp_path / "targets.csv"
    path.write_text(contents, encoding="utf-8")
    with pytest.raises(ValueError):
        load_targets(path)


def test_csv_accepts_utf8_bom(tmp_path):
    path = tmp_path / "targets.csv"
    path.write_text("target_id,report,metric,as_of,value\nx,Café,metric,2026-01-01,10\n", encoding="utf-8-sig")
    assert load_targets(path)[0].report == "Café"


def test_missing_or_unresolved_records_do_not_count_as_success(tmp_path, runner):
    rec = reconcile(spec(), [target()], runner, SearchJudge(), log=lambda *a: None)
    write([rec], tmp_path)
    answers = tmp_path / "answers.json"
    answers.write_text(json.dumps({"report/metric": {"params": {"measure": "new"}},
                                   "missing/metric": {"params": {"measure": "new"}}}), encoding="utf-8")
    assert score_dir(tmp_path, answers)["param_accuracy"] == 0.5
    rec.status = "unresolved"
    rec.residual.likely_causes = ["restatement"]
    write([rec], tmp_path)
    answers.write_text(json.dumps({"report/metric": {"params": {"measure": "new"}, "residual": "restatement"}}), encoding="utf-8")
    assert score_dir(tmp_path, answers)["cases_correct"] == "0/1"


def test_pdf_regex_keeps_negative_sign_and_label_capture_groups(monkeypatch):
    from reconloop.extract.pdf_text import extract

    class Document:
        pages = [SimpleNamespace(extract_text=lambda: "Week ending 2026-01-01\nWeekly sales: $-1,234.50")]
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass

    monkeypatch.setitem(sys.modules, "pdfplumber", SimpleNamespace(open=lambda path: Document()))
    rows = extract("fictional.pdf", "report", [{"metric": "metric", "label": r"(Weekly) sales",
                                               "as_of": r"Week ending (\d{4}-\d{2}-\d{2})"}])
    assert rows[0].value == -1234.5


def test_notebook_generates_missing_demo_data(tmp_path, monkeypatch):
    root = Path(__file__).resolve().parents[1]
    demo = tmp_path / "examples" / "fictional_retail"
    demo.mkdir(parents=True)
    for name in ("config.toml", "generate_data.py"):
        shutil.copy(root / "examples" / "fictional_retail" / name, demo / name)
    notebooks = tmp_path / "notebooks"
    notebooks.mkdir()
    monkeypatch.chdir(notebooks)
    result = runpy.run_path(str(root / "notebooks" / "reconcile_with_agent.py"))
    assert (demo / "targets.csv").is_file()
    assert len(result["s"].pairs()) == 3
