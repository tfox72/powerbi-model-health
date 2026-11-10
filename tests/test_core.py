"""Unit tests for the pure functions in Step 2, including realistic PBIR / legacy report JSON."""
import pathlib as _pl
ROOT = _pl.Path(__file__).resolve().parent.parent
import json
import re
import pandas as pd

import sys
sys.path.insert(0, str(ROOT / "tools"))
from build import split_cells

# The Step 2 engine cells are pure Python (no Fabric calls): run them and test the functions directly.
src = open(str(ROOT / "notebook" / "model_health_src.py"), encoding="utf-8").read()
step2 = src[src.index("# ## Step 2"):src.index("# ## Step 3")]
core = "\n\n".join(body for kind, body in split_cells("# %% [markdown]\n" + step2) if kind == "engine")
assert core.count("\ndef ") > 30, "engine cells not found"
ns = {}
exec(core, ns)
_col, _meas, _anycol, _hier, _tbl, _anyhier = ns["_col"], ns["_meas"], ns["_anycol"], ns["_hier"], ns["_tbl"], ns["_anyhier"]

# ---------------- helpers ----------------
assert ns["as_list"]('["A","B"]') == ["A", "B"]
assert ns["as_list"]("A, B") == ["A", "B"]
assert ns["as_list"]("") == [] and ns["as_list"](None) == [] and ns["as_list"](["X"]) == ["X"]
assert ns["as_list"]("Sales Model") == ["Sales Model"]  # no substring matching later
assert ns["as_bool"]("True") and not ns["as_bool"]("false") and ns["as_bool"](True)

hc = ns["has_comment"]
assert hc("SUM(Sales[Amt]) // total")
assert hc("-- header\nSUM(x)")
assert hc("/* a */ 1")
assert not hc('SUM(x) & "http://a.com"')
assert not hc("CALCULATE([X], 'Sales -- 2024'[Amt] > 0)")   # quoted table name
assert not hc("SUM('T'[a//b])")                               # bracketed column
assert not hc("")
assert hc("let // step\n a = 1 in a", "M")
assert not hc('let a = "--" in a', "M")
assert not hc('let a = #"Col // x" in a', "M")
assert ns["expression_hash"]("SUM( x )") == ns["expression_hash"]("SUM(\n x\n)") != ns["expression_hash"]("SUM(y)")
print("helpers ok")

# ---------------- DAX / NAMEOF references ----------------
refs = ns["dax_references"]("SUM('Fact Sales'[Freight]) + [Base] + Sales[Qty] & \"[not a ref]\"")
assert _col("Fact Sales", "Freight") in refs and _col("Sales", "Qty") in refs and _meas("Base") in refs
assert _meas("not a ref") not in refs
fp = ns["nameof_references"]('{ ("Sales", NAMEOF(\'_Measures\'[Total Sales]), 0), ("Color", NAMEOF(Product[Color]), 1), ("X", NAMEOF([Margin %]), 2) }')
assert _meas("Total Sales") in fp and _col("Product", "Color") in fp and _meas("Margin %") in fp
print("dax refs ok")

# ---------------- report parser ----------------
def field(kind, entity, prop, alias=False):
    sr = {"Source": entity} if alias else {"Entity": entity}
    return {kind: {"Expression": {"SourceRef": sr}, "Property": prop}}

pbir_visual = {  # definition/pages/p1/visuals/v1/visual.json
    "visual": {"visualType": "tableEx", "query": {"queryState": {"Values": {"projections": [
        {"field": field("Column", "Product", "Name"), "queryRef": "Product.Name"},
        {"field": field("Column", "Store", "Name"), "queryRef": "Store.Name"},   # same property name, other table
        {"field": {"Aggregation": {"Expression": field("Column", "Sales", "Amount"), "Function": 0}}},
        {"field": field("Measure", "_Measures", "Total Sales")},
        {"field": {"HierarchyLevel": {"Expression": {"Hierarchy": {
            "Expression": {"SourceRef": {"Entity": "Date"}}, "Hierarchy": "Fiscal"}}, "Level": "Fiscal Year"}}},
        {"field": {"HierarchyLevel": {"Expression": {"Hierarchy": {
            "Expression": {"PropertyVariationSource": {"Expression": {"SourceRef": {"Entity": "Sales"}},
                                                       "Name": "Variation", "Property": "OrderDate"}},
            "Hierarchy": "Date Hierarchy"}}, "Level": "Year"}}},
        {"field": {"NativeVisualCalculation": {"Language": "dax", "Expression": "RUNNINGSUM([Total Sales])", "Name": "Running"}}},
    ]}}}},
    "filterConfig": {"filters": [{"field": field("Column", "Region", "Country")}]},
}
legacy_report = {  # report.json (PBIR-Legacy): config/filters are JSON strings, queries use aliases
    "sections": [{"filters": json.dumps([{"expression": field("Column", "Channel", "Name")}]),
                  "visualContainers": [{"config": json.dumps({"singleVisual": {"prototypeQuery": {
                      "From": [{"Name": "s", "Entity": "Sales"}, {"Name": "c", "Entity": "Customer"}],
                      "Select": [field("Column", "c", "Segment", alias=True),
                                 {"Aggregation": {"Expression": field("Column", "s", "Qty", alias=True), "Function": 0}}]}}})}]}],
}
report_ext = {"entities": [{"name": "_Measures", "measures": [
    {"name": "Report Freight", "expression": "SUM('Sales'[Freight]) + [Base Measure]"}]}]}
bookmark = {"explorationState": {"filters": {"byExpr": [{"expression": field("Column", "Product", "Brand")}]}}}

nodes = set()
for doc in (pbir_visual, legacy_report, report_ext, bookmark):
    ns["extract_report_fields"](doc, out=nodes)
