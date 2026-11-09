"""Run every notebook cell (except %pip) against fake sempy / sempy_labs / TOM / spark objects."""
import pathlib as _pl
ROOT = _pl.Path(__file__).resolve().parent.parent
import base64
import json
import os
import shutil
import sys
import types
import warnings
from types import SimpleNamespace as NS
import pandas as pd

warnings.simplefilter("error", FutureWarning)


class Coll(list):
    @property
    def Count(self):
        return len(self)


class Enum:
    def __init__(self, n): self.n = n
    def __str__(self): return self.n


def col(name, ctype="Data", hidden=False, desc="", expr="", sort=None, key=False, groupby=None):
    rcd = NS(GroupByColumns=Coll([NS(GroupingColumn=g) for g in groupby])) if groupby else None
    return NS(Name=name, Type=Enum(ctype), DataType=Enum("Int64"), IsHidden=hidden, Description=desc,
              Expression=expr, SortByColumn=sort, IsKey=key, Parent=None, LineageTag=f"lt-{name}",
              RelatedColumnDetails=rcd)


def part(name, stype="M", expr='let\n  Source = Sql.Database("x","y")\nin Source', mode="Import"):
    return NS(Name=name, Mode=Enum(mode), SourceType=Enum(stype), Source=NS(Expression=expr), Description="")


def table(name, cols, measures=(), hidden=False, partitions=None, hierarchies=()):
    t = NS(Name=name, IsHidden=hidden, Description="", LineageTag=f"lt-{name}", Columns=Coll(cols), DataCategory=("Time" if name == "Date" else ""),
           Measures=Coll(measures), CalculationGroup=None, Hierarchies=Coll(hierarchies),
           Partitions=Coll(partitions or [part(name)]))
    for c in cols: c.Parent = t
    for m in measures: m.Parent = t
    return t


def measure(name, expr, desc="", hidden=False):
    return NS(Name=name, Expression=expr, Description=desc, IsHidden=hidden, DisplayFolder="", FormatString="",
              LineageTag=f"lt-{name}")


monthno = col("MonthNo", hidden=True)
fy, fq = col("Fiscal Year"), col("Fiscal Quarter")
sales = table("Sales", [col("ProductKey", hidden=True), col("DateKey", hidden=True), col("Amount"), col("Notes"),
                        col("Margin", "Calculated", expr="Sales[Amount] * 0.2")])
date = table("Date", [col("DateKey", key=True), col("MonthName", sort=monthno), monthno, fy, fq],
             hierarchies=[NS(Name="Fiscal", Levels=Coll([NS(Column=fy), NS(Column=fq)]))])
product = table("Product", [col("ProductKey", hidden=True), col("Name"), col("Color")])
store = table("Store", [col("Name"), col("Address")])
fp_fields_fields = col("Fields Fields", hidden=True)
fields = table("Fields", [col("Fields", groupby=[fp_fields_fields]), fp_fields_fields, col("Fields Order", hidden=True)],
               partitions=[part("Fields", "Calculated", '{("Total", NAMEOF(\'_Measures\'[Param Measure]), 0)}')])
meas = [measure("Total Sales", "SUM(Sales[Amount])", "Sum"),
        measure("Unused", "COUNTROWS(Sales)", hidden=True),
        measure("Param Measure", "SUM(Sales[Notes])")]
mtable = table("_Measures", [col("Column1", hidden=True)], meas)
autodate = table("LocalDateTable_abc", [col("Year", hidden=True)], hidden=True,
                 partitions=[part("LocalDateTable_abc", "Calculated", "CALENDAR(1,2)")])
TABLES = [sales, date, product, store, fields, mtable, autodate]


def rel(ft, fc, tt, tc):
    f = next(t for t in TABLES if t.Name == ft); t2 = next(t for t in TABLES if t.Name == tt)
    return NS(FromTable=f, FromColumn=next(c for c in f.Columns if c.Name == fc),
              ToTable=t2, ToColumn=next(c for c in t2.Columns if c.Name == tc),
              FromCardinality=Enum("Many"), ToCardinality=Enum("One"),
              CrossFilteringBehavior=Enum("OneDirection"), IsActive=True)


