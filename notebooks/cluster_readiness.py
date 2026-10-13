# Databricks notebook source
# MAGIC %md
# MAGIC # Reconciliation cluster readiness
# MAGIC Install the built wheel and its OCR dependencies through the environment's library settings first.
# MAGIC Configure classic compute's OCR system packages with the reviewed, pinned init script.
# MAGIC This notebook checks the active driver; it does not install or deploy anything.

# COMMAND ----------
import json
from reconloop.doctor import diagnose

dbutils.widgets.text("storage_directory", "")
dbutils.widgets.dropdown("write_probe", "false", ["false", "true"])
storage_directory = dbutils.widgets.get("storage_directory") or None
write_probe = dbutils.widgets.get("write_probe") == "true"
result = diagnose(ocr=True, path=storage_directory, write_probe=write_probe)
print(json.dumps(result, indent=2))
if not result["ok"]:
    raise RuntimeError("Readiness checks failed; resolve the reported remedies before running extraction.")