expected = {
    _col("Product", "Name"), _col("Store", "Name"), _col("Sales", "Amount"), _meas("Total Sales"),
    _hier("Date", "Fiscal"), _col("Sales", "OrderDate"), _col("Region", "Country"),
    _col("Channel", "Name"), _col("Customer", "Segment"), _col("Sales", "Qty"),
    _col("Sales", "Freight"), _meas("Base Measure"), _col("Product", "Brand"),
}
missing = expected - nodes
assert not missing, missing
assert ns["report_format"](["definition/report.json", "definition.pbir"]) == "PBIR"
assert ns["report_format"](["report.json"]) == "PBIR-Legacy"
print(f"report parser ok ({len(nodes)} nodes, all {len(expected)} expected found)")

# ---------------- star schema ----------------
def T(name, dc=3, vis=None, ms=0, **flags):
    base = {"Table Name": name, "Is Hidden": False, "Description": "", "Lineage Tag": "", "Data Columns": dc,
            "Visible Columns": dc if vis is None else vis, "Measures": ms, "Is Calc Group": False,
            "Is Field Parameter": False, "Is Auto Date": False, "Is Agg Table": False, "Is Date Table": False,
            "Is Calc Table": False, "Is What-if": False, "Storage Mode": "Import"}
    base.update(flags)
    return base

tables = pd.DataFrame([
    T("Sales"), T("Product"), T("Category"), T("Date", **{"Is Date Table": True}),
    T("_Measures", dc=1, vis=0, ms=3), T("Orphan"), T("Budget"),
    T("Discount", dc=1, **{"Is Calc Table": True, "Is What-if": True}),
    T("Fields", **{"Is Field Parameter": True}), T("LocalDateTable_1", **{"Is Auto Date": True}),
    T("Customer"), T("CustomerGroup"), T("SalesAgg", **{"Is Agg Table": True}),
])
def R(a, fc, b, tc, f="Many", t="One", active=True):
    return {"Relationship": f"{a}->{b}", "From Table": a, "From Column": fc, "To Table": b, "To Column": tc,
            "From Cardinality": f, "To Cardinality": t, "Cross Filter": "OneDirection", "Is Active": active}
rels = pd.DataFrame([
    R("Sales", "ProductKey", "Product", "ProductKey"), R("Sales", "DateKey", "Date", "DateKey"),
    R("Product", "CategoryKey", "Category", "CategoryKey"), R("Budget", "CategoryKey", "Category", "CategoryKey"),
    R("Customer", "GroupKey", "CustomerGroup", "GroupKey", "Many", "Many"),
])
cls = ns["classify_tables"](tables, rels)
roles = dict(zip(cls["Table Name"], cls["Role"]))
assert roles == {"Sales": "Fact", "Product": "Snowflaked dimension / bridge", "Category": "Dimension",
                 "Date": "Date dimension", "_Measures": "Measure table", "Orphan": "Disconnected", "Budget": "Fact",
                 "Discount": "What-if parameter", "Fields": "Field parameter", "LocalDateTable_1": "Auto date table",
                 "Customer": "Many-to-many participant", "CustomerGroup": "Many-to-many participant",
                 "SalesAgg": "Aggregation table"}, roles
sf = ns["star_schema_findings"](cls, rels)
names = [(f["Object Name"], f["Finding"]) for f in sf]
assert any(o == "Orphan" and t.startswith("Table has no relationships") for o, t in names)
assert any(o == "Budget" and t.startswith("Fact table is not directly") for o, t in names)
assert not any(o in ("Discount", "Fields", "Customer", "Sales") and "no relationships" in t for o, t in names)
assert any(f["Object Name"] == "Product" and "bridge" in f["Suggestion"] for f in sf)
print("star schema ok")

# ---------------- dependency graph + unused ----------------
dmv = pd.DataFrame([
    {"Table Name": t, "Object Name": o, "Object Type": ot, "Referenced Table": rt,
     "Referenced Object": ro, "Referenced Object Type": rot}
    for t, o, ot, rt, ro, rot in [
        ("_Measures", "Total Sales", "MEASURE", "Sales", "Amount", "COLUMN"),
        ("_Measures", "Total Margin", "MEASURE", "Sales", "Margin", "CALC_COLUMN"),
        ("Sales", "Margin", "CALC_COLUMN", "Sales", "Amount", "COLUMN"),
        ("_Measures", "Dead Base", "MEASURE", "Sales", "", "TABLE"),
        ("_Measures", "Dead Top", "MEASURE", "_Measures", "Dead Base", "MEASURE"),
        ("_Measures", "Via AttrH", "MEASURE", "Product", "Size", "ATTRIBUTE_HIERARCHY"),
        ("Sales", "Amount", "ATTRIBUTE_HIERARCHY", "Sales", "Notes", "COLUMN"),      # ignored source
        ("Sales", "H1", "HIERARCHY", "Sales", "Notes", "COLUMN"),                    # ignored source
        ("_Measures", "Total Sales", "KPI", "_Measures", "Sales Goal", "MEASURE"),     # KPI -> root
        ("Region", "Region Filter", "ROWS_ALLOWED", "Region", "Owner", "COLUMN"),     # RLS -> root
    ]
])
edges, roots, seen = ns["build_dependency_edges"](dmv)
assert _meas("Sales Goal") in roots and _col("Region", "Owner") in roots
assert _col("Sales", "Notes") not in roots and not any(_col("Sales", "Notes") in v for v in edges.values())
assert _col("Product", "Size") in edges[_meas("Via AttrH")]
assert "KPI" in seen

def C(t, c, hidden=False, ctype="Data", sort="", key=False, expr=""):
    return {"Table Name": t, "Column Name": c, "Column Type": ctype, "Data Type": "Int64", "Is Hidden": hidden,
            "Description": "", "Lineage Tag": f"lt-{t}-{c}", "Expression": expr, "Sort By Column": sort, "Is Key": key}
