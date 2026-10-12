"""The reconciliation loop.

    run -> compare -> judge proposes one named change -> guardrails -> accept or reject -> repeat

Stops when the fit variance is within tolerance, when the judge has nothing defensible
left, or after max_iter. Whatever remains is classified and explained, not hidden.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import replace

from .compare import classify_residual, evaluate, score, split_targets, summarize_result
from .guardrails import Policy, check
from .metricspec import MetricSpec
from .schema import Iteration, ReconRecord, Target
from .judge.base import JudgeState


def _measure(runner, spec, params, fit, hold):
    rows_f = evaluate(runner, spec, params, fit)
    rows_h = evaluate(runner, spec, params, hold) if hold else []
    return rows_f + rows_h, score(rows_f), (score(rows_h) if hold else None)


def reconcile(spec: MetricSpec, targets: list[Target], runner, judge, policy: Policy | None = None,
              start: dict[str, str] | None = None, max_iter: int = 12, log=print) -> ReconRecord:
    policy = policy or Policy()
    fit, hold = split_targets(targets, spec.name)
    params = spec.initial_choices(start)
    start_params = dict(params)

    rows, f, h = _measure(runner, spec, params, fit, hold)
    history = [Iteration(step=0, params=dict(params), fit_variance=f, holdout_variance=h, per_target=rows)]
    tried: set[tuple[str, str]] = set()
    report = targets[0].report if targets else ""
    log(f"[{report} / {spec.name}] start {spec.describe(params)}  fit {f:.2%}" + (f"  holdout {h:.2%}" if h is not None else ""))

    for step in range(1, max_iter + 1):
        last = history[-1] if history[-1].accepted is not False else next(i for i in reversed(history) if i.accepted is not False)
        if last.fit_variance <= spec.tolerance:
            break
        pattern = classify_residual([r for r in last.per_target if r["split"] == "fit"], spec.tolerance)
        # Keep holdout values out of every iteration visible to a custom judge.
        visible_history = [replace(i, holdout_variance=None,
                                   per_target=[r for r in i.per_target if r["split"] == "fit"])
                           for i in history]
        visible_last = next(i for i in reversed(visible_history) if i.accepted is not False)
        state = deepcopy(JudgeState(spec=spec, params=dict(params), targets=fit, last=visible_last,
                                    history=visible_history, tried=tried, residual_pattern=pattern))
        change = judge.propose(state, runner)
        if change is None:
            log(f"  step {step}: judge has no defensible change left")
            break
        trial = dict(params, **{change.param: change.new}) if change.param in spec.params else dict(params)
        execution_error = ""
        try:
            t_rows, tf, th = _measure(runner, spec, trial, fit, hold)
        except Exception as e:  # bad option, bad SQL
            t_rows, tf, th = last.per_target, last.fit_variance, last.holdout_variance
            execution_error = f"execution failed: {e}"
        n_acc = sum(1 for i in history if i.accepted)
        reason = execution_error or check(change, spec, last.fit_variance, tf, last.holdout_variance, th, n_acc, policy, last.per_target, t_rows)
        it = Iteration(step=step, params=trial, fit_variance=tf, holdout_variance=th, per_target=t_rows,
                       change=change, accepted=(reason == ""), reject_reason=reason)
        history.append(it)
        tried.add((change.param, change.new))
        if reason:
            log(f"  step {step}: REJECT {change.param} {change.old}->{change.new} [{change.hypothesis}]: {reason}")
            continue
        params = trial
        log(f"  step {step}: accept {change.param} {change.old}->{change.new} [{change.hypothesis}]  fit {tf:.2%}"
            + (f"  holdout {th:.2%}" if th is not None else ""))

    final = next(i for i in reversed(history) if i.accepted is not False)
    status, residual = summarize_result(final, spec.tolerance)
    log(f"  -> {status}: fit {final.fit_variance:.2%} ({residual.pattern})")
    sample_as_of = targets[0].as_of if targets else "YYYY-MM-DD"
    return ReconRecord(report=report, metric=spec.name, start_params=start_params, final_params=dict(params),
                       final_query=spec.render(params, sample_as_of), tolerance=spec.tolerance, status=status,
                       iterations=history,
                       residual=residual)