MODEL = NS(Tables=Coll(TABLES), Relationships=Coll([rel("Sales", "ProductKey", "Product", "ProductKey"),
                                                     rel("Sales", "DateKey", "Date", "DateKey")]),
           Expressions=Coll([NS(Name="ServerName", Expression='"srv" meta [IsParameterQuery=true]',
                                Description="", LineageTag="lt-srv")]))


tiny_tbl = table("Data", [col("A"), col("B")])
TINY = NS(Tables=Coll([tiny_tbl]), Relationships=Coll([]), Expressions=Coll([]))
TINY_TABLES = [tiny_tbl]


class FakeTom:
    model = MODEL
    def all_date_tables(self): return iter([date])
    def is_calculated_table(self, table_name): return table_name in ("Fields", "LocalDateTable_abc")
    def is_field_parameter(self, table_name): return table_name == "Fields"
    def is_auto_date_table(self, table_name): return table_name.startswith("LocalDateTable_")
    def is_agg_table(self, table_name): return False
    def is_direct_lake(self): return False
    def all_columns(self): return [c for t in TABLES for c in t.Columns]
    def all_measures(self): return [m for t in TABLES for m in t.Measures]


class TinyTom(FakeTom):
    model = TINY
    def all_date_tables(self): return iter([])
    def is_calculated_table(self, table_name): return False
    def is_field_parameter(self, table_name): return False
    def all_columns(self): return [c for t in TINY_TABLES for c in t.Columns]
    def all_measures(self): return []


class Ctx:
    def __init__(self, readonly, tom=None): assert readonly is True, "must be read-only!"; self.tom = tom or FakeTom()
    def __enter__(self): return self.tom
    def __exit__(self, *a): return False


fabric = types.ModuleType("sempy.fabric")
fabric.resolve_workspace_id = lambda w=None: "ws-1"
fabric.resolve_workspace_name = lambda w=None: "Finance WS"
fabric.list_datasets = lambda workspace=None, mode=None: pd.DataFrame(
    {"Dataset Name": ["Sales Model", "LH1", "Broken", "Tiny"], "Dataset Id": ["ds-1", "ds-lh", "ds-x", "ds-t"]})
fabric.list_items = lambda workspace=None: pd.DataFrame({"Display Name": ["LH1", "LH1", "Sales Model"],
                                                         "Type": ["Lakehouse", "SemanticModel", "SemanticModel"]})
fabric.evaluate_dax = lambda dataset, workspace=None, dax_string="": pd.DataFrame(columns=["Table Name", "Object Name",
    "Object Type", "Referenced Table", "Referenced Object", "Referenced Object Type"]) if dataset == "Tiny" else pd.DataFrame([
    {"Table Name": "_Measures", "Object Name": "Total Sales", "Object Type": "MEASURE",
     "Referenced Table": "Sales", "Referenced Object": "Amount", "Referenced Object Type": "COLUMN"},
    {"Table Name": "_Measures", "Object Name": "Param Measure", "Object Type": "MEASURE",
     "Referenced Table": "Sales", "Referenced Object": "Notes", "Referenced Object Type": "COLUMN"},
    {"Table Name": "Sales", "Object Name": "Margin", "Object Type": "CALC_COLUMN",
     "Referenced Table": "Sales", "Referenced Object": "Amount", "Referenced Object Type": "COLUMN"},
    {"Table Name": "Sales", "Object Name": "Amount", "Object Type": "ATTRIBUTE_HIERARCHY",
     "Referenced Table": "Sales", "Referenced Object": "Amount", "Referenced Object Type": "COLUMN"},
])
fabric.list_reports = lambda workspace=None: pd.DataFrame([
    {"Id": "r1", "Name": "Sales Report", "Dataset Id": "DS-1", "Report Type": "PowerBIReport"},
    {"Id": "r5", "Name": "Lineage Missed", "Dataset Id": "ds-1", "Report Type": "PowerBIReport"},
    {"Id": "rx", "Name": "Other Model Report", "Dataset Id": "ds-9", "Report Type": "PowerBIReport"}])
sempy = types.ModuleType("sempy"); sempy.fabric = fabric