columns = pd.DataFrame([
    C("Sales", "ProductKey", True), C("Sales", "DateKey", True), C("Sales", "Amount"), C("Sales", "Notes"),
    C("Sales", "OldFlag", True), C("Sales", "Margin", ctype="Calculated", expr="Sales[Amount]*0.2"),
    C("Sales", "OrderDate"),
    C("Date", "DateKey", key=True), C("Date", "MonthName", sort="MonthNo"), C("Date", "MonthNo", True),
    C("Date", "Fiscal Year"), C("Date", "Fiscal Quarter"),
    C("Product", "ProductKey", True), C("Product", "Name"), C("Product", "Size"), C("Product", "Unused Visible"),
    C("Store", "Name"), C("Store", "Address"),
    C("Fields", "Fields"), C("Fields", "Fields Fields", True), C("Fields", "Fields Order", True),
    C("LocalDateTable_1", "Year", True), C("SalesAgg", "SumAmt", True),
    C("Region", "Owner", True),
])
measures = pd.DataFrame([
    {"Table Name": "_Measures", "Measure Name": n, "Expression": e, "Description": d, "Is Hidden": h,
     "Lineage Tag": f"lt-{n}", "Display Folder": "", "Format String": ""}
    for n, e, d, h in [
        ("Total Sales", "SUM(Sales[Amount])", "Sum of sales", False),
        ("Total Margin", "// margin\nSUM(Sales[Margin])", "", False),
        ("Dead Base", "COUNTROWS(Sales)", "", True),
        ("Dead Top", "[Dead Base] * 2", "", False),
        ("Sales Goal", "1000", "", True),
        ("Via AttrH", "COUNTROWS(VALUES(Product[Size]))", "", False),
        ("In Field Param", "1", "", False),
    ]
])
for r in rels.to_dict("records"):
    roots |= {_col(r["From Table"], r["From Column"]), _col(r["To Table"], r["To Column"])}
roots |= {_col("Date", "DateKey")}
roots |= ns["nameof_references"]("{(\"X\", NAMEOF([In Field Param]), 0), (\"Via\", NAMEOF([Via AttrH]), 1)}")
roots |= {_col("Fields", c) for c in ("Fields", "Fields Fields", "Fields Order")}
roots |= {_meas("Total Margin"), _col("Product", "Name"), _col("Store", "Name"), _col("Date", "MonthName"),
          _hier("Date", "Fiscal"), _col("Sales", "OrderDate")}
used = ns["find_used_objects"](
    roots, edges, sort_by={("Date", "MonthName"): "MonthNo"},
    group_by={("Fields", "Fields"): ["Fields Fields"]}, calc_table_of_column={},
    hierarchy_columns={("Date", "Fiscal"): ["Fiscal Year", "Fiscal Quarter"]})
excluded = {"LocalDateTable_1", "SalesAgg", "Fields"}
un = ns["unused_objects"](columns, measures, used, excluded, "High", {("Sales", "Notes"): 5_000_000})
got = set(zip(un["Object Type"], un["Object Name"]))
assert got == {("Column", "Notes"), ("Column", "OldFlag"), ("Column", "Unused Visible"), ("Column", "Address"),
               ("Measure", "Total Sales"), ("Measure", "Dead Base"), ("Measure", "Dead Top")}, got
assert un.iloc[0]["Object Name"] == "Notes"
assert un[un["Object Name"] == "Notes"]["Recommendation"].iloc[0] == "Hide → check logs → back up → remove."
assert un[un["Object Name"] == "OldFlag"]["Recommendation"].iloc[0] == "Strong candidate: check logs → back up → remove."
logged = ns["unused_objects"](columns, measures, used, excluded, "High", {}, edges=edges, query_log_days=30)
assert "logs clear" in logged["Recommendation"].iloc[0]
low = ns["unused_objects"](columns, measures, used, excluded, "Low")
assert low["Recommendation"].str.startswith("Don't remove yet").all()
med = ns["unused_objects"](columns, measures, used, excluded, "Medium")
assert med["Recommendation"].str.startswith("Likely:").all()
dl = ns["unused_objects"](columns, measures, used, excluded, "High", {}, direct_lake=True)
assert dl[dl["Object Name"] == "Notes"]["Size Note"].iloc[0].startswith("Not loaded")
# AnyColumn wildcard keeps same-named columns
used2 = used | {_anycol("Address")}
assert "Address" not in set(ns["unused_objects"](columns, measures, used2, excluded, "High")["Object Name"])
print("unused ok:", sorted(got))

uc = ns["usage_confidence"]
OK30 = ("ok", "query logs for 30 days checked (5 queries, 1 from Excel)")
assert uc(True, False, 0, 0, {}, True, (), OK30)[0] == "Medium"          # verified logs lift "no reports" to Medium
assert uc(True, False, 2, 2, {"PaginatedReport": 1}, True, (), OK30)[0] == "High"
assert "Also query logs for 30 days checked" in uc(True, False, 2, 2, {}, True, (), OK30)[1]
assert uc(True, False, 3, 2, {}, True, ["X"], OK30)[0] == "Medium"       # unread reports still Medium
PART = ("partial", "monitoring data only goes back 3 days of the 30 requested")
assert uc(True, False, 0, 0, {}, True, (), PART)[0] == "Low"             # partial logs never raise confidence
assert uc(True, False, 2, 2, {"PaginatedReport": 1}, True, (), PART)[0] == "Medium"
assert "can't vouch" in uc(True, False, 2, 2, {}, True, (), PART)[1]
assert "query-log check failed" in uc(True, False, 2, 2, {}, True, (), ("failed", "boom"))[1]
assert "set MONITORING_DAYS" in uc(True, False, 2, 2, {}, True)[1]
assert uc(False, False, 0, 0, {}, True)[0] == "Low"
assert uc(True, True, 0, 0, {}, True)[0] == "Unknown"
assert uc(True, False, 0, 0, {}, True)[0] == "Low"
assert uc(True, False, 3, 0, {}, True)[0] == "Unknown"            # none of the reports readable
assert uc(True, False, 3, 2, {}, True, ["Locked"])[0] == "Medium"
assert "Locked" in uc(True, False, 3, 2, {}, True, ["Locked"])[1]
assert uc(True, False, 2, 2, {"PaginatedReport": 1}, True)[0] == "Medium"
assert "1 PaginatedReport" in uc(True, False, 2, 2, {"PaginatedReport": 1}, True)[1]
assert uc(True, False, 2, 2, {}, False)[0] == "Low"               # lineage unavailable / incomplete
assert uc(True, False, 2, 2, {}, True)[0] == "High"
assert "Excel" in uc(True, False, 2, 2, {}, True)[1]
print("confidence ok")

