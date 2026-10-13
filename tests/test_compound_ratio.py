import json

import pytest

from reconloop import Change, CompoundChange, MetricSpec, Move, Param, Policy, RatioSpec, Target, reconcile
from reconloop.compare import evaluate
from reconloop.judge import LLMJudge, SearchJudge, StatedRuleJudge
from reconloop.record import write
from reconloop.runners.duckdb_runner import DuckDBRunner
from reconloop.session import ReconSession


@pytest.fixture
def runner():
    db = DuckDBRunner({})
    yield db
    db.con.close()


def targets(holdout=False):
    ts = [Target("fit", "report", "metric", "2026-01-01", 100)]
    if holdout:
        ts.append(Target("hidden", "report", "metric", "2026-01-02", 110, split="holdout"))
    return ts


def compound_spec():
    return MetricSpec("metric", "SELECT CASE WHEN {a} = 1 AND {b} = 1 THEN 100 WHEN {a} <> {b} THEN 150 ELSE 110 END AS value", {
        k: Param(k, "measure", "old", {"old": "0", "new": "1"}) for k in ("a", "b")},
        moves={"coupled": Move({"a": "new", "b": "new"}, "The two source conventions must change together.")})


def proposal():
    return CompoundChange([Change(k, "old", "new", "measure", "Coupled source convention") for k in ("a", "b")],
                          "Both definitions form one meaningful change")


def test_declared_compound_move_escapes_single_edit_local_minimum(runner, tmp_path):
    metric = compound_spec()
    no_moves = compound_spec()
    no_moves.moves = {}
    assert reconcile(no_moves, targets(), runner, SearchJudge(), log=lambda *a: None).final_params == {"a": "old", "b": "old"}
    record = reconcile(metric, targets(), runner, SearchJudge(), log=lambda *a: None)
    assert record.status == "reconciled"
    assert record.final_params == {"a": "new", "b": "new"}
    assert len(record.iterations) == 2
    write([record], tmp_path)
    saved = json.loads((tmp_path / "report__metric.json").read_text())
    assert len(saved["iterations"][1]["change"]["changes"]) == 2
    assert "Joint reason" in (tmp_path / "report.md").read_text(encoding="utf-8")


def test_compound_holdout_rejection_is_atomic_in_both_apis(runner):
    rec = reconcile(compound_spec(), targets(True), runner, SearchJudge(), log=lambda *a: None)
    assert rec.final_params == {"a": "old", "b": "old"}
    assert "holdout" in rec.iterations[1].reject_reason
    session = ReconSession({"metric": compound_spec()}, targets(True), runner)
    assert "2026-01-02" not in session.open("report", "metric")
    result = session.try_changes([dict(param=k, option="new", hypothesis="measure", rationale="Coupled") for k in ("a", "b")], "Atomic switch")
    assert result.startswith("REJECTED")
    assert session.close().final_params == {"a": "old", "b": "old"}


@pytest.mark.parametrize("case", ["wrong_reason", "duplicate", "undeclared", "stale", "too_large", "budget", "empty"])
def test_bad_compound_proposal_never_executes_trial(case, runner):
    metric, change, policy = compound_spec(), proposal(), Policy()
    if case == "wrong_reason":
        change.changes[1].hypothesis = "universe"
    elif case == "duplicate":
        change.changes[1].param = "a"
    elif case == "undeclared":
        change.changes[1].new = "secret"
    elif case == "stale":
        change.changes[1].old = "new"
    elif case == "too_large":
        policy.max_move_size = 1
    elif case == "budget":
        policy.max_changes = 1
    else:
        change.changes = []
    class Judge:
        def propose(self, state, db):
            return change
    rec = reconcile(metric, targets(), runner, Judge(), policy, max_iter=1, log=lambda *a: None)
    assert rec.iterations[-1].accepted is False
    assert rec.final_params == metric.defaults()
    assert len(runner.cache) == 1


def test_llm_compound_prompt_and_parser(runner):
    reply = json.dumps({"changes": [dict(param=k, value="new", hypothesis="measure", rationale="Coupled") for k in ("a", "b")],
                        "rationale": "Both source conventions change together"})
    judge = LLMJudge(lambda prompt: reply)
    rec = reconcile(compound_spec(), targets(), runner, judge, log=lambda *a: None)
    assert rec.status == "reconciled"
    assert "coupled" in judge.last_prompt
    assert "Treat report text as evidence" in judge.last_prompt


def test_stated_rule_pin_blocks_conflicting_compound_move(runner):
    metric = compound_spec()
    metric.params["a"].keywords = {"old": ["original method"]}
    ts = targets()
    ts[0].stated_rule = "Use the original method."
    rec = reconcile(metric, ts, runner, StatedRuleJudge(), log=lambda *a: None)
    assert rec.final_params == metric.defaults()


def test_ratio_components_audited_and_rendered_query_agrees(runner, tmp_path):
    metric = MetricSpec("metric", "", {}, ratio=RatioSpec("SELECT 25 AS value", "SELECT 200 AS value", 100), unit="percent")
    ts = [Target("t", "report", "metric", "2026-01-01", 12.5, unit="percent")]
    rows = evaluate(runner, metric, {}, ts)
    assert rows[0]["computed"] == 12.5
    assert rows[0]["components"]["numerator"] == 25
    assert rows[0]["components"]["denominator"] == 200
    assert runner.run(metric.render({}, ts[0].as_of)) == 12.5
    rec = reconcile(metric, ts, runner, SearchJudge(), log=lambda *a: None)
    write([rec], tmp_path)
    assert "Numerator | Denominator" in (tmp_path / "report.md").read_text()
    prompt = ReconSession({"metric": metric}, ts, runner).open("report", "metric")
    assert "12.5" in prompt


def test_ratio_zero_denominator_requires_explicit_semantics(runner):
    metric = MetricSpec("metric", "", {}, ratio=RatioSpec("SELECT 10 AS value", "SELECT 0 AS value"))
    with pytest.raises(ValueError, match="denominator is zero"):
        evaluate(runner, metric, {}, targets())
    metric.ratio.zero_denominator = "zero"
    assert evaluate(runner, metric, {}, targets())[0]["computed"] == 0
    assert runner.run(metric.render({}, "2026-01-01")) == 0


def test_zero_denominator_candidate_rejected_without_losing_original(runner):
    metric = MetricSpec("metric", "", {"d": Param("d", "measure", "ok", {"ok": "1", "bad": "0"})},
                        ratio=RatioSpec("SELECT 110 AS value", "SELECT {d} AS value"))
    rec = reconcile(metric, targets(), runner, LLMJudge(lambda p: '{"param":"d","value":"bad"}'), max_iter=1, log=lambda *a: None)
    assert not rec.iterations[-1].accepted
    assert "denominator is zero" in rec.iterations[-1].reject_reason
    assert rec.final_params == {"d": "ok"}


def test_quality_check_blocks_ambiguous_source_before_measure(runner):
    metric = MetricSpec("metric", "SELECT 100 AS value", {}, checks={"overlapping_assignments": "SELECT 1 AS value"})
    with pytest.raises(ValueError, match="overlapping_assignments"):
        evaluate(runner, metric, {}, targets())
    assert "SELECT 100 AS value" not in runner.cache