labs = types.ModuleType("sempy_labs")
def _bpa(**kw):
    assert kw.get("extended") is False and kw.get("export") is False
    if kw.get("dataset") == "Tiny":
        return pd.DataFrame(columns=["Category", "Rule Name", "Severity", "Object Type", "Object Name", "Description", "URL"])
    return pd.DataFrame([
        {"Category": "Formatting", "Rule Name": "Provide format string for measures", "Severity": "W",
         "Object Type": "Measure", "Object Name": "Unused", "Description": "desc", "URL": ""},
        {"Category": "Maintenance", "Rule Name": "Visible objects with no description", "Severity": "I",
         "Object Type": "Column", "Object Name": "'Sales'[Notes]", "Description": "d", "URL": ""},
        {"Category": "Formatting", "Rule Name": "Do not summarize numeric columns", "Severity": "W",
         "Object Type": "Column", "Object Name": "'Sales'[Amount]", "Description": "d", "URL": ""}])
labs.run_model_bpa = _bpa
LOG_COVERAGE = {"first_days_ago": 31, "queries": 500, "excel": 20}
def _qwm(query, workspace=None, language="kql"):
    assert "summarize" in query and language == "kql"
    return pd.DataFrame([{"FirstAny": pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=LOG_COVERAGE["first_days_ago"]),
                          "Queries": LOG_COVERAGE["queries"], "Excel": LOG_COVERAGE["excel"]}])
labs.query_workspace_monitoring = _qwm
labs.vertipaq_analyzer = lambda **kw: {"Columns": pd.DataFrame([
    {"Table Name": "Sales", "Column Name": "Notes", "Type": "Data", "Cardinality": 9, "Total Size": 9_000_000},
    {"Table Name": "Store", "Column Name": "Address", "Type": "Data", "Cardinality": 9, "Total Size": 2_000_000},
    {"Table Name": "Sales", "Column Name": "RowNumber-2662979B", "Type": "RowNumber", "Cardinality": 9, "Total Size": 5}])}
SAVED = {}
def _save(dataframe, delta_table_name, write_mode, merge_schema):
    assert write_mode == "append"
    SAVED[delta_table_name] = dataframe
labs.save_as_delta_table = _save

def b64(obj): return base64.b64encode(json.dumps(obj).encode()).decode()
def F(kind, ent, prop): return {kind: {"Expression": {"SourceRef": {"Entity": ent}}, "Property": prop}}
PBIR_VISUAL = {"visual": {"query": {"queryState": {"Values": {"projections": [
    {"field": F("Column", "Product", "Name")}, {"field": F("Column", "Store", "Name")},
    {"field": F("Measure", "_Measures", "Total Sales")},
    {"field": {"HierarchyLevel": {"Expression": {"Hierarchy": {"Expression": {"SourceRef": {"Entity": "Date"}},
                                                               "Hierarchy": "Fiscal"}}, "Level": "Fiscal Year"}}},
    {"field": F("Column", "Date", "MonthName")}, {"field": F("Column", "Fields", "Fields")}]}}}}}
LEGACY = {"sections": [{"visualContainers": [{"config": json.dumps({"singleVisual": {"prototypeQuery": {
    "From": [{"Name": "p", "Entity": "Product"}],
    "Select": [{"Column": {"Expression": {"SourceRef": {"Source": "p"}}, "Property": "Color"}}]}}})}]}]}
DEFS = {
    "r1": pd.DataFrame([{"path": "definition/report.json", "payload": b64({}), "payloadType": "InlineBase64"},
                        {"path": "definition/pages/p1/visuals/v1/visual.json", "payload": b64(PBIR_VISUAL), "payloadType": "InlineBase64"},
                        {"path": "StaticResources/logo.png", "payload": "iVBOR", "payloadType": "InlineBase64"}]),
    "r2": pd.DataFrame([{"path": "report.json", "payload": b64(LEGACY), "payloadType": "InlineBase64"}]),
    "r4": pd.DataFrame([{"path": "definition/report.json", "payload": b64({}), "payloadType": "InlineBase64"},
                        {"path": "definition/reportExtensions.json", "payload": b64({"entities": [{"name": "_Measures",
                            "measures": [{"name": "Ext", "expression": "SUM(store[address])"}]}]}), "payloadType": "InlineBase64"},
                        {"path": "definition/pages/p9/visuals/v9/visual.json", "payload": "bm90IGpzb24=", "payloadType": "InlineBase64"}]),
    "r5": pd.DataFrame([{"path": "definition/report.json", "payload": b64({}), "payloadType": "InlineBase64"}]),
}
def _get_def(report, workspace=None, return_dataframe=True):
    if report == "r3":
        raise PermissionError("403 Forbidden")
    return DEFS[report]