# ---------------- documentation ----------------
exprs = pd.DataFrame([
    {"Object Type": "M Partition", "Table Name": "Sales", "Object Name": "Sales", "Expression": "let\n Source = Sql.Database(\"srv\", \"db\"),\n Filtered = Table.SelectRows(Source, each [Amount] > 0)\nin Filtered",
     "Language": "M", "Description": "", "Lineage Tag": ""},
    {"Object Type": "Calculated Table", "Table Name": "LocalDateTable_1", "Object Name": "LocalDateTable_1",
     "Expression": "CALENDAR(MIN(x), MAX(x))", "Language": "DAX", "Description": "", "Lineage Tag": ""},
])
long_measure = pd.concat([measures, pd.DataFrame([{"Table Name": "_Measures", "Measure Name": "Long One",
    "Expression": "SUMX(Sales, Sales[Amount] * 2) " * 12, "Description": "", "Is Hidden": False,
    "Lineage Tag": "lt-long", "Display Folder": "", "Format String": ""}])], ignore_index=True)
inv, df = ns["documentation_rows"](tables, columns, long_measure, exprs, skip_tables={"LocalDateTable_1", "Fields"}, long_chars=300, short_chars=80)
assert len(inv) == len(tables) + len(columns) + len(long_measure) + len(exprs)
assert inv["Has Comment"].map(type).eq(bool).all()
assert inv["Expression Hash"].str.len().isin([0, 16]).all()
by = {(f["Object Name"], f["Category"]): f["Severity"] for f in df}
assert ("Total Margin", "Comments") not in by
assert ("Total Sales", "Comments") not in by              # 18 chars: below the short threshold, not flagged
assert by[("Long One", "Comments")] == "Warning"           # long visible -> Warning
assert by[("Sales", "Comments")] == "Info"                 # M partition -> Info
assert ("Total Sales", "Descriptions") not in by
assert by[("Dead Top", "Descriptions")] == "Warning"       # visible measure, no description
assert ("Dead Base", "Descriptions") not in by             # hidden
assert ("LocalDateTable_1", "Comments") not in by          # auto-generated skipped
assert not any(t == "Fields" for (t, _c) in by)            # field param table skipped
print("documentation ok")

# ---------------- change tracking ----------------
def snap(rows):
    return pd.DataFrame([{"Object_Type": "Measure", "Table_Name": "_Measures", "Object_Name": n,
                          "Lineage_Tag": lt, "Expression_Hash": h, "Description": d} for n, lt, h, d in rows])
prev = snap([("A", "lt1", "h1", "desc A"), ("B", "lt2", "h2", ""), ("C", "lt3", "h3", "c"), ("Old", "lt9", "h9", "")])
cur = snap([("A", "lt1", "h1x", "desc A"), ("B2", "lt2", "h2", ""), ("C", "lt3", "h3", "c new"), ("New", "lt10", "h10", "")])
ch = ns["compute_changes"](prev, cur)
kinds = set(zip(ch["Change"], ch["Object_Name"]))
assert kinds == {("Expression changed", "A"), ("Renamed", "B2"), ("Description changed", "C"),
                 ("Added", "New"), ("Removed", "Old")}, kinds
assert ch[(ch["Change"] == "Expression changed")]["Description_May_Be_Stale"].iloc[0] == True
assert ns["compute_changes"](pd.DataFrame(), cur).empty
print("changes ok")

# ---------------- v3: case-insensitivity, alias fallback, removal order, roles ----------------
assert _col("Sales", "Qty") == _col("sales", "QTY") and _meas("Total") == _meas("TOTAL")
cols3 = pd.DataFrame([C("Sales", "Qty"), C("Sales", "Unused"), C("Date", "Fiscal Year"), C("Date", "Fiscal Month"),
                      C("Sales", "Base"), C("Sales", "Derived", ctype="Calculated", expr="Sales[Base]*2")])
meas3 = pd.DataFrame([{"Table Name": "M", "Measure Name": "Ext Ref", "Expression": "1", "Description": "",
                       "Is Hidden": False, "Lineage Tag": "", "Display Folder": "", "Format String": ""}])
r3 = ns["dax_references"]("SUM(sales[qty]) + [ext ref]")          # lower-case DAX from a report extension
r3 |= ns["extract_report_fields"]({"Hierarchy": {"Expression": {"SourceRef": {"Source": "zz"}}, "Hierarchy": "fiscal"}})
assert _anyhier("Fiscal") in r3
e3, _, _ = ns["build_dependency_edges"](pd.DataFrame([{"Table Name": "Sales", "Object Name": "Derived",
    "Object Type": "CALC_COLUMN", "Referenced Table": "Sales", "Referenced Object": "Base", "Referenced Object Type": "COLUMN"}]))
u3 = ns["find_used_objects"](r3, e3, {}, {}, {}, {("Date", "Fiscal"): ["Fiscal Year", "Fiscal Month"]},
                             list(zip(cols3["Table Name"], cols3["Column Name"])))
