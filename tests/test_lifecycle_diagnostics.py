from dataclasses import replace
import json

import pytest

from reconloop import MetricSpec, Param, Policy, Target
from reconloop.diagnostics import constant_ratio, post_close
from reconloop.runners.duckdb_runner import DuckDBRunner
from reconloop.session import ReconSession


@pytest.fixture
def session():
    runner = DuckDBRunner({})
    specs = {
        "a": MetricSpec("a", "SELECT {measure} AS value", {
            "measure": Param("measure", "measure", "initial", {"initial": "50", "partial": "80", "final": "100"})}),
        "b": MetricSpec("b", "SELECT 100 AS value", {})}
    targets = [Target(f"{m}-{i}", "report", m, f"2026-01-0{i}", 100, split="holdout" if i == 4 else "fit")
               for m in specs for i in range(1, 5)]
    yield ReconSession(specs, targets, runner, Policy(max_changes=1))
    runner.close()


def test_deferral_preserves_progress_budget_and_hidden_holdouts(session, tmp_path):
    session.open("report", "a")
    assert session.try_change("measure", "partial", "measure", "Established subset").startswith("ACCEPTED")
    session.defer("awaiting reference", depends_on=[("report", "b")])
    assert session.pending_pairs() == [("report", "b")]
    assert session.deferred_pairs() == [("report", "a")]
    assert "80" not in json.dumps(session.progress())
    with pytest.raises(RuntimeError, match="dependent"):
        session.resume("report", "a")
    with pytest.raises(ValueError, match="deferred"):
        session.open("report", "a")
    session.open_next()
    session.close()
    assert "DEFERRED" in session.open_next()
    path = session.checkpoint(tmp_path / "checkpoint.json", source_version="snapshot-1")
    restored = ReconSession(session.specs, session.targets, session.runner, session.policy)
    restored.restore(path, source_version="snapshot-1")
    assert restored.progress() == session.progress()
    text = restored.resume("report", "a")
    assert "partial" in text and "2026-01-04" not in text
    assert restored.try_change("measure", "final", "measure", "Full measure").startswith("REJECTED: too many")
    record = restored.close()
    assert record.final_params == {"measure": "partial"}
    assert [e["action"] for e in record.lifecycle] == ["deferred", "resumed"]
    assert len(record.iterations) == 3


def test_deferred_pairs_cannot_cycle_or_silently_close(session, tmp_path):
    session.open("report", "a")
    with pytest.raises(ValueError, match="reason"):
        session.defer(" ")
    session.defer("depends on b", depends_on=[("report", "b")])
    session.open("report", "b")
    with pytest.raises(ValueError, match="cycle"):
        session.defer("depends on a", depends_on=[("report", "a")])
    session.defer("external information")
    assert session.pending_pairs() == [] and len(session.deferred_pairs()) == 2
    report = session.report(tmp_path / "report")
    assert "2 deferred" in open(report, encoding="utf-8").read()
    assert not session.records


def test_checkpoint_binding_integrity_and_exclusive_write(session, tmp_path):
    session.open("report", "a")
    path = session.checkpoint(tmp_path / "checkpoint.json", source_version="v1")
    with pytest.raises(FileExistsError):
        session.checkpoint(path, source_version="v1")
    empty = ReconSession(session.specs, session.targets, session.runner, session.policy)
    with pytest.raises(ValueError, match="source_version"):
        empty.restore(path, source_version="v2")
    changed = ReconSession(session.specs, [replace(t, value=999) for t in session.targets], session.runner, session.policy)
    with pytest.raises(ValueError, match="changed"):
        changed.restore(path, source_version="v1")
    document = json.loads(path.read_text())
    document["payload"]["active"]["params"]["measure"] = "final"
    path.write_text(json.dumps(document))
    with pytest.raises(ValueError, match="integrity"):
        empty.restore(path, source_version="v1")
    assert empty._cur is None


def rows(factors):
    return [dict(target_id=str(i), as_of=f"2026-01-0{i+1}", gold=100, computed=100*f, split="fit") for i, f in enumerate(factors)]


def test_constant_ratio_is_evidence_not_an_automatic_conversion():
    result = constant_ratio(rows([2.07, 2.075, 2.065]))
    assert result["status"] == "constant"
    assert result["computed_over_target"] == pytest.approx(2.07)
    assert "does not establish the cause" in result["interpretation"]
    assert constant_ratio(rows([2.2, 1.7, 2.2]))["status"] == "variable"
    assert constant_ratio(rows([1, 1, 1]))["status"] == "near_identity"
    assert constant_ratio(rows([2, 2]))["status"] == "insufficient"
    zero = rows([0, 0, 0])
    zero[0]["gold"] = 0
    assert len(constant_ratio(zero)["excluded"]) == 3


def test_holdout_can_disprove_fit_factor_without_changing_definition(session):
    session.targets[-5] = replace(session.targets[-5], value=50)
    session.open("report", "a")
    record = session.close()
    assert record.diagnostics["fit_ratio"]["computed_over_target"] == .5
    assert record.diagnostics["holdout_factor_check"]["consistent"] is False
    assert record.final_params == {"measure": "initial"}


def test_automatic_vintage_comparison_holds_other_choices_fixed(session):
    spec = session.specs["a"]
    spec.params["vintage"] = Param("vintage", "data_vintage", "published", {"published": "1", "refreshed": "2"})
    spec.template = "SELECT {measure} * {vintage} AS value"
    session.open("report", "a")
    record = session.close()
    diagnostic = post_close(record, spec, [t for t in session.targets if t.metric == "a"], session.runner,
                            {"vintages": {"a": {"parameter": "vintage", "before": "published", "after": "refreshed"}}})
    assert len(diagnostic["vintages"]) == 4
    assert all(r["before_params"]["measure"] == r["after_params"]["measure"] == "initial" for r in diagnostic["vintages"])
    assert record.final_params["vintage"] == "published"


def test_breakdown_reveals_different_factors_against_independent_targets(session):
    from reconloop import reconcile
    spec = MetricSpec("volume", "SELECT {segment} AS value", {
        "segment": Param("segment", "universe", "all", {"all": "200", "north": "220", "south": "170"})}, unit="count")
    targets = [Target(f"{m}-{i}", "r", m, f"2026-01-0{i}", 100, unit="count")
               for m in ("volume", "north_volume", "south_volume") for i in (1, 2, 3)]
    own = [t for t in targets if t.metric == "volume"]
    class Stop:
        def propose(self, state, runner):
            return None
    record = reconcile(spec, own, session.runner, Stop(), log=lambda *a: None)
    config = {"breakdowns": {"volume": {"parameter": "segment", "metrics": {"north": "north_volume", "south": "south_volume"}}}}
    evidence = post_close(record, spec, own, session.runner, config, reference_targets=targets)
    assert [r["fit_ratio"]["computed_over_target"] for r in evidence["breakdowns"]] == [2.2, 1.7]
    assert record.final_params == {"segment": "all"}


def test_checkpoint_preserves_undefined_relative_variance(session, tmp_path):
    session.targets = [replace(t, value=0) for t in session.targets]
    session.open("report", "a")
    session.defer("zero reference needs investigation")
    path = session.checkpoint(tmp_path / "undefined.json", source_version="v1")
    restored = ReconSession(session.specs, session.targets, session.runner, session.policy)
    restored.restore(path, source_version="v1")
    restored.resume("report", "a")
    assert restored.close().residual.fit_variance == float("inf")