report_mod = types.ModuleType("sempy_labs.report"); report_mod.get_report_definition = _get_def
helpers = types.ModuleType("sempy_labs._helper_functions")
helpers.format_dax_object_name = lambda t, c: f"'{t}'[{c}]"
LINEAGE_MODE = {"paged": False}
def _lineage(item, workspace=None, type=None):
    if item == "ds-t":
        return {"items": [{"id": "ds-t", "type": "SemanticModel", "displayName": "Tiny"}], "relations": []}
    base = _lineage_base(item)
    if LINEAGE_MODE["paged"]:
        base = dict(base, continuationToken="abc")
    return base
helpers.get_downstream_relations = _lineage
_lineage_base = lambda item: {
    # Real API shape: the model itself is listed in items, and transitive dependents appear too.
    "items": [{"id": "ds-1", "type": "SemanticModel", "displayName": "Sales Model", "workspaceId": "ws-1"},
              {"id": "r1", "type": "Report", "displayName": "Sales Report", "workspaceId": "ws-1"},
              {"id": "r2", "type": "Report", "displayName": "Old Report", "workspaceId": "ws-2"},
              {"id": "r3", "type": "Report", "displayName": "Locked Report", "workspaceId": "ws-3"},
              {"id": "r4", "type": "Report", "displayName": "Half Broken", "workspaceId": "ws-1"},
              {"id": "pg", "type": "PaginatedReport", "displayName": "Invoice", "workspaceId": "ws-1"},
              {"id": "cm", "type": "SemanticModel", "displayName": "Composite", "workspaceId": "ws-4"},
              {"id": "rc", "type": "Report", "displayName": "On Composite", "workspaceId": "ws-4"}],
    "relations": [{"itemId": x, "dependentOnItemId": "ds-1"} for x in ("r1", "r2", "r3", "r4", "pg", "cm")]
                 + [{"itemId": "rc", "dependentOnItemId": "cm"}]}
pyspark_mod = types.ModuleType("pyspark"); pyspark_mod.__version__ = "3.5.1"
sm_mod = types.ModuleType("sempy_labs.semantic_model")
MONITOR_CALLS = []
def _fuo(dataset, workspace=None, method="WorkspaceMonitoring", workspace_monitoring_days=7, visualize=True):
    assert visualize is False and method == "WorkspaceMonitoring"
    MONITOR_CALLS.append((dataset, workspace_monitoring_days))
    return pd.DataFrame([{"Table Name": "Sales", "Object Type": "Column", "Object Name": "Margin", "IsUsed": True, "UsageCount": 3},
                         {"Table Name": "Sales", "Object Type": "Column", "Object Name": "Notes", "IsUsed": False, "UsageCount": 0}])
sm_mod.find_unused_objects = _fuo
tom_mod = types.ModuleType("sempy_labs.tom")
def connect_semantic_model(dataset, workspace=None, readonly=True):
    if dataset == "Broken":
        raise RuntimeError("XMLA endpoint disabled")
    return Ctx(readonly, TinyTom() if dataset == "Tiny" else None)
tom_mod.connect_semantic_model = connect_semantic_model
icons = types.ModuleType("sempy_labs._icons"); icons.severity_mapping = {"W": "Warning", "E": "Error", "I": "Info"}
for name, mod in {"pyspark": pyspark_mod, "sempy_labs.semantic_model": sm_mod,
                  "sempy": sempy, "sempy.fabric": fabric, "sempy_labs": labs, "sempy_labs.tom": tom_mod,
                  "sempy_labs.report": report_mod, "sempy_labs._helper_functions": helpers, "sempy_labs._icons": icons}.items():
    sys.modules[name] = mod
import importlib.metadata as md
_real = md.version
md.version = lambda p: "0.18.1" if p == "semantic-link-labs" else _real(p)