un3 = ns["unused_objects"](cols3, meas3, u3, set(), "High", edges=e3)
names3 = set(un3["Object Name"])
assert names3 == {"Unused", "Base", "Derived"}, names3            # Qty, Ext Ref, both Fiscal levels kept
base = un3[un3["Object Name"] == "Base"].iloc[0]
assert base["Used Only By Unused"] == "Sales[Derived]" and "After: Sales[Derived]" in base["Recommendation"]
print("v3 case/alias/removal-order ok")

tables4 = pd.DataFrame([T("Fact"), T("Dim"), T("RolePlay"), T("HiddenOrphan", vis=0)])
rels4 = pd.DataFrame([R("Fact", "K", "Dim", "K"), R("Fact", "K2", "RolePlay", "K", active=False)])
cls4 = ns["classify_tables"](tables4, rels4)
roles4 = dict(zip(cls4["Table Name"], cls4["Role"]))
assert roles4["RolePlay"] == "Inactive relationships only" and roles4["HiddenOrphan"] == "Disconnected", roles4
sf4 = ns["star_schema_findings"](cls4, rels4)
ho = next(x for x in sf4 if x["Object Name"] == "HiddenOrphan")
assert ho["Severity"] == "Info" and "all its columns are hidden" in ho["Finding"]
assert any(x["Object Name"] == "RolePlay" and "inactive" in x["Finding"] for x in sf4)
print("v3 roles ok")

# ---------------- v3: grouped issues and summary quality on a NOISY model ----------------
F_ = ns["finding"]
noisy = []
for i in range(40):   # typical: dozens of per-object formatting warnings
    noisy.append(F_("BPA", "Formatting", "Warning", "Measure", "M", f"Measure {i}", "Provide format string for measures", "Add a format string."))
for i in range(25):
    noisy.append(F_("BPA", "Formatting", "Warning", "Column", "Sales", f"'Sales'[C{i}]", "Do not summarize numeric columns", "Set Summarize By to None."))
noisy.append(F_("BPA", "Error Prevention", "Error", "Relationship", "", "'A'[k] -> 'B'[k]", "Relationship columns should be of the same data type", "Match the data types."))
noisy += [F_("BPA", "DAX Expressions", "Warning", "Measure", "M", f"Ratio {i}", "Use the DIVIDE function for division", "Use DIVIDE.") for i in range(4)]
noisy.append(F_("Star schema", "Model structure", "Warning", "Table", "Budget", "Budget", "Fact table is not directly related to the marked date table.", "Relate it."))
for i in range(30):
    noisy.append(F_("Documentation", "Descriptions", "Info", "Column", "Sales", f"Col{i}", "Missing description.", "Add one."))
for i in range(8):
    noisy.append(F_("Documentation", "Descriptions", "Info", "Table", f"T{i}", f"T{i}", "Missing description.", "Add one."))
for i in range(12):
    noisy.append(F_("Documentation", "Descriptions", "Warning", "Measure", "M", f"Measure {i}", "Missing description.", "Add one."))
noisy_df = pd.DataFrame(noisy)
unused_n = ns["unused_objects"](columns, measures, used, excluded, "Medium", {("Sales", "Notes"): 5_000_000})
issues = ns["group_issues"](noisy_df, unused_n, "Medium")
print("\nGrouped issues for a noisy model (", len(noisy_df), "raw findings ):")
print(issues[["Severity", "Area", "Issue", "Count"]].to_string())
assert len(issues) <= 12, len(issues)                              # ~120 findings -> a handful of issue types
assert issues.iloc[0]["Area"] == "BPA: Error Prevention"          # the one real error leads
order = list(issues["Area"])
w = issues[issues["Severity"] == "Warning"]
wa = list(w["Area"])
assert wa.index("BPA: DAX Expressions") < wa.index("Star schema") < wa.index("BPA: Formatting") < wa.index("Documentation")
assert issues[issues["Area"] == "Usage"]["Severity"].iloc[0] == "Info"        # Medium confidence -> Info
fmt = issues[issues["Issue"] == "Provide format string for measures"].iloc[0]
assert fmt["Count"] == 40 and "(+37 more)" in fmt["Examples"]
other = issues[issues["Issue"] == "Other documentation gaps"]
assert len(other) == 1 and other.iloc[0]["Count"] == 38 and "30 Columns without descriptions" in other.iloc[0]["Examples"]
assert (issues["Issue"] == "Visible measures without descriptions").sum() == 1
assert issues.iloc[-1]["Issue"] == "Other documentation gaps"                # always last
assert issues[issues["Area"] == "Usage"]["Issue"].iloc[0].startswith("Unused objects (")
assert issues[issues["Issue"] == "Use the DIVIDE function for division"]["Fix"].iloc[0].startswith("Replace a / b with DIVIDE(a, b)")
assert ns["_short_fix"]("Unknown rule", "First sentence here. Second sentence.") == "First sentence here."

roles_df = pd.DataFrame({"Table Name": ["Sales", "Date", "Product"], "Role": ["Fact", "Date dimension", "Dimension"]})
doc_inv, _ = ns["documentation_rows"](tables, columns, long_measure, exprs, set(), 300)
changes_df = pd.DataFrame(
    [["Added", "Column", "S", f"new{i}", "", False] for i in range(30)] +
    [["Expression changed", "Measure", "M", "Total Sales", "", True], ["Renamed", "Measure", "M", "B2", "M.B", False]],
    columns=["Change", "Object_Type", "Table_Name", "Object_Name", "Previous_Name", "Description_May_Be_Stale"])
sec = ns["model_summary_markdown"](
    "Sales Model", "OK", {"Dataset Name": "Sales Model", "Errors": 1, "Warnings": 81}, issues,
    {"Confidence": "Medium", "Confidence Detail": "1 of 3 reports could not be read (Locked). Excel..."},
    pd.DataFrame([{"Report Name": "Locked", "Error": "PermissionError: 403"}]), unused_n, roles_df, doc_inv, changes_df, 12,
    has_previous=True, dictionary_file="dictionary_Sales_Model.md")
