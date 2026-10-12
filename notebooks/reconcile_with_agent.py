# Databricks notebook source
# MAGIC %md
# MAGIC # Reconcile with an agent as the judge
# MAGIC
# MAGIC 1. Run the setup cells.
# MAGIC 2. Open the Assistant (Genie) in this notebook and paste the prompt from the next cell.
# MAGIC 3. The agent drives `s.try_change(...)` one step at a time. Every query and variance is computed here, not by the model.
# MAGIC 4. The record is written to `OUT_DIR` at the end.
# MAGIC
# MAGIC The demo uses the bundled fictional data. For your own data, point `CONFIG` at your config and use the Spark runner.

# COMMAND ----------

# MAGIC %md
# MAGIC ### Prompt to paste into the Assistant
# MAGIC ```
# MAGIC You are the judge in a reconciliation loop. Read AGENT_GUIDE.md in the reconloop repo and follow it.
# MAGIC The session object is `s` in this notebook. For each pair in s.pairs(): open it, read the status,
# MAGIC propose one change at a time with s.try_change(param, option, hypothesis, rationale), stop when DONE
# MAGIC or when nothing defensible is left, then s.close(). Do not compute numbers yourself.
# MAGIC When all pairs are closed, run s.report(OUT_DIR) and summarise what reconciled, what has an
# MAGIC explained residual and why, and what needs a person.
# MAGIC ```

# COMMAND ----------

# Install from the repo you cloned into a Git folder (adjust the path), or from a wheel in a volume.
# %pip install -e /Workspace/Repos/<you>/reconloop
# dbutils.library.restartPython()

# COMMAND ----------

import os
from reconloop.session import ReconSession

REPO = os.path.abspath(os.path.join(os.getcwd(), ".."))      # notebook lives in reconloop/notebooks
CONFIG = os.path.join(REPO, "examples", "fictional_retail", "config.toml")
OUT_DIR = os.path.join(REPO, "reconloop_out")

# Demo: local DuckDB runner over the bundled CSVs (generate them first if missing).
if not os.path.exists(os.path.join(REPO, "examples", "fictional_retail", "targets.csv")):
    import runpy; runpy.run_path(os.path.join(REPO, "examples", "fictional_retail", "generate_data.py"), run_name="__main__")

s = ReconSession.from_config(CONFIG)

# Your data instead:
# from reconloop.runners.spark_runner import SparkRunner
# s = ReconSession.from_config("/Workspace/.../my_config.toml", runner=SparkRunner(spark))

s.pairs()

# COMMAND ----------

# The agent works from here. Example of what it will do:
print(s.open("ops_report", "weekly_sales"))

# COMMAND ----------

# print(s.try_change("window", "fiscal", "time_window", "Report states fiscal week."))

# COMMAND ----------

# s.close()
# print(s.report(OUT_DIR))
