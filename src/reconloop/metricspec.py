"""A metric is a query template plus a declared space of allowed definitional choices.

The parameter space IS the governance: the loop may only move between choices
somebody has written down as legitimate. That is what stops it from inventing
filters to hit a number.

Example (TOML):

    [metrics.weekly_sales]
    unit = "currency"
    tolerance = 0.005
    template = "SELECT SUM({measure}) AS value FROM sales WHERE {window} AND {stores}"

    [metrics.weekly_sales.params.window]
    hypothesis = "time_window"
    default = "calendar"
    [metrics.weekly_sales.params.window.options]
    fiscal   = "date BETWEEN DATE '{as_of}' - 6 AND DATE '{as_of}'"
    calendar = "date BETWEEN DATE '{as_of}' - 5 AND DATE '{as_of}' + 1"
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from math import isfinite
from copy import deepcopy


@dataclass
class Param:
    name: str
    hypothesis: str
    default: str
    options: dict[str, str]          # option name -> SQL fragment (may contain {as_of})
    describe: dict[str, str] = field(default_factory=dict)   # option name -> plain words
    keywords: dict[str, list[str]] = field(default_factory=dict)  # option name -> words a report might use for it


@dataclass
class MetricSpec:
    name: str
    template: str
    params: dict[str, Param]
    unit: str = ""
    tolerance: float = 0.005         # mean absolute relative variance that counts as reconciled

    def __post_init__(self):
        if not isfinite(self.tolerance) or self.tolerance < 0:
            raise ValueError("tolerance must be finite and nonnegative")
        self.initial_choices()

    def defaults(self) -> dict[str, str]:
        return {k: p.default for k, p in self.params.items()}

    def initial_choices(self, start: dict[str, str] | None = None) -> dict[str, str]:
        choices = self.defaults() | (start or {})
        if choices.keys() - self.params.keys():
            raise ValueError("start contains unknown parameters")
        for key, option in choices.items():
            if option not in self.params[key].options:
                raise ValueError(f"{key}: '{option}' is not an allowed option")
        return choices

    def render(self, choices: dict[str, str], as_of: str) -> str:
        # Dates come from report data, not trusted SQL configuration.
        if date.fromisoformat(as_of).isoformat() != as_of:
            raise ValueError("as_of must be an ISO date (YYYY-MM-DD)")
        frags = {}
        for k, p in self.params.items():
            opt = choices.get(k, p.default)
            if opt not in p.options:
                raise ValueError(f"{self.name}: '{opt}' is not an allowed option for '{k}' ({list(p.options)})")
            frags[k] = p.options[opt].format(as_of=as_of)
        return self.template.format(**frags)

    def describe(self, choices: dict[str, str]) -> str:
        parts = []
        for k, p in self.params.items():
            opt = choices.get(k, p.default)
            parts.append(f"{k}={opt}" + (f" ({p.describe[opt]})" if opt in p.describe else ""))
        return "; ".join(parts)


def load_specs(cfg: dict) -> dict[str, MetricSpec]:
    specs = {}
    for name, m in (cfg.get("metrics") or {}).items():
        params = {}
        declarations = {}
        for group in m.get("param_groups", []):
            if group not in cfg.get("param_groups", {}):
                raise ValueError(f"{name}: unknown parameter group {group!r}")
            for pname, declaration in cfg["param_groups"][group].items():
                if pname in declarations:
                    raise ValueError(f"{name}: duplicate shared parameter {pname!r}")
                declarations[pname] = deepcopy(declaration)
        # A local declaration replaces the complete shared parameter, explicitly.
        declarations.update(deepcopy(m.get("params") or {}))
        for pname, p in declarations.items():
            params[pname] = Param(name=pname, hypothesis=p["hypothesis"], default=p["default"],
                                  options=dict(p["options"]), describe=dict(p.get("describe", {})),
                                  keywords={k: list(v) for k, v in (p.get("keywords") or {}).items()})
        specs[name] = MetricSpec(name=name, template=m["template"], params=params,
                                 unit=m.get("unit", ""), tolerance=float(m.get("tolerance", 0.005)))
    return specs