print("\n" + sec)
assert sec.index("### Priority issues") < sec.index("### Unused objects") < sec.index("### Model shape") < sec.index("### Documentation")
assert "Reports not read: Locked (PermissionError: 403)" in sec
assert "**Fact** (1): Sales" in sec
docsec = sec[sec.index("### Documentation"):]
assert "Visible measures needing documentation (longest first)" in docsec and docsec.index("Long One") < docsec.index("Dead Top")
assert "Added: 30" in sec and "new1 " not in sec                    # Added collapsed to a count
chsec = sec[sec.index("### Changes"):]
assert chsec.index("| Expression changed") < chsec.index("| Renamed")    # stale first
assert len(sec.splitlines()) < 90, len(sec.splitlines())

import datetime
meta_ = {"workspace": "WS", "run_id": "abc", "run_ts": datetime.datetime(2026, 11, 8), "labs_version": "0.18.1"}
sc = pd.DataFrame([{"Dataset Name": f"M{i}", "Status": "OK", "Errors": i, "Warnings": 10 - i} for i in range(6)] +
                  [{"Dataset Name": "Bad", "Status": "FAILED at Read model metadata", "Errors": 0, "Warnings": 0}])
ws_md = ns["workspace_summary_markdown"](meta_, sc, {f"M{i}": f"## M{i}\nbody" for i in range(6)},
                                         pd.DataFrame([{"Dataset Name": "Bad", "Step": "Read model metadata", "Error": "XMLA"}]))
assert "## M5" in ws_md and "## M4" in ws_md and "## M0" not in ws_md   # >3 models: only the 2 worst in detail
assert "FAILED at Read model metadata" in ws_md and "Steps that failed" in ws_md
empty_md = ns["workspace_summary_markdown"](meta_, pd.DataFrame(columns=["Dataset Name", "Status", "Errors", "Warnings"]), {}, pd.DataFrame())
assert "No models were analyzed" in empty_md
assert ns["group_issues"](pd.DataFrame(columns=ns["FINDING_COLUMNS"]), None, "").empty
assert ns["rank_findings"](pd.DataFrame()).empty

dic = ns["dictionary_markdown"]("Sales Model", tables, dict(zip(cls["Table Name"], cls["Role"])), columns, long_measure,
                                {"LocalDateTable_1"}, exprs)
assert "### [Total Sales]" in dic and "```dax\nSUM(Sales[Amount])\n```" in dic and "LocalDateTable_1" not in dic
assert "**Power Query (`Sales`)**" in dic and "```powerquery\nlet" in dic
assert "**Calculated column `Margin`**" in dic
assert ns["safe_name"]("Sales / Finance Model") == "Sales_Finance_Model"
print("\nv3 summary quality ok")
print("ALL CORE TESTS PASSED")

# ---------------- v4 additions ----------------
# DMV typing: calc items / KPIs / unknown types are roots; partitions and format-string rows are edges
dmv4 = pd.DataFrame([
    {"Table Name": t, "Object Name": o, "Object Type": ot, "Referenced Table": rt, "Referenced Object": ro, "Referenced Object Type": rot}
    for t, o, ot, rt, ro, rot in [
        ("CG", "YTD", "CALC_ITEM", "M", "Base", "MEASURE"),
        ("CG", "Prior", "CALCULATION_ITEM", "M", "Base2", "MEASURE"),
        ("Calc", "Calc-part", "PARTITION", "Sales", "Amount", "COLUMN"),
        ("M", "Fmt", "MEASURE_FORMAT_STRING", "M", "FmtHelper", "MEASURE"),
        ("X", "Y", "SOMETHING_NEW", "Sales", "Weird", "COLUMN"),
        ("M", "Z", "MEASURE", "Sales", "Q", "MYSTERY_TYPE"),
    ]])
e4, r4, notes4 = ns["build_dependency_edges"](dmv4)
assert _meas("Base") in r4 and _meas("Base2") in r4 and _col("Sales", "Weird") in r4
assert _col("Sales", "Amount") in e4[_tbl("Calc")] and _meas("FmtHelper") in e4[_meas("Fmt")]
assert any("MYSTERY_TYPE" in n for n in notes4)
# AnyColumn pulls in that column's Sort By target
u4 = ns["find_used_objects"]({_anycol("MonthName")}, {}, {("Date", "MonthName"): "MonthNo"}, {}, {}, {},
                             [("Date", "MonthName"), ("Date", "MonthNo")])
assert _col("Date", "MonthNo") in u4
# file names: collisions get an id suffix
stems = ns["unique_file_names"]([{"name": "Sales Model", "id": "aaaaaaaa-1"}, {"name": "Sales_Model", "id": "bbbbbbbb-2"},
                                 {"name": "HR", "id": "c"}])
assert len(set(stems.values())) == 3 and stems["HR"] == "HR"
# markdown safety: CR/LF and pipes in cells, backticks inside DAX
tbl = ns["_md_table"](pd.DataFrame([{"A": "line1\r\nline2 | x", "B": "`code`"}]), ["A", "B"], 5)
assert tbl.startswith("\n|") and "line1 line2 \\| x" in tbl and "\r" not in tbl
fence = ns["_fence"]("VAR x = \"```\"\r\nRETURN x", "dax")
assert fence.startswith("````dax\n") and fence.endswith("\n````") and "\r" not in fence
# failed model section is short and honest; first-run and no-change wording
failed_sec = ns["model_summary_markdown"]("Bad", "FAILED at Read model metadata: XMLA", {"Dataset Name": "Bad", "Errors": None},
                                          pd.DataFrame(), {}, None, None, None, None, None)
