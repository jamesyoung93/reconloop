from dataclasses import replace

import pytest

from reconloop import MetricSpec, Param, RatioSpec, Target, Policy
from reconloop.coupled import CoupledGroup, Identity, load_groups, reconcile_coupled
from reconloop.record import write
from reconloop.runners.duckdb_runner import DuckDBRunner


@pytest.fixture
def runner():
    db = DuckDBRunner({})
    yield db
    db.con.close()


def scenario():
    specs = {
        "volume": MetricSpec("volume", "SELECT 100 AS value", {}),
        "share": MetricSpec("share", "", {"grain": Param("grain", "deduplication", "half", {"half": "1", "whole": "2"})},
                            ratio=RatioSpec("SELECT 50 * {grain} AS value", "SELECT 100 * {grain} AS value"))}
    targets = [Target(f"{m}-{day}", "dashboard", m, day, v, split=split)
               for m, v in [("volume", 100), ("share", .5)]
               for day, split in [("2026-01-01", "fit"), ("2026-01-02", "holdout")]]
    group = CoupledGroup("identity", ["volume", "share"], [Identity("numerator", "share.numerator", "volume.value")])
    return specs, targets, group


def test_coupled_search_repairs_hidden_ratio_error_even_when_all_target_values_match(runner, tmp_path):
    specs, targets, group = scenario()
    records = reconcile_coupled(group, specs, targets, runner, log=lambda *a: None)
    assert all(r.status == "reconciled" for r in records)
    share = next(r for r in records if r.metric == "share")
    assert share.start_params["grain"] == "half" and share.final_params["grain"] == "whole"
    assert share.residual.fit_variance == 0 and share.residual.holdout_variance == 0
    assert all(i["passed"] for i in share.coupling["final_identities"])
    write(records, tmp_path)
    text = (tmp_path / "report.md").read_text(encoding="utf-8")
    assert "Coupled group" in text and "unchanged member" in text


def test_best_fit_candidate_checked_once_holdout_cannot_select_an_alternative(runner):
    specs, targets, group = scenario()
    share = specs["share"]
    share.params["grain"].options = {"half": "1 /* half */", "bad": "2 /* bad */", "good": "2 /* good */"}
    share.ratio.numerator = "SELECT 50 * {grain} * CASE WHEN DATE '{as_of}' = DATE '2026-01-02' AND '{grain}' LIKE '%bad%' THEN 1.5 ELSE 1 END AS value"
    # The format above includes SQL comments inside a string literal; they remain literal evidence.
    calls, original = [], runner.run
    def tracked(sql):
        calls.append(sql)
        return original(sql)
    runner.run = tracked
    records = reconcile_coupled(group, specs, targets, runner, log=lambda *a: None)
    assert all(r.status == "unresolved" for r in records)
    assert records[1].final_params == {"grain": "half"}
    audit = records[0].coupling
    assert audit["fit_selected"]["share"]["grain"] == "bad"
    assert audit["accepted"] is False and "holdout" in audit["reject_reason"]
    assert not any("/* good */" in sql and "DATE '2026-01-02' =" in sql for sql in calls)


def test_misaligned_periods_and_splits_rejected_before_sql(runner):
    specs, targets, group = scenario()
    targets[-1] = replace(targets[-1], split="fit")
    with pytest.raises(ValueError, match="coverage"):
        reconcile_coupled(group, specs, targets, runner)
    assert not runner.cache


def test_search_budget_checked_before_execution(runner):
    specs, targets, group = scenario()
    group.max_candidates = 1
    with pytest.raises(ValueError, match="search space"):
        reconcile_coupled(group, specs, targets, runner)
    assert not runner.cache


def test_same_period_cannot_be_both_fit_and_holdout(runner):
    specs, targets, group = scenario()
    targets = [replace(t, as_of="2026-01-01") for t in targets]
    with pytest.raises(ValueError, match="coverage"):
        reconcile_coupled(group, specs, targets, runner)
    assert not runner.cache


def test_undefined_holdout_variance_rejects_the_joint_candidate(runner):
    specs, targets, group = scenario()
    targets = [replace(t, value=0) if t.split == "holdout" else t for t in targets]
    records = reconcile_coupled(group, specs, targets, runner, log=lambda *a: None)
    assert all(r.status == "unresolved" for r in records)
    assert records[0].coupling["accepted"] is False
    assert "undefined holdout" in records[0].coupling["reject_reason"]
    assert records[1].final_params["grain"] == "half"


def test_unsatisfiable_identity_marks_all_members_unresolved(runner):
    specs, targets, group = scenario()
    group.identities[0].factor = 3
    records = reconcile_coupled(group, specs, targets, runner, log=lambda *a: None)
    assert all(r.status == "unresolved" for r in records)
    assert records[0].coupling["fit_selected"] is None


def test_shared_parameter_choices_cannot_disagree(runner):
    specs, targets, group = scenario()
    specs["volume"].params = {"grain": Param("grain", "deduplication", "whole", {"half": "1", "whole": "2"})}
    group.shared = {"grain": ["volume.grain", "share.grain"]}
    records = reconcile_coupled(group, specs, targets, runner, log=lambda *a: None)
    assert all(r.final_params["grain"] == "whole" for r in records)


def test_explicit_conversion_and_absolute_zero_tolerance(runner):
    specs, targets, group = scenario()
    group.identities[0] = Identity("conversion", "share.numerator", "volume.value", factor=.5,
                                   absolute_tolerance=0, relative_tolerance=0)
    records = reconcile_coupled(group, specs, targets, runner, log=lambda *a: None)
    assert all(r.status == "reconciled" for r in records)
    assert records[1].final_params["grain"] == "half"


def test_overlapping_groups_invalid_components_and_negative_tolerances_rejected():
    specs, _, _ = scenario()
    declaration = {"metrics": ["volume", "share"], "identities": [{"name": "n", "left": "share.numerator", "right": "volume.value"}]}
    with pytest.raises(ValueError, match="overlapping"):
        load_groups({"coupled": {"a": declaration, "b": declaration}}, specs)
    declaration["identities"][0]["right"] = "volume.numerator"
    with pytest.raises(ValueError, match="component"):
        load_groups({"coupled": {"a": declaration}}, specs)
    with pytest.raises(ValueError, match="tolerances"):
        Identity("bad", "x.value", "y.value", relative_tolerance=-1)


def test_policy_change_budget_cannot_be_bypassed_by_coupling(runner):
    specs, targets, group = scenario()
    records = reconcile_coupled(group, specs, targets, runner, policy=Policy(max_changes=0), log=lambda *a: None)
    assert all(r.status == "unresolved" for r in records)
    assert records[1].final_params["grain"] == "half"


def test_overflow_in_conversion_cannot_make_identity_pass(runner):
    specs, targets, group = scenario()
    group.identities[0].factor = 1e308
    records = reconcile_coupled(group, specs, targets, runner, log=lambda *a: None)
    assert all(r.status == "unresolved" for r in records)
    assert not any(e["passed"] for e in records[0].coupling["final_identities"])
