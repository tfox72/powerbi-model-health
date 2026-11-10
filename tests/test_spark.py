"""
Local-Spark checks for the parts the mocks can't cover:
1. read_previous_docs (the real Spark code): first run, older-schema table, latest-snapshot filtering.
2. Every output table the notebook writes can be turned into a Spark DataFrame, and appended twice.
"""
import pathlib as _pl
ROOT = _pl.Path(__file__).resolve().parent.parent
import os
import re
import shutil
import sys
import pandas as pd
from pyspark.sql import SparkSession

WH = str(_pl.Path(__import__("tempfile").gettempdir()) / "mh_spark_wh")
shutil.rmtree(WH, ignore_errors=True)
spark = (SparkSession.builder.master("local[1]").appName("mh-test")
         .config("spark.sql.warehouse.dir", WH).config("spark.ui.enabled", "false")
         .config("spark.sql.execution.arrow.pyspark.enabled", "false").getOrCreate())
spark.sparkContext.setLogLevel("ERROR")

src = open(str(ROOT / "notebook" / "model_health_src.py"), encoding="utf-8").read()
fn = re.search(r"^def read_previous_docs\(.*?(?=^def )", src, flags=re.S | re.M).group(0)
ns = {"spark": spark, "pd": pd}
exec(fn, ns)
read_previous_docs = ns["read_previous_docs"]

# 1a. first run: table missing -> empty
assert read_previous_docs("mh_documentation", "ws-1", ["ds-1"]).empty
print("first run ok")

# 1b. table from an older notebook version (no Dataset_Id) -> empty with a note
spark.createDataFrame(pd.DataFrame([{"Run_Timestamp": pd.Timestamp("2026-11-01"), "Dataset_Name": "A",
                                     "Object_Name": "x"}])).write.saveAsTable("old_documentation")
assert read_previous_docs("old_documentation", "ws-1", ["ds-1"]).empty
print("old schema ok")

# 1c. history with several runs, models and workspaces -> only the latest snapshot per requested model
rows = []
for ts, ws, ds, name, h in [
    ("2026-10-01", "ws-1", "ds-1", "Total Sales", "h0"),
    ("2026-11-01", "ws-1", "ds-1", "Total Sales", "h1"),
    ("2026-11-01", "ws-1", "ds-1", "Margin", "m1"),
    ("2026-11-02", "ws-1", "ds-2", "Other", "o1"),
    ("2026-11-05", "ws-9", "ds-1", "WrongWorkspace", "z"),
]:
    rows.append({"Run_Id": f"run-{ts}", "Run_Timestamp": pd.Timestamp(ts), "Workspace_Id": ws, "Dataset_Id": ds, "Dataset_Name": "M",
                 "Object_Type": "Measure", "Table_Name": "_M", "Object_Name": name, "Lineage_Tag": f"lt-{name}",
                 "Expression_Hash": h, "Description": "", "Extra_Col": 1})
spark.createDataFrame(pd.DataFrame(rows)).write.saveAsTable("mh_documentation")
prev = read_previous_docs("mh_documentation", "ws-1", ["ds-1"])
assert set(prev["Object_Name"]) == {"Total Sales", "Margin"}, prev
assert set(prev["Expression_Hash"]) == {"h1", "m1"}
assert "Extra_Col" not in prev.columns
both = read_previous_docs("mh_documentation", "ws-1", ["ds-1", "ds-2"])
assert set(both["Object_Name"]) == {"Total Sales", "Margin", "Other"}
# The current run is excluded, so re-running after a save compares with the run before it, not with itself
earlier = read_previous_docs("mh_documentation", "ws-1", ["ds-1"], exclude_run_id="run-2026-11-01")
assert set(earlier["Expression_Hash"]) == {"h0"}, earlier
print("latest-snapshot filter ok (current run excluded)")

# 2. every output frame from a mocked notebook run converts to Spark and appends twice (schema stays stable)
import importlib.util, io, contextlib
spec = importlib.util.spec_from_file_location("e2e", str(ROOT / "tests" / "test_e2e.py"))
captured = {}
sys.argv = ["x"]
_real_pyspark = sys.modules["pyspark"]
with contextlib.redirect_stdout(io.StringIO()):
    e2e = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(e2e)          # runs all scenarios; SAVED holds the last normal run
    e2e.run_notebook("MONITORING_DAYS = 30")
sys.modules["pyspark"] = _real_pyspark
outputs = dict(e2e.SAVED)
assert outputs, "no outputs captured"
for name, pdf in outputs.items():
    sdf = spark.createDataFrame(pdf)
    sdf.write.mode("append").option("mergeSchema", "true").saveAsTable(f"t_{name}")
    sdf.write.mode("append").option("mergeSchema", "true").saveAsTable(f"t_{name}")
    n = spark.read.table(f"t_{name}").count()
    assert n == 2 * len(pdf), (name, n, len(pdf))
    bad = [f.name for f in sdf.schema.fields if f.dataType.simpleString() in ("void", "null")]
    assert not bad, (name, bad)
print(f"spark conversion ok for {len(outputs)} tables: {sorted(outputs)}")
spark.stop()
print("SPARK TESTS PASSED")
