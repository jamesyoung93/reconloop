from pathlib import Path
import runpy
import shutil

import pytest

from reconloop import run_config
from reconloop.jobs import run_job
from reconloop.scoring import score_dir
from reconloop.session import ReconSession


@pytest.fixture
def config(tmp_path):
    source = Path(__file__).resolve().parents[1] / "examples" / "coupled_metrics"
    for name in ("config.toml", "generate_data.py"):
        shutil.copy(source / name, tmp_path / name)
    runpy.run_path(str(tmp_path / "generate_data.py"), run_name="__main__")
    return tmp_path / "config.toml"


def test_coupled_example_in_batch_and_jobs(config, tmp_path):
    def forbidden(*args):
        pytest.fail("coupled groups must not delegate to an independent per-metric judge")
    records = run_config(config, judge_factory=forbidden, out_dir=tmp_path / "out", log=lambda *a: None)
    assert len(records) == 3 and all(r.status == "reconciled" for r in records)
    assert score_dir(tmp_path / "out", config.parent / "answers.json")["cases_correct"] == "3/3"
    assert all(e["passed"] for e in records[0].coupling["final_identities"])
    job = run_job(config, tmp_path / "jobs", log=lambda *a: None)
    assert job["status"] == "complete"


def test_partial_metric_selection_cannot_drop_constraints(config):
    with pytest.raises(ValueError, match="select all members"):
        run_config(config, metrics=["category_share"])


def test_interactive_session_cannot_silently_ignore_coupling(config):
    with pytest.raises(ValueError, match="coupled constraints"):
        ReconSession.from_config(config)
