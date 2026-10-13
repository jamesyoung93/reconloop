import json
from pathlib import Path
import runpy
import shutil

import pytest

from reconloop import load_config, run_config
from reconloop.cli import main
from reconloop.config import build_runner
from reconloop.judge import StatedRuleJudge
from reconloop.jobs import run_job
from reconloop.revisions import revisions_config
from reconloop.scoring import score_dir


@pytest.fixture
def config(tmp_path):
    example = Path(__file__).resolve().parents[1] / "examples" / "versioned_metrics"
    for name in ("generate_data.py", "config.toml"):
        shutil.copy(example / name, tmp_path / name)
    runpy.run_path(str(tmp_path / "generate_data.py"), run_name="__main__")
    return tmp_path / "config.toml"


def test_five_metrics_holdouts_and_known_definitions(config, tmp_path):
    out = tmp_path / "records"
    records = run_config(config, judge=StatedRuleJudge(), out_dir=out, log=lambda *a: None)
    assert len(records) == 5
    assert all(r.status == "reconciled" and r.residual.holdout_variance == 0 for r in records)
    assert score_dir(out, config.parent / "answers.json")["cases_correct"] == "5/5"
    share = next(r for r in records if r.metric == "territory_share")
    assert any(i.accepted and len(getattr(i.change, "changes", [])) == 3 for i in share.iterations)
    evidence = revisions_config(config, metric="total_volume", parameter="data_vintage", before="published",
                                after="refreshed", records_dir=out, out_dir=tmp_path / "revisions")
    assert [e["delta"] for e in evidence] == [16, 32, 48, 64]
    assert all(e["status"] == "revised" for e in evidence)


def test_overlapping_and_missing_territory_mappings_fail_closed(config):
    cfg, specs, targets = load_config(config)
    runner = build_runner(cfg, config)
    spec = specs["territory_volume"]
    # Materialize the CSV view to simulate duplicate assignment data.
    runner.con.execute("CREATE TABLE extra_assignments AS SELECT * FROM assignments")
    runner.con.execute("INSERT INTO extra_assignments SELECT * FROM assignments")
    runner.con.execute("CREATE OR REPLACE VIEW assignments AS SELECT * FROM extra_assignments")
    with pytest.raises(ValueError, match="overlapping_assignments"):
        spec.compute(runner, spec.defaults(), targets[0].as_of)
    runner.con.execute("DELETE FROM extra_assignments WHERE account = 2")
    runner.cache.clear()
    with pytest.raises(ValueError, match="unmatched_assignments"):
        spec.compute(runner, spec.defaults(), targets[0].as_of)


def test_scheduler_run_isolated_and_failure_recorded(config, tmp_path):
    first = run_job(config, tmp_path / "jobs", judge=StatedRuleJudge(), log=lambda *a: None)
    assert first["status"] == "complete" and first["counts"]["reconciled"] == 5
    assert len(first["config_sha256"]) == 64
    second = run_job(config, tmp_path / "jobs", metrics=["missing"], log=lambda *a: None)
    assert second["status"] == "failed" and second["run_id"] != first["run_id"]
    assert json.loads((Path(second["output_dir"]) / "run.json").read_text())["status"] == "failed"


def test_revision_cli_and_job_review_exit_code(config, tmp_path, monkeypatch):
    main(["revisions", str(config), "--metric", "total_volume", "--parameter", "data_vintage",
          "--before", "published", "--after", "refreshed", "--out", str(tmp_path / "revisions")])
    assert (tmp_path / "revisions" / "revisions.json").exists()
    monkeypatch.setattr("reconloop.jobs.run_job", lambda *args, **kwargs: {"status": "needs_review"})
    with pytest.raises(SystemExit) as exc:
        main(["job", str(config), "--out", str(tmp_path / "jobs")])
    assert exc.value.code == 3
