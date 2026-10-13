from dataclasses import replace
import json
from pathlib import Path
import runpy
import shutil

import pytest

from reconloop import load_config, run_config
from reconloop.batch import select_pairs
from reconloop.cli import main
from reconloop.extract.csv_targets import write_targets
from reconloop.judge import StatedRuleJudge
from reconloop.scoring import score_dir
from reconloop.session import ReconSession


@pytest.fixture
def config(tmp_path):
    example = Path(__file__).resolve().parents[1] / "examples" / "multi_metric"
    for name in ("generate_data.py", "config.toml"):
        shutil.copy(example / name, tmp_path / name)
    runpy.run_path(str(tmp_path / "generate_data.py"), run_name="__main__")
    return tmp_path / "config.toml"


def test_three_metric_demo_reconciles_and_scores_all_definitions(config, tmp_path):
    records = run_config(config, judge=StatedRuleJudge(), out_dir=tmp_path / "out", log=lambda *a: None)
    assert {r.metric for r in records} == {"net_sales", "orders", "return_rate"}
    assert all(r.status == "reconciled" and r.residual.holdout_variance < r.tolerance for r in records)
    assert score_dir(tmp_path / "out", config.parent / "answers.json")["cases_correct"] == "3/3"
    assert "3 metrics; 3 reconciled" in (tmp_path / "out" / "report.md").read_text(encoding="utf-8")


def test_shared_parameter_groups_are_independent(config):
    _, specs, _ = load_config(config)
    specs["orders"].params["window"].options["agent_added"] = "TRUE"
    assert "agent_added" not in specs["net_sales"].params["window"].options


def test_batch_filters_and_factory_isolate_state(config):
    calls = []
    def factory(report, metric):
        calls.append((report, metric))
        return StatedRuleJudge()
    records = run_config(config, metrics=["orders", "return_rate"], reports=["retail_dashboard"],
                         judge_factory=factory, log=lambda *a: None)
    assert [r.metric for r in records] == ["orders", "return_rate"]
    assert calls == [(r.report, r.metric) for r in records]
    with pytest.raises(ValueError, match="unknown"):
        run_config(config, metrics=["typo"])


def test_cli_metric_filter(config, tmp_path):
    out = tmp_path / "selected"
    main(["run", str(config), "--metric", "orders", "--out", str(out)])
    assert len(list(out.glob("*.json"))) == 1
    assert json.loads(next(out.glob("*.json")).read_text())["metric"] == "orders"


def test_agent_queue_progress_and_metric_specific_changes(config):
    session = ReconSession.from_config(str(config))
    assert len(session.pending_pairs()) == 3
    while session.pending_pairs():
        assert "RECONCILING" in session.open_next("retail_dashboard")
        active = next(row for row in session.progress() if row["status"] == "active")
        with pytest.raises(RuntimeError):
            session.open_next()
        session.try_change("window", "fiscal", "time_window", "Fiscal week in report.")
        session.try_change("stores", "comparable", "universe", "Comparable stores in report.")
        if active["metric"] == "net_sales":
            session.try_change("measure", "net", "measure", "Net sales in report.")
        assert session.close().status == "reconciled"
    assert session.open_next() == "ALL PAIRS CLOSED"
    assert all(row["status"] == "reconciled" for row in session.progress())
    with pytest.raises(ValueError, match="already closed"):
        session.open("retail_dashboard", "orders")


def test_unconfigured_metric_or_unit_mismatch_cannot_silently_disappear(config):
    cfg, specs, targets = load_config(config)
    with pytest.raises(ValueError, match="no metric spec"):
        select_pairs(specs, targets + [replace(targets[0], metric="missing")])
    with pytest.raises(ValueError, match="units"):
        select_pairs(specs, [replace(t, unit="wrong") if t.metric == "orders" else t for t in targets])


def test_multiple_csv_sources_preserve_all_metrics(config):
    cfg, specs, targets = load_config(config)
    write_targets([t for t in targets if t.metric == "orders"], config.parent / "orders.csv")
    write_targets([t for t in targets if t.metric != "orders"], config.parent / "others.csv")
    text = config.read_text().replace('[targets]\nfile = "targets.csv"',
        '[[targets.sources]]\ntype = "csv"\nfile = "orders.csv"\n'
        '[[targets.sources]]\ntype = "csv"\nfile = "others.csv"')
    config.write_text(text)
    assert len(load_config(config)[2]) == 15


def test_incomplete_pdf_config_writes_diagnostics_and_cannot_run(tmp_path):
    pytest.importorskip("pdfplumber")
    canvas = pytest.importorskip("reportlab.pdfgen.canvas")
    c = canvas.Canvas(str(tmp_path / "report.pdf"))
    c.drawString(50, 700, "No KPI present")
    c.save()
    config = tmp_path / "config.toml"
    config.write_text('''[[targets.sources]]
type = "pdf"
file = "report.pdf"
report = "dashboard"
ocr = "never"
[[targets.sources.patterns]]
metric = "sales"
label = "Sales"
as_of_value = "2026-01-08"
''')
    with pytest.raises(SystemExit) as exc:
        main(["extract", str(config), "--out", str(tmp_path / "out")])
    assert exc.value.code == 2
    assert json.loads((tmp_path / "out" / "extraction.json").read_text())["issues"]
    with pytest.raises(ValueError, match="needs review"):
        load_config(config)


def test_pdf_source_reconciles_multiple_metrics_with_provenance(tmp_path):
    pytest.importorskip("pdfplumber")
    canvas = pytest.importorskip("reportlab.pdfgen.canvas")
    c = canvas.Canvas(str(tmp_path / "report.pdf"))
    c.drawString(50, 700, "Sales 100")
    c.drawString(50, 650, "Orders 20")
    c.save()
    config = tmp_path / "config.toml"
    config.write_text('''[[targets.sources]]
type = "pdf"
file = "report.pdf"
report = "dashboard"
ocr = "never"
[[targets.sources.patterns]]
metric = "sales"
label = "Sales"
as_of_value = "2026-01-08"
[[targets.sources.patterns]]
metric = "orders"
label = "Orders"
as_of_value = "2026-01-08"
[metrics.sales]
template = "SELECT 100 AS value"
[metrics.orders]
template = "SELECT 20 AS value"
''')
    records = run_config(config, log=lambda *a: None)
    assert {r.metric for r in records} == {"sales", "orders"}
    assert all(r.status == "reconciled" for r in records)
    assert all(r.iterations[0].per_target[0]["source_file"] == "report.pdf" for r in records)
