"""reconloop: reconcile a rebuilt metric against trusted reports, and show your work.

    from reconloop import load_config, run_config
    records = run_config("examples/fictional_retail/config.toml")
"""
from .schema import Target, Change, CompoundChange, Iteration, ReconRecord, Residual
from .metricspec import MetricSpec, Param, RatioSpec, Move, load_specs
from .loop import reconcile
from .guardrails import Policy
from .config import load_config, run_config

__all__ = ["Target", "Change", "CompoundChange", "Iteration", "ReconRecord", "Residual", "MetricSpec", "Param", "RatioSpec", "Move", "load_specs",
           "reconcile", "Policy", "load_config", "run_config"]
__version__ = "0.5.0"
