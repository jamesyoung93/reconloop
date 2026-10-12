import json
import runpy
from pathlib import Path

import pytest

from reconloop import load_config, run_config
from reconloop.compare import classify_residual, rel_var
from reconloop.judge import SearchJudge, StatedRuleJudge
from reconloop.scoring import score_dir
from reconloop.session import ReconSession

DEMO = Path(__file__).resolve().parent.parent / "examples" / "fictional_retail"
CFG = DEMO / "config.toml"


@pytest.fixture(scope="session", autouse=True)
def demo_data():
    if not (DEMO / "targets.csv").exists():
        runpy.run_path(str(DEMO / "generate_data.py"), run_name="__main__")


def test_rel_var():
    assert rel_var(101, 100) == pytest.approx(0.01)
    assert rel_var(0, 0) == 0.0


def test_residual_shapes():
    flat = [{"rel": 0.015, "as_of": f"2026-01-{d:02d}"} for d in range(1, 8)]
    assert classify_residual(flat, 0.003) == "level_shift"
    assert classify_residual([{"rel": 0.001, "as_of": "x"}], 0.003) == "within_tolerance"


def test_stated_rule_judge_solves_demo(tmp_path):
    run_config(CFG, judge=StatedRuleJudge(), out_dir=tmp_path, log=lambda *a: None)
    res = score_dir(tmp_path, DEMO / "answers.json")
    assert res["cases_correct"] == "3/3"
    ops = json.loads((tmp_path / "ops_report__weekly_sales.json").read_text())
    assert ops["status"] == "explained_residual"
    assert "restatement" in ops["residual"]["likely_causes"]


def test_search_judge_falls_into_the_trap(tmp_path):
    """Greedy search on fit variance alone keeps the wrong week to absorb the restatement."""
    run_config(CFG, judge=SearchJudge(), out_dir=tmp_path, log=lambda *a: None)
    res = score_dir(tmp_path, DEMO / "answers.json")
    assert res["detail"]["ops_report/weekly_sales"]["case_correct"] is False


def test_session_flow_and_guardrails(tmp_path):
    s = ReconSession.from_config(str(CFG))
    assert ("ops_report", "weekly_sales") in s.pairs()
    s.open("ops_report", "weekly_sales")
    out = s.try_change("window", "fiscal", "universe", "wrong reason on purpose")
    assert out.startswith("REJECTED") and "does not match" in out
    out = s.try_change("stores", "everything", "universe", "not a declared option")
    assert out.startswith("REJECTED")
    assert s.try_change("window", "fiscal", "time_window", "Report states fiscal week.").startswith("ACCEPTED")
    assert s.try_change("measure", "net", "measure", "Report states net sales.").startswith("ACCEPTED")
    rec = s.close()
    assert rec.status == "explained_residual"
    md = s.report(str(tmp_path))
    assert Path(md).exists()


def test_add_option_is_flagged(tmp_path):
    s = ReconSession.from_config(str(CFG))
    s.open("merch_report", "weekly_sales")
    s.add_option("stores", "all_but_closed", "TRUE", "Hypothetical: closed stores excluded.")
    s.try_change("stores", "all_but_closed", "universe", "Agent-added option.")
    rec = s.close()
    assert "awaiting review" in rec.residual.note
    s.report(str(tmp_path))
    assert (tmp_path / "spec_changes_for_review.json").exists()


def test_llm_judge_parses_and_is_guarded(tmp_path):
    from reconloop.judge import LLMJudge
    replies = iter(['{"param": "window", "value": "fiscal", "hypothesis": "time_window", "rationale": "Report says fiscal."}',
                    'Sure! {"param": "measure", "value": "net", "hypothesis": "measure", "rationale": "Report says net."}',
                    '{"param": null, "rationale": "Constant 1.5% gap; likely restatement."}'])
    judge = LLMJudge(lambda prompt: next(replies))
    cfg, specs, targets = load_config(CFG)
    from reconloop.config import build_runner
    from reconloop.loop import reconcile
    ts = [t for t in targets if t.report == "ops_report"]
    rec = reconcile(specs["weekly_sales"], ts, build_runner(cfg, CFG), judge, start=cfg["start"]["weekly_sales"], log=lambda *a: None)
    assert rec.final_params["window"] == "fiscal" and rec.final_params["measure"] == "net"
    assert rec.status == "explained_residual"
    assert "Allowed choices" in judge.last_prompt and "holdout" not in judge.last_prompt.split("Fit results")[1].split("Mean")[0]