assert "could not be read" in failed_sec and "dictionary" not in failed_sec and "Scorecard" not in failed_sec
ok_sec = ns["model_summary_markdown"]("M", "OK", {}, pd.DataFrame(), {}, None, None, None, None, None)
assert "Unused objects — not run" in ok_sec and "First run for this model" in ok_sec and "dictionary" not in ok_sec
nochg = ns["model_summary_markdown"]("M", "OK", {}, pd.DataFrame(), {"Confidence": "High", "Confidence Detail": "d"},
                                     None, pd.DataFrame(), None, None, pd.DataFrame(), has_previous=True)
assert "_No changes since the previous run._" in nochg and "_No unused objects found._" in nochg
# Direct Lake / no Vertipaq: sizes show n/a, not 0.0
dl_un = ns["unused_objects"](columns, measures, used, excluded, "High", {}, direct_lake=True)
dl_sec = ns["model_summary_markdown"]("M", "OK", {}, pd.DataFrame(), {"Confidence": "High", "Confidence Detail": "d"},
                                      None, dl_un, None, None, None, sizes_available=False)
assert "| n/a |" in dl_sec and "| 0.0 |" not in dl_sec
# big unused columns rank right after DAX issues
big = ns["unused_objects"](columns, measures, used, excluded, "High", {("Sales", "Notes"): 500 * 1_048_576})
gi = ns["group_issues"](noisy_df, big, "High")
ga = list(gi["Area"])
assert gi[gi["Area"] == "Usage"]["Severity"].iloc[0] == "Warning"
assert ga.index("BPA: DAX Expressions") < ga.index("Star schema") < ga.index("Usage") < ga.index("BPA: Formatting"), ga
# workspace summary picks the worst models by errors + key warnings, not raw formatting warnings
scw = pd.DataFrame([{"Dataset Name": "FormattingHeavy", "Status": "OK", "Errors": 0, "Key Warnings": 0, "Warnings": 90},
                    {"Dataset Name": "RealProblems", "Status": "OK", "Errors": 2, "Key Warnings": 5, "Warnings": 6},
                    {"Dataset Name": "Fine", "Status": "OK", "Errors": 0, "Key Warnings": 1, "Warnings": 1},
                    {"Dataset Name": "AlsoFine", "Status": "OK", "Errors": 0, "Key Warnings": 0, "Warnings": 0}])
wsm = ns["workspace_summary_markdown"](meta_, scw, {n: f"## {n}\nx" for n in scw["Dataset Name"]}, pd.DataFrame())
assert "## RealProblems" in wsm and "## Fine" in wsm and "## FormattingHeavy" not in wsm
print("v4 additions ok")
print("ALL CORE TESTS PASSED (v4)")

# ---------------- v5 additions ----------------
import datetime as _dt
now = pd.Timestamp("2026-11-08", tz="UTC")
jq = ns["judge_query_logs"]
assert jq({"queries": 900, "excel": 40, "first": now - pd.Timedelta(days=30)}, 30, 3, now)[0] == "ok"
assert "40 from Excel" in jq({"queries": 900, "excel": 40, "first": now - pd.Timedelta(days=30)}, 30, 3, now)[1]
assert jq({"queries": 900, "excel": 0, "first": now - pd.Timedelta(days=5)}, 30, 3, now)[0] == "partial"   # monitoring too new
assert jq({"queries": 0, "excel": 0, "first": now - pd.Timedelta(days=30)}, 30, 3, now)[0] == "partial"    # nothing logged
assert jq({"queries": 0, "excel": 0, "first": now - pd.Timedelta(days=30)}, 30, 0, now)[0] == "ok"         # no reports, quiet model
assert jq({"queries": 60000, "excel": 0, "first": now - pd.Timedelta(days=30)}, 30, 3, now)[0] == "partial" # cap hit
assert jq({"queries": 10, "excel": 0, "first": now - pd.Timedelta(days=7)}, 7, 3, now)[0] == "partial"      # window too short
assert jq({"queries": 10, "excel": 0, "first": None}, 30, 3, now)[0] == "partial"
# NaN-safe keys and DMV rows
assert ns["_k"](float("nan")) == "" and ns["_k"](None) == ""
e5, r5, _ = ns["build_dependency_edges"](pd.DataFrame([{"Table Name": float("nan"), "Object Name": "x", "Object Type": float("nan"),
    "Referenced Table": "T", "Referenced Object": "C", "Referenced Object Type": "COLUMN"}]))
assert _col("T", "C") in r5
# escaped ]] in names
r6 = ns["dax_references"]("SUM('Sales'[Amount [USD]]]) + [Margin [%]]]")
assert _col("Sales", "Amount [USD]") in r6 and _meas("Margin [%]") in r6
# noisy performance rules rank below star schema; star schema right after DAX
nz = pd.DataFrame([F_("BPA", "Performance", "Warning", "Column", "S", f"'S'[c{i}]", "Do not use floating point data types", "x") for i in range(30)]
                  + [F_("Star schema", "Model structure", "Warning", "Table", "Budget", "Budget", "Fact table is not directly related to the marked date table.", "x"),
                     F_("BPA", "Performance", "Warning", "Relationship", "", "r", "Many-to-many relationships should be single-direction", "x")])