# Previous run (what read_previous_docs would return from Spark)
PREV = pd.DataFrame([
    {"Run_Timestamp": pd.Timestamp("2026-11-01"), "Workspace_Id": "ws-1", "Dataset_Id": "ds-1", "Dataset_Name": "Sales Model",
     "Object_Type": "Measure", "Table_Name": "_Measures", "Object_Name": "Total Sales", "Lineage_Tag": "lt-Total Sales",
     "Expression_Hash": "oldhash", "Description": "Sum"},
    {"Run_Timestamp": pd.Timestamp("2026-11-01"), "Workspace_Id": "ws-1", "Dataset_Id": "ds-1", "Dataset_Name": "Sales Model",
     "Object_Type": "Measure", "Table_Name": "_Measures", "Object_Name": "Gone", "Lineage_Tag": "lt-gone",
     "Expression_Hash": "x", "Description": ""},
])
FILES = str(_pl.Path(__import__("tempfile").gettempdir()) / "mh_fake_lakehouse" / "Files")
shutil.rmtree(_pl.Path(FILES).parent, ignore_errors=True); os.makedirs(FILES)
NB = json.load(open(str(ROOT / "notebook" / "Model_Health_Phase1.ipynb")))


def run_notebook(params_override=""):
    SAVED.clear()
    g = {"display": lambda x: None, "spark": object()}
    for i, c in enumerate(NB["cells"]):
        code = "".join(c["source"])
        if c["cell_type"] != "code" or code.lstrip().startswith("%pip"):
            continue
        code = code.replace('"/lakehouse/default/Files"', f'"{FILES}"')
        if c["metadata"].get("tags") == ["parameters"]:
            code += "\n" + params_override
        exec(compile(code, f"cell{i}", "exec"), g)
        if "def read_previous_docs" in code:
            g["read_previous_docs"] = lambda table, ws, ids: PREV.copy()
    return g


import io, contextlib
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    g = run_notebook()
out1 = buf.getvalue()

# ---------------- run 1 assertions ----------------
assert [m["name"] for m in g["models"]] == ["Sales Model", "Broken", "Tiny"], g["models"]
f = SAVED["mh_findings"]
assert set(f["Dataset_Name"]) <= {"Sales Model", "Tiny"} and "ds-1" in set(f["Dataset_Id"])
assert not (f["Finding"] == "Visible objects with no description").any(), "superseded BPA rule leaked"
assert f.loc[f["Finding"] == "Do not summarize numeric columns", "Table_Name"].iloc[0] == "Sales"
assert f.loc[f["Finding"] == "Provide format string for measures", "Table_Name"].iloc[0] == "_Measures"
un = SAVED["mh_unused_objects"]
un = un[un["Dataset_Name"] == "Sales Model"]
got = set(zip(un["Object_Type"], un["Table_Name"], un["Object_Name"]))
# Store[Address] is now used via the lower-case report-extension DAX in the half-broken report
assert got == {("Column", "Sales", "Margin"), ("Column", "_Measures", "Column1"), ("Measure", "_Measures", "Unused")}, got
conf = SAVED["mh_usage_confidence"]
detail = conf["Confidence_Detail"].iloc[0]
conf = conf[conf["Dataset_Name"] == "Sales Model"]
detail = conf["Confidence_Detail"].iloc[0]
assert conf["Confidence"].iloc[0] == "Medium", conf["Confidence"].iloc[0]
assert conf["Query_Logs"].iloc[0] == "Not checked" and not MONITOR_CALLS
assert "1 SemanticModel" in detail and "1 PaginatedReport" in detail and "Locked Report" in detail and "Half Broken" in detail, detail
assert "2 SemanticModel" not in detail                                  # the model itself is not counted
assert int(conf["Reports_Found"].iloc[0]) == 5                           # r1..r4 + r5 (lineage-missed); not rc/rx
scan = SAVED["mh_report_scan"].set_index("Report_Name")
assert scan.loc["Sales Report", "Scanned"] and scan.loc["Old Report", "Scanned"] and scan.loc["Lineage Missed", "Scanned"]
assert not scan.loc["Locked Report", "Scanned"] and "403" in scan.loc["Locked Report", "Error"]
assert not scan.loc["Half Broken", "Scanned"] and scan.loc["Half Broken", "Error"].startswith("Partly unreadable")
assert scan.loc["Old Report", "Format"] == "PBIR-Legacy"
uf = f[(f["Source"] == "Usage") & (f["Dataset_Name"] == "Sales Model")]
assert len(uf) and (uf["Severity"] == "Info").all(), "Medium confidence must not produce Warning-level removal findings"
assert un["Recommendation"].str.startswith("Likely:").all()
log = SAVED["mh_run_log"]
assert ((log["Dataset_Name"] == "Broken") & (log["Status"] == "Failed")).any()
assert not ((log["Dataset_Name"] == "Tiny") & (log["Status"] == "Failed")).any()
assert str(log["Seconds"].dtype).startswith("float")
docs = SAVED["mh_documentation"]
assert docs["Has_Comment"].dtype == bool and not (docs.astype(str) == "nan").any().any()
chg = SAVED["mh_changes"]
kinds = set(zip(chg["Change"], chg["Object_Name"]))
assert ("Expression changed", "Total Sales") in kinds and ("Removed", "Gone") in kinds, kinds
assert all(" " not in c for df in SAVED.values() for c in df.columns)
latest = f"{FILES}/model_health/latest"
files1 = sorted(os.listdir(latest))
assert files1 == sorted(["summary.md", "summary_Sales_Model.md", "summary_Broken.md", "summary_Tiny.md",
                         "dictionary_Sales_Model.md", "dictionary_Tiny.md",
                         "top_issues.csv", "top_findings.csv", "unused_candidates.csv"]), files1
