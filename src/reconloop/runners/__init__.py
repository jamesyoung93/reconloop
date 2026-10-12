"""Runners execute a rendered query and return one number.

Write a new runner for any engine: it only needs `run(sql) -> float`.
"""
from .base import Runner
from .duckdb_runner import DuckDBRunner

__all__ = ["Runner", "DuckDBRunner"]