gnz = list(ns["group_issues"](nz, None, "")["Issue"])
assert gnz.index("Fact table is not directly related to the marked date table.") < gnz.index("Do not use floating point data types")
assert gnz.index("Many-to-many relationships should be single-direction") < gnz.index("Do not use floating point data types")
assert ns["_short_fix"]("Remove auto-date table", "").startswith("First repoint visuals")
# markdown: leading block characters are escaped
assert ns["_md_cell"]("# Sales") == "\\# Sales" and ns["_md_cell"]("- bullet") == "\\- bullet"
# lineage tag appearing between runs is the same object, not Added + Removed
prev7 = snap([("A", "", "h1", "d")]); cur7 = snap([("A", "lt-new", "h1", "d")])
assert ns["compute_changes"](prev7, cur7).empty
# dictionary split at section boundaries
big_md = "# T\n" + "".join(f"## Table {i}\n" + "x" * 1000 + "\n" for i in range(400))
parts = ns["split_markdown"](big_md, 150_000)
assert len(parts) == 3 and all(len(p) <= 151_000 for p in parts) and all(p.startswith(("# T", "## Table")) for p in parts)
# relationships in the dictionary and model shape
rel_df = pd.DataFrame([R("Sales", "ProductKey", "Product", "ProductKey"), R("A", "k", "B", "k", "Many", "Many", active=False)])
d8 = ns["dictionary_markdown"]("M", tables.head(1), {}, columns.head(0), measures.head(0), set(), None, relationships=rel_df)
assert "## Relationships" in d8 and "Sales[ProductKey]" in d8 and "many-to-many" in d8
s8 = ns["model_summary_markdown"]("M", "OK", {}, pd.DataFrame(), {}, None, None, roles_df, None, None, relationships=rel_df)
assert "Relationships: 2 (1 inactive, 0 bi-directional, 1 many-to-many)" in s8
# zero-table model: classify returns a typed empty frame
empty_cls = ns["classify_tables"](tables.head(0), rels.head(0))
assert "Role" in empty_cls.columns and empty_cls.empty
print("v5 additions ok")
print("ALL CORE TESTS PASSED (v5)")

# ---------------- v6 additions ----------------
# select_models: case-insensitive names, default models only when named, skip list, missing names reported
ALL = [{"name": "Sales Model", "id": "1", "is_default": False}, {"name": "LH1", "id": "2", "is_default": True},
       {"name": "Finance", "id": "3", "is_default": False}]
sel, missing, left = ns["select_models"](ALL, [], [])
assert [m["name"] for m in sel] == ["Sales Model", "Finance"] and missing == [] and left == ["LH1"]
sel, missing, left = ns["select_models"](ALL, ["sales model ", "Nope"], [])
assert [m["name"] for m in sel] == ["Sales Model"] and missing == ["Nope"] and left == []
sel, _, _ = ns["select_models"](ALL, ["LH1"], [])
assert [m["name"] for m in sel] == ["LH1"]                         # a default model is scanned when named
sel, _, _ = ns["select_models"](ALL, [], ["FINANCE"])
assert [m["name"] for m in sel] == ["Sales Model"]
assert ns["select_models"]([], ["X"], []) == ([], ["X"], [])
assert ns["duplicate_names"]([{"name": "A"}, {"name": "B"}, {"name": "A"}]) == ["A"]

# DMV: a plain COLUMN or TABLE source is an edge (used only if the source is used), never silently dropped
e9, r9, _ = ns["build_dependency_edges"](pd.DataFrame([
    {"Table Name": "T", "Object Name": "A", "Object Type": "COLUMN", "Referenced Table": "T", "Referenced Object": "B", "Referenced Object Type": "COLUMN"},
    {"Table Name": "T", "Object Name": "", "Object Type": "TABLE", "Referenced Table": "U", "Referenced Object": "C", "Referenced Object Type": "COLUMN"},
    {"Table Name": "CG", "Object Name": "YTD", "Object Type": "CALC_GROUP", "Referenced Table": "", "Referenced Object": "Base", "Referenced Object Type": "MEASURE"},
]))
assert _col("T", "B") in e9[_col("T", "A")] and _col("U", "C") in e9[_tbl("T")] and _meas("Base") in r9
assert _col("T", "B") in ns["find_used_objects"]({_col("T", "A")}, e9, {}, {}, {}, {})
assert _col("T", "B") not in ns["find_used_objects"](set(), e9, {}, {}, {}, {})

# documentation worklist: changed-but-undescribed first, then measures (longest first), tables, M, columns
inv9, find9 = ns["documentation_rows"](tables, columns, long_measure, exprs, skip_tables={"LocalDateTable_1", "Fields"},
                                       long_chars=300, short_chars=80)
find9 = pd.DataFrame(find9)
chg9 = pd.DataFrame([["Expression changed", "Measure", "_Measures", "Total Sales", "", True],
                     ["Added", "Measure", "_Measures", "Dead Top", "", False]],
                    columns=["Change", "Object_Type", "Table_Name", "Object_Name", "Previous_Name", "Description_May_Be_Stale"])
wl = ns["doc_worklist"](find9, inv9, chg9)
assert list(wl.columns) == ns["WORKLIST_COLUMNS"]
first = wl.iloc[0]
assert first["Object Name"] == "Total Sales" and first["Needs"] == "review description (expression changed)"
assert first["Current Description"] == "Sum of sales" and first["Lineage Tag"] == "lt-Total Sales"
second = wl.iloc[1]
assert second["Object Name"] == "Long One" and second["Needs"] == "description + comment"
types = list(wl["Object Type"])
assert types.index("Measure") < types.index("Table") < types.index("M Partition") < types.index("Column"), types
assert (wl[["Draft Description", "Draft Comment", "Approved"]] == "").all().all()
assert not wl.duplicated(["Object Type", "Table Name", "Object Name"]).any()
assert ns["doc_worklist"](None, None, None).empty and ns["doc_worklist"](find9.head(0), inv9, None).empty

# the summary points at the worklist, and the header names the notebook version
sec9 = ns["model_summary_markdown"]("M", "OK", {}, pd.DataFrame(), {}, None, None, None, inv9, None,
                                    worklist_file="doc_worklist_M.csv", worklist_count=len(wl))
assert f"`doc_worklist_M.csv` ({len(wl)} objects)" in sec9
ws9 = ns["workspace_summary_markdown"]({**meta_, "notebook_version": "0.6.0"}, scw, {}, pd.DataFrame())
assert "Model Health 0.6.0" in ws9

# show_markdown never raises, with or without IPython
import io as _io, contextlib as _ctx
with _ctx.redirect_stdout(_io.StringIO()) as _b:
    ns["show_markdown"]("# hello")
print("v6 additions ok")
print("ALL CORE TESTS PASSED (v6)")