_c = SAVED["mh_usage_confidence"]; tiny_conf = _c[_c["Dataset_Name"] == "Tiny"]
assert tiny_conf["Confidence"].iloc[0] == "Low"                       # zero-measure model analysed, no reports
assert "Unused objects — not run" not in open(f"{latest}/summary_Tiny.md").read()
broken_sec = open(f"{latest}/summary_Broken.md").read()
assert broken_sec.startswith("# Model health — Broken\nWorkspace: Finance WS") and "dictionary_" not in broken_sec
_d = open(f"{latest}/dictionary_Sales_Model.md").read()
assert "**Power Query (`Sales`)**" in _d and "## Relationships" in _d and "Sales[ProductKey]" in _d
_s = open(f"{latest}/summary_Sales_Model.md").read()
assert "Relationships: 2 (0 inactive" in _s and "Removal procedure: hide" in _s
_tiny = open(f"{latest}/summary_Tiny.md").read()
assert "BPA not run" not in _tiny and "Provide format string" not in _tiny
summary = open(f"{latest}/summary.md").read()
assert "| Broken | FAILED at Read model metadata" in summary, summary[:600]
assert "### Priority issues" in summary and "Reports not read: Locked Report" in summary and "### Model shape" in summary
assert "summary.md (copy this into your agent" in out1
dic = open(f"{latest}/dictionary_Sales_Model.md").read()
assert "### [Total Sales]" in dic and "SUM(Sales[Amount])" in dic and "LocalDateTable_abc" not in dic
print("RUN 1 (normal) PASSED")
print("-" * 30, "summary.md from run 1", "-" * 30)
print(summary)
print("-" * 80)

# ---------------- run 2: every model fails + one table write fails ----------------
_orig_connect, _orig_save = tom_mod.connect_semantic_model, labs.save_as_delta_table
tom_mod.connect_semantic_model = lambda dataset, workspace=None, readonly=True: (_ for _ in ()).throw(RuntimeError("XMLA disabled"))
def flaky_save(dataframe, delta_table_name, write_mode, merge_schema):
    if delta_table_name == "mh_run_log":
        raise RuntimeError("Failed to merge fields 'Seconds' and 'Seconds'")
    SAVED[delta_table_name] = dataframe
labs.save_as_delta_table = flaky_save
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    g2 = run_notebook()
out2 = buf.getvalue()
files2 = sorted(os.listdir(latest))
assert files2 == sorted(["summary.md", "summary_Sales_Model.md", "summary_Broken.md", "summary_Tiny.md",
                         "top_issues.csv", "top_findings.csv", "unused_candidates.csv"]), files2   # old dictionaries removed
