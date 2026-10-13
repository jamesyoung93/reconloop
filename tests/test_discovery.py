import json
from types import SimpleNamespace

import pytest

from reconloop import Target, load_config
from reconloop.discovery import discover, load_dictionary, write_draft


def inputs():
    columns = [dict(name="day", data_type="date"), dict(name="sales_amount", data_type="decimal(12,2)"),
               dict(name="volume", data_type="double")]
    return columns, [Target("t", "operations", "sales", "2026-01-01", 100, unit="currency")]


def test_dictionary_filtered_before_mapping_and_draft_cannot_run(tmp_path):
    columns, targets = inputs()
    dictionary = tmp_path / "dictionary.csv"
    dictionary.write_text("table,column,description,unit\nother,sales_amount,not relevant,count\nfacts,sales_amount,Net sales,currency\nfacts,volume,Units,count\n")
    draft = discover(None, "facts", targets, columns=columns, dictionary=dictionary)
    assert draft["proposals"][0]["column"] == "sales_amount"
    out = write_draft(draft, tmp_path / "draft")
    with pytest.raises(ValueError, match="independent review"):
        load_config(out / "config.toml")
    config = out / "config.toml"
    config.write_text(config.read_text().replace('status = "needs_review"', 'status = "approved"'))
    _, specs, loaded = load_config(config)
    assert len(loaded) == 1
    assert "SUM(sales_amount)" in specs["sales"].render({}, "2026-01-01")
    with pytest.raises(FileExistsError):
        write_draft(draft, out)


def test_spark_discovery_reads_schema_only():
    columns, targets = inputs()
    class Spark:
        def table(self, name):
            assert name == "catalog.schema.facts"
            return SimpleNamespace(schema=SimpleNamespace(fields=[
                SimpleNamespace(name=c["name"], nullable=True, dataType=SimpleNamespace(simpleString=lambda c=c: c["data_type"]))
                for c in columns]))
        def sql(self, query):
            pytest.fail("discovery must not execute data queries")
    draft = discover(Spark(), "catalog.schema.facts", targets)
    assert draft["proposals"][0]["date_column"] == "day"


def test_model_choices_cannot_inject_sql_or_approve_configuration():
    columns, targets = inputs()
    choice = dict(metric="sales", column="sales_amount", date_column="day", aggregation="sum", rationale="Column definition")
    draft = discover(None, "facts", targets, columns=columns, complete=lambda prompt: json.dumps([choice]))
    assert draft["status"] == "needs_review"
    for bad in [dict(choice, column="sales_amount; DROP TABLE facts"), dict(choice, approved=True), dict(choice, metric="unknown")]:
        with pytest.raises(ValueError):
            discover(None, "facts", targets, columns=columns, complete=lambda prompt: json.dumps([bad]))


def test_ambiguous_date_and_missing_measure_remain_unresolved():
    columns, targets = inputs()
    columns += [dict(name="snapshot", data_type="date")]
    draft = discover(None, "facts", targets, columns=columns)
    assert draft["proposals"][0]["date_column"] is None
    draft = discover(None, "facts", targets, columns=[dict(name="day", data_type="date")])
    assert draft["proposals"][0]["column"] is None


def test_dictionary_stream_budget_conflicts_and_custom_headers(tmp_path):
    path = tmp_path / "dictionary.csv"
    path.write_text("Table name,Column name,description\nfacts,amount,Sales\nfacts,amount,Conflicting meaning\n")
    mapping = {"table": "Table name", "column": "Column name"}
    with pytest.raises(ValueError, match="conflicting"):
        load_dictionary(path, table="facts", columns=mapping)
    with pytest.raises(ValueError, match="budget"):
        load_dictionary(path, table="facts", columns=mapping, max_rows=1)


def test_excel_dictionary_reads_literals_and_rejects_formulas(tmp_path):
    openpyxl = pytest.importorskip("openpyxl")
    book = openpyxl.Workbook()
    book.active.append(["table", "column", "description"])
    book.active.append(["facts", "sales_amount", "Net sales"])
    path = tmp_path / "dictionary.xlsx"
    book.save(path)
    assert load_dictionary(path, table="facts")[0]["description"] == "Net sales"
    book.active["C2"] = '=HYPERLINK("example","x")'
    book.save(path)
    book.close()
    with pytest.raises(ValueError, match="formulas"):
        load_dictionary(path, table="facts")