lines = open(f"{latest}/unused_candidates.csv").read().strip().splitlines()
assert lines[0].startswith("Dataset Name,Object Type") and len(lines) == 1          # header only, no stale rows
s2 = open(f"{latest}/summary.md").read()
assert s2.count("FAILED at Read model metadata") >= 2 and "Steps that failed" in s2, s2
assert "Could not append to mh_run_log" in out2 and "set TABLE_PREFIX" in out2
print("RUN 2 (all models fail, one table write fails) PASSED")
tom_mod.connect_semantic_model, labs.save_as_delta_table = _orig_connect, _orig_save

# ---------------- run 3: no models match ----------------
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    g3 = run_notebook('DATASETS = "Does Not Exist"')
s3 = open(f"{latest}/summary.md").read()
assert "No models were analyzed" in s3, s3[:300]
assert "Not found in Finance WS: ['Does Not Exist']" in buf.getvalue()
assert sorted(os.listdir(latest)) == ["summary.md", "top_findings.csv", "top_issues.csv", "unused_candidates.csv"]
print("RUN 3 (no models) PASSED")

# ---------------- run 4: query-log check on ----------------
with contextlib.redirect_stdout(io.StringIO()):
    run_notebook("MONITORING_DAYS = 45")
c4 = SAVED["mh_usage_confidence"]; c4 = c4[c4["Dataset_Name"] == "Sales Model"]
assert ("ds-1", 30) in MONITOR_CALLS                                    # capped at 30-day retention
assert c4["Query_Logs"].iloc[0] == "Checked 30 days" and "500 queries, 20 from Excel" in c4["Confidence_Detail"].iloc[0]
u4 = SAVED["mh_unused_objects"]
assert "Margin" not in set(u4[u4["Dataset_Name"] == "Sales Model"]["Object_Name"])   # seen in the logs -> used
print("RUN 4 (query logs) PASSED")

# ---------------- run 4b: monitoring switched on only 5 days ago -> partial, no confidence lift ----------------
LOG_COVERAGE["first_days_ago"] = 5
with contextlib.redirect_stdout(io.StringIO()):
    run_notebook("MONITORING_DAYS = 30")
LOG_COVERAGE["first_days_ago"] = 31
c4b = SAVED["mh_usage_confidence"]; c4b = c4b[c4b["Dataset_Name"] == "Sales Model"]
assert c4b["Query_Logs"].iloc[0].startswith("Partial: monitoring data only goes back 5 days")
assert c4b["Confidence"].iloc[0] == "Medium" and "can't vouch" in c4b["Confidence_Detail"].iloc[0]
u4b = SAVED["mh_unused_objects"]
assert "Margin" not in set(u4b[u4b["Dataset_Name"] == "Sales Model"]["Object_Name"])   # still counted as used
print("RUN 4b (partial query logs) PASSED")

# ---------------- run 5: paged lineage response ----------------
LINEAGE_MODE["paged"] = True
with contextlib.redirect_stdout(io.StringIO()) as b5:
    run_notebook()
LINEAGE_MODE["paged"] = False
c5 = SAVED["mh_usage_confidence"]; c5 = c5[c5["Dataset_Name"] == "Sales Model"]
assert c5["Confidence"].iloc[0] == "Low" and "Lineage was incomplete" in c5["Confidence_Detail"].iloc[0]
print("RUN 5 (paged lineage -> Low) PASSED")

# ---------------- runtime check refuses Spark 3.4 ----------------
pyspark_mod.__version__ = "3.4.1"
try:
    run_notebook()
    raise AssertionError("runtime check did not stop Spark 3.4")
except RuntimeError as ex:
    assert "Fabric Runtime 1.3" in str(ex)
pyspark_mod.__version__ = "3.5.1"
print("RUNTIME CHECK PASSED")

# Doc check: every column named in output-tables.md exists in what a normal run writes
import re as _re
with contextlib.redirect_stdout(io.StringIO()):
    run_notebook()
doc = open(str(ROOT / "skill" / "references" / "output-tables.md")).read()
for t, df in SAVED.items():
    rows = [l for l in doc.splitlines() if l.startswith(f"| `{t}`")]
    assert rows, f"{t} not documented"
    named = set(_re.findall(r"`([A-Za-z_]+)`", rows[0].split("|")[3]))
    missing = named - set(df.columns)
    assert not missing, (t, missing)
print("output-tables.md matches")
print("E2E PASSED")
