# %% [markdown]
# # Power BI Model Health Check
#
# **Version 0.6.0 · read-only.** Scans the Power BI semantic models in a Fabric workspace and tells you, in ranked order, what to fix. Nothing in any model or report is changed.
#
# ## How to use it
# 1. **Attach a lakehouse** (Explorer pane → *Add lakehouse*). Results are saved there.
# 2. In **Step 1**, set `DATASETS` to one small model for your first run.
# 3. Select **Run all**. Step 4 checks your setup in a few seconds and stops with a plain message if something is missing.
# 4. Read the results in **Step 7**, or give `Files/model_health/latest/summary.md` to your Copilot agent.
#
# The only cell you edit is **Step 1**. Every other code cell has to run, but most have their code collapsed because you don't need to read it. Expand any cell to see what it does.
#
# ## What it checks
#
# | Check | What you get |
# |---|---|
# | **Best practices** | Microsoft's Best Practice Analyzer rules for DAX, performance and error prevention, grouped and ranked, each with a short fix. |
# | **Star schema** | A role for every table (fact, dimension, snowflaked, bridge, parameter…) and the structural problems worth fixing. |
# | **Unused columns and measures** | What nothing uses, checked against the model's own dependencies and every report bound to it, with a confidence level that says how far to trust the list. |
# | **Documentation** | Description and comment coverage, a data dictionary with full DAX and Power Query, a worklist for drafting what's missing, and which measures changed since the last run. |
# | **Size** | The largest columns, matched to the unused list to show likely savings. |
#
# ## What you need
# - **Fabric Runtime 1.3** (Spark 3.5). The first code cell checks this.
# - **XMLA endpoints** enabled for the tenant and capacity (your Fabric admin can confirm).
# - **Contributor** on the model's workspace, or **Write** on each model. *Build* alone can run queries but can't read the model metadata.
# - **Contributor** on the workspaces that hold the reports. Reports you can't read are listed as not read, and confidence drops.
# - *Optional:* **workspace monitoring** on the workspace, for the query-log check (`MONITORING_DAYS`). It's the only way to see Excel usage.
#
# ## Read-only guarantee
# Models are opened with `readonly=True`. The Best Practice Analyzer runs with `extended=False` and `export=False`. Report definitions are downloaded and parsed in memory. Nothing is saved back to a model or report. The only things written are result files and tables in the lakehouse you attach.

# %% [markdown]
# ## Step 0 — Install Semantic Link Labs
#
# Choose **one** option:
#
# | Option | When | What to do |
# |---|---|---|
# | **A. Environment** (best) | Scheduled runs, pipelines, High Concurrency sessions | Create a Fabric **Environment** → Public libraries → add `semantic-link-labs` version `0.18.1` → Save → Publish. Select it in this notebook's toolbar, then **delete or comment out the `%pip` line below**. |
# | **B. %pip** (default) | You can't create Environments and the notebook can reach PyPI | Leave the cell as is. It installs for this session only and takes ~30–60 s. |
# | **C. Offline wheels** | PyPI is blocked | See below. |
#
# **Option C:** on a PC with internet access, run:
# ```
# pip download semantic-link-labs==0.18.1 semantic-link-sempy==0.14.3 anytree polib jsonpath-ng ply sqlglot anywidget psygnal powerbiclient jupyter-ui-poll --no-deps -d wheels --platform manylinux2014_x86_64 --python-version 3.11 --only-binary=:all:
# ```
# The platform flags matter because one dependency (`psygnal`) has compiled wheels, and Fabric runs on Linux. Upload the `wheels` folder to the lakehouse at `Files/wheels`, then swap the `%pip` line for the commented offline line. `pyspark`, `ipywidgets`, `msal`, `requests` and `pandas` already come with Fabric Runtime 1.3. If the install still reports a missing package, download that one the same way and upload it.
#
# **Notes:**
# - `%pip` restarts the Python interpreter, so it sits at the top. Only the quick runtime check runs before it.
# - `%pip` isn't supported in High Concurrency sessions.
# - In a Data Pipeline notebook activity, `%pip` only works if the activity sets the boolean parameter `_inlineInstallationEnabled = True`. Otherwise use option A.

# %%
# Runtime check: semantic-link-labs 0.18.1 needs semantic-link-sempy 0.14.3, which needs Spark 3.5+ (Fabric Runtime 1.3).
import pyspark
if tuple(int(x) for x in pyspark.__version__.split(".")[:2]) < (3, 5):
    raise RuntimeError(
        f"This notebook needs Fabric Runtime 1.3 (Spark 3.5+); this session runs Spark {pyspark.__version__}. "
        "Switch the runtime in the workspace Spark settings or in the attached Environment, then restart the session."
    )
print(f"Spark {pyspark.__version__}: OK")

# %%
%pip install -q semantic-link-labs==0.18.1
# Option C (offline) — use this line instead of the one above:
# %pip install -q --no-index --find-links /lakehouse/default/Files/wheels semantic-link-labs==0.18.1

# %%
import importlib.metadata

NOTEBOOK_VERSION = "0.6.0"
TESTED_VERSION = "0.18.1"
try:
    _labs_version = importlib.metadata.version("semantic-link-labs")
except importlib.metadata.PackageNotFoundError:
    raise ImportError(
        "semantic-link-labs is not installed. Run the %pip cell above, or select a Fabric Environment that includes it."
    )
if tuple(int(x) for x in _labs_version.split(".")[:2]) < (0, 18):
    raise ImportError(f"semantic-link-labs {_labs_version} is too old; this notebook needs 0.18.x (tested on {TESTED_VERSION}).")
if _labs_version != TESTED_VERSION:
    print(f"Note: tested with semantic-link-labs {TESTED_VERSION}; you have {_labs_version}. If a step fails, pin {TESTED_VERSION}.")

import sempy_labs as labs
print(f"Model Health {NOTEBOOK_VERSION} · semantic-link-labs {_labs_version} ready")

# %% [markdown]
# ## Step 1 — Settings
# The only cell you normally edit. It's the **parameters** cell, so pipelines and scheduled runs can override any value. Lists can also be passed as `"A,B"` or `'["A","B"]'`.

# %% [parameters]
# --- What to scan ---
WORKSPACE = None            # None = the attached lakehouse's workspace (else this notebook's); or "Workspace Name"
DATASETS = []               # ["One Small Model"] for a first run; [] = every semantic model in the workspace
SKIP_DATASETS = []          # model names to always skip

# --- Which checks ---
RUN_BPA = True              # Best Practice Analyzer
RUN_VERTIPAQ = True         # column sizes
SCAN_REPORTS = True         # read report definitions to find which fields reports use
MONITORING_DAYS = 0         # >0: also check workspace monitoring query logs (Excel, ad-hoc DAX); 14-30 to count

# --- Where results go ---
WRITE_TO_LAKEHOUSE = True   # False = show results in the notebook only (no files, no tables, no change tracking)
TABLE_PREFIX = "mh_"

# --- Tuning (rarely changed) ---
TOP_N_COLUMNS = 50          # largest columns kept per model in mh_column_sizes
TOP_FINDINGS_PER_MODEL = 50 # individual findings per model in top_findings.csv
TOP_ISSUES_PER_MODEL = 12   # grouped issues per model in the summary files
LONG_EXPRESSION_CHARS = 300 # uncommented visible measures/calc columns at least this long are Warnings
SHORT_EXPRESSION_CHARS = 80 # uncommented expressions shorter than this are not flagged at all

# %% [markdown]
# ## Step 2 — Engine: analysis logic
# Function definitions only: nothing here talks to Fabric, so every function is unit-tested outside Fabric. The code is collapsed; expand a cell to read it.
#
# **Design rule:** when in doubt, an object counts as *used*. A missed cleanup costs nothing. A false "unused" can break a report if someone acts on it.
#
# ### 2a · Helpers and DAX parsing

# %% [engine]
import re
import json
import hashlib
import datetime
import uuid
from collections import deque

import pandas as pd

SEV_ERROR, SEV_WARNING, SEV_INFO = "Error", "Warning", "Info"
SEVERITY_ORDER = {SEV_ERROR: 0, SEV_WARNING: 1, SEV_INFO: 2}

FINDING_COLUMNS = [
    "Source", "Category", "Severity", "Object Type", "Table Name", "Object Name",
    "Finding", "Suggestion",
]

# BPA rules this notebook replaces with its own, more complete checks (avoids double counting).
BPA_RULES_SUPERSEDED = {
    "Visible objects with no description",   # -> Documentation findings
    "Ensure tables have relationships",       # -> Star schema "Disconnected" findings (role-aware)
    "Consider a star-schema instead of a snowflake architecture",  # -> Star schema snowflake findings
    "Remove unnecessary columns",             # -> Usage findings (adds report usage)
    "Remove unnecessary measures",            # -> Usage findings (adds report usage)
}


def as_list(value) -> list:
    """Accept a list, a JSON list string, or a comma-separated string (pipelines pass strings)."""
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        return [str(v) for v in value]
    s = str(value).strip()
    if not s:
        return []
    if s.startswith("["):
        try:
            return [str(v) for v in json.loads(s)]
        except ValueError:
            pass
    return [part.strip() for part in s.split(",") if part.strip()]


def as_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("1", "true", "yes", "y")


def select_models(all_models: list, datasets: list, skip: list) -> tuple:
    """
    Pick the models to scan from [{'name', 'id', 'is_default'}].
    Names match case-insensitively. Default models (auto-created with a lakehouse or warehouse) are
    scanned only when named in DATASETS. Returns (selected, names_not_found, default_models_left_out).
    """
    by_key = {}
    for m in all_models:
        by_key.setdefault(str(m["name"]).strip().casefold(), []).append(m)
    skip_keys = {str(n).strip().casefold() for n in skip}
    if datasets:
        wanted = [str(n).strip() for n in datasets]
        missing = sorted(n for n in wanted if n.casefold() not in by_key)
        keys = {n.casefold() for n in wanted}
        chosen = [m for m in all_models if str(m["name"]).strip().casefold() in keys]
        left_out = []
    else:
        missing = []
        chosen = [m for m in all_models if not m.get("is_default")]
        left_out = [m["name"] for m in all_models if m.get("is_default")]
    chosen = [m for m in chosen if str(m["name"]).strip().casefold() not in skip_keys]
    return chosen, missing, left_out


def duplicate_names(models: list) -> list:
    """Model names that appear more than once (results are keyed by name, so duplicates would collide)."""
    seen, dup = set(), []
    for m in models:
        if m["name"] in seen and m["name"] not in dup:
            dup.append(m["name"])
        seen.add(m["name"])
    return dup


# ---------- Expressions ----------

_STRING_LITERAL = re.compile(r'"(?:[^"]|"")*"')
_QUOTED_NAME = re.compile(r"'(?:[^']|'')*'")
_BRACKETED = re.compile(r"\[[^\]]*\]")
_DAX_COMMENT = re.compile(r"(//|--|/\*)")
_M_COMMENT = re.compile(r"(//|/\*)")


def has_comment(expression, language: str = "DAX") -> bool:
    """True if a DAX or M expression contains a comment (ignoring text inside strings, 'names' and [brackets])."""
    if not expression:
        return False
    s = _STRING_LITERAL.sub('""', str(expression))
    if language.upper() == "DAX":
        s = _QUOTED_NAME.sub("''", s)
    s = _BRACKETED.sub("[]", s)
    return bool((_DAX_COMMENT if language.upper() == "DAX" else _M_COMMENT).search(s))


def expression_hash(expression) -> str:
    """Whitespace-insensitive fingerprint, used to detect changed expressions between runs."""
    if not expression:
        return ""
    normalized = re.sub(r"\s+", " ", str(expression)).strip()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]


_BR = r"\[((?:[^\]]|\]\])+)\]"          # [name], where ]] is an escaped ]
_DAX_QUALIFIED = re.compile(r"(?:'((?:[^']|'')+)'|(?<![\w\[\]'])([^\W\d][\w\.]*))\s*" + _BR)
_DAX_BRACKET = re.compile(_BR)
_NAMEOF = re.compile(r"NAMEOF\s*\(\s*((?:'(?:[^']|'')+'|[^\W\d][\w\.]*)?)\s*\[([^\]]+)\]\s*\)", re.I)


def dax_references(expression) -> set:
    """
    Objects a DAX string might reference. Deliberately generous:
    Table[X] counts as both column Table[X] and measure X; a bare [X] counts as measure X
    and as 'any column named X'.
    """
    refs = set()
    if not expression:
        return refs
    s = _STRING_LITERAL.sub('""', str(expression))
    for m in _DAX_QUALIFIED.finditer(s):
        table = (m.group(1) or m.group(2)).replace("''", "'")
        name = m.group(3).replace("]]", "]")
        refs.add(_col(table, name))
        refs.add(_meas(name))
    for m in _DAX_BRACKET.finditer(_DAX_QUALIFIED.sub(" ", s)):
        name = m.group(1).replace("]]", "]")
        refs.add(_meas(name))
        refs.add(_anycol(name))
    return refs


def nameof_references(expression) -> set:
    """Field-parameter targets: NAMEOF('T'[C]) -> column T[C] (or measure C); NAMEOF([M]) -> measure M."""
    refs = set()
    for m in _NAMEOF.finditer(str(expression or "")):
        table, name = m.group(1).strip("'").replace("''", "'"), m.group(2)
        refs.add(_meas(name))
        refs.add(_col(table, name) if table else _anycol(name))
    return refs


# ---------- Graph nodes ----------
# DAX object names are case-insensitive, so every node key is casefolded.

def _k(value) -> str:
    if value is None or (isinstance(value, float) and value != value):   # None / NaN
        return ""
    return str(value).casefold()


def _col(table, column):
    return ("Column", _k(table), _k(column))


def _meas(name):
    return ("Measure", "", _k(name))


def _tbl(table):
    return ("Table", _k(table), "")


def _anycol(column):
    return ("AnyColumn", "", _k(column))


def _hier(table, hierarchy):
    return ("Hierarchy", _k(table), _k(hierarchy))


def _anyhier(hierarchy):
    return ("AnyHierarchy", "", _k(hierarchy))


def finding(source, category, severity, object_type, table, name, text, suggestion):
    return {
        "Source": source, "Category": category, "Severity": severity,
        "Object Type": object_type, "Table Name": table or "", "Object Name": name or "",
        "Finding": text, "Suggestion": suggestion,
    }


# %% [markdown]
# ### 2b · Report parser

# %% [engine]
# ---------- Report parsing (PBIR and legacy report.json) ----------

def _maybe_json(value):
    """Legacy report.json stores visual config and filters as JSON *strings*."""
    if isinstance(value, str):
        s = value.strip()
        if s[:1] in ("{", "["):
            try:
                return json.loads(s)
            except ValueError:
                return value
    return value


def extract_report_fields(obj, aliases=None, out=None) -> set:
    """
    Walk any report JSON and collect every model object it references:
    - {"Column"|"Measure": {"Expression": {"SourceRef": {...}}, "Property": X}}  (keyed by table + name)
    - {"Hierarchy": {"Expression": {"SourceRef"...}, "Hierarchy": H}}            (user hierarchies)
    - PropertyVariationSource                                                     (auto date/time on a date column)
    - query aliases ("From": [{"Name": "s", "Entity": "Sales"}])                  (legacy prototypeQuery)
    - DAX text in "Expression"/"expression" strings                               (report-level measures, visual calcs)
    """
    out = set() if out is None else out
    obj = _maybe_json(obj)
    if isinstance(obj, list):
        for item in obj:
            extract_report_fields(item, aliases, out)
        return out
    if not isinstance(obj, dict):
        return out

    aliases = dict(aliases or {})
    if isinstance(obj.get("From"), list):
        for f in obj["From"]:
            if isinstance(f, dict) and f.get("Name") and f.get("Entity"):
                aliases[f["Name"]] = f["Entity"]

    def entity_of(expr):
        if not isinstance(expr, dict):
            return None
        sr = expr.get("SourceRef")
        if isinstance(sr, dict):
            return sr.get("Entity") or aliases.get(sr.get("Source"))
        return None

    for key in ("Column", "Measure"):
        v = obj.get(key)
        if isinstance(v, dict) and v.get("Property"):
            ent = entity_of(v.get("Expression"))
            if key == "Measure":
                out.add(_meas(v["Property"]))
            if ent:
                out.add(_col(ent, v["Property"]))
            elif key == "Column":
                out.add(_anycol(v["Property"]))

    v = obj.get("Hierarchy")
    if isinstance(v, dict) and v.get("Hierarchy"):
        expr = v.get("Expression") or {}
        ent = entity_of(expr)
        out.add(_hier(ent, v["Hierarchy"]) if ent else _anyhier(v["Hierarchy"]))
        pvs = expr.get("PropertyVariationSource") if isinstance(expr, dict) else None
        if isinstance(pvs, dict) and pvs.get("Property"):
            ent2 = entity_of(pvs.get("Expression"))
            out.add(_col(ent2, pvs["Property"]) if ent2 else _anycol(pvs["Property"]))

    for k in ("Expression", "expression"):
        if isinstance(obj.get(k), str) and "[" in obj[k]:
            out |= dax_references(obj[k])

    for value in obj.values():
        if isinstance(value, (dict, list)) or (isinstance(value, str) and value.strip()[:1] in ("{", "[")):
            extract_report_fields(value, aliases, out)
    return out


def report_format(paths) -> str:
    return "PBIR" if any(p.startswith("definition/") for p in paths) else "PBIR-Legacy"


# %% [markdown]
# ### 2c · Star schema

# %% [engine]
# ---------- Star schema ----------

def relationship_ends(rel: dict):
    """(many_side_tables, one_side_tables, is_many_to_many) for one relationship."""
    if rel["From Cardinality"] == "Many" and rel["To Cardinality"] == "Many":
        return [], [], True
    many, one = [], []
    for table, card in ((rel["From Table"], rel["From Cardinality"]), (rel["To Table"], rel["To Cardinality"])):
        (many if card == "Many" else one).append(table)
    return many, one, False


def classify_tables(tables: pd.DataFrame, relationships: pd.DataFrame) -> pd.DataFrame:
    """Label every table with a role based on which side of active relationships it sits."""
    many_count, one_count, m2m_count, inactive_count = {}, {}, {}, {}
    for rel in relationships.to_dict("records"):
        if not rel.get("Is Active", True):
            for t in (rel["From Table"], rel["To Table"]):
                inactive_count[t] = inactive_count.get(t, 0) + 1
            continue
        many, one, m2m = relationship_ends(rel)
        if m2m:
            for t in (rel["From Table"], rel["To Table"]):
                m2m_count[t] = m2m_count.get(t, 0) + 1
        for t in many:
            many_count[t] = many_count.get(t, 0) + 1
        for t in one:
            one_count[t] = one_count.get(t, 0) + 1

    rows = []
    for t in tables.to_dict("records"):
        name = t["Table Name"]
        m, o, mm = many_count.get(name, 0), one_count.get(name, 0), m2m_count.get(name, 0)
        if t.get("Is Calc Group"):
            role = "Calculation group"
        elif t.get("Is Field Parameter"):
            role = "Field parameter"
        elif t.get("Is Auto Date"):
            role = "Auto date table"
        elif t.get("Is Agg Table"):
            role = "Aggregation table"
        elif t.get("Is Date Table"):
            role = "Date dimension"
        elif t.get("Is What-if"):
            role = "What-if parameter"
        elif m == 0 and o == 0 and mm == 0:
            if t.get("Visible Columns", 0) == 0 and t.get("Measures", 0) > 0:
                role = "Measure table"
            elif inactive_count.get(name):
                role = "Inactive relationships only"
            else:
                role = "Disconnected"
        elif m == 0 and o == 0:
            role = "Many-to-many participant"
        elif m > 0 and o == 0:
            role = "Fact"
        elif o > 0 and m == 0:
            role = "Dimension"
        else:
            role = "Snowflaked dimension / bridge"
        rows.append({**t, "Role": role, "Many-side Relationships": m, "One-side Relationships": o,
                     "Many-to-many Relationships": mm})
    return pd.DataFrame(rows, columns=list(tables.columns) + ["Role", "Many-side Relationships", "One-side Relationships",
                                                               "Many-to-many Relationships"])


def star_schema_findings(classified: pd.DataFrame, relationships: pd.DataFrame) -> list:
    """Structural checks the standard BPA rules don't already cover."""
    out = []
    roles = dict(zip(classified["Table Name"], classified["Role"]))
    date_tables = {t for t, r in roles.items() if r == "Date dimension"}
    neighbours = {t: set() for t in roles}
    for rel in relationships.to_dict("records"):
        if rel.get("Is Active", True):
            neighbours.setdefault(rel["From Table"], set()).add(rel["To Table"])
            neighbours.setdefault(rel["To Table"], set()).add(rel["From Table"])

    for t, role in roles.items():
        if role == "Disconnected":
            visible = int(classified.loc[classified["Table Name"] == t, "Visible Columns"].iloc[0] or 0)
            out.append(finding(
                "Star schema", "Model structure", SEV_WARNING if visible else SEV_INFO, "Table", t, t,
                "Table has no relationships" + (" and has visible columns." if visible else "; all its columns are hidden."),
                "If it is a slicer or parameter table, hide what users shouldn't pick and add a description; otherwise relate it to the model or remove it.",
            ))
        if role == "Inactive relationships only":
            out.append(finding(
                "Star schema", "Relationships", SEV_INFO, "Table", t, t,
                "Table is connected only through inactive relationships.",
                "Fine if measures activate them with USERELATIONSHIP; otherwise activate the relationship or remove the table.",
            ))
        if role == "Fact" and date_tables and not (neighbours.get(t, set()) & date_tables):
            out.append(finding(
                "Star schema", "Model structure", SEV_WARNING, "Table", t, t,
                "Fact table is not directly related to the marked date table.",
                "Relate the fact's date key to the date dimension so time intelligence works on this table.",
            ))
        if role == "Snowflaked dimension / bridge":
            out.append(finding(
                "Star schema", "Model structure", SEV_INFO, "Table", t, t,
                "Table sits on both sides of relationships (snowflaked dimension or bridge).",
                "If it is a dimension chained to another dimension, consider flattening their attributes into one table. If it is a bridge table for many-to-many, leave it as is and document it.",
            ))

    for rel in relationships.to_dict("records"):
        many, one, _ = relationship_ends(rel)
        if len(one) == 2:
            out.append(finding(
                "Star schema", "Relationships", SEV_INFO, "Relationship", rel["From Table"], rel["Relationship"],
                "One-to-one relationship.",
                "One-to-one usually means the two tables are one entity and can be merged.",
            ))
    return out


# %% [markdown]
# ### 2d · Unused objects and confidence

# %% [engine]
# ---------- Unused objects ----------

def _dmv_node(obj_type, table, name):
    """Map a DMV object type to a graph node by substring, the way semantic-link-labs normalises usage types."""
    t = _k(obj_type).upper()
    if "MEASURE" in t:
        return _meas(name)
    if "COLUMN" in t or t == "ATTRIBUTE_HIERARCHY":
        return _col(table, name)
    if "TABLE" in t or "PARTITION" in t:
        return _tbl(table)
    return None


def build_dependency_edges(dmv: pd.DataFrame):
    """
    Turn DISCOVER_CALC_DEPENDENCY rows into graph edges.
    - Measures, calculated columns, calculated tables, partitions and plain columns or tables become
      edges: their dependencies are used only if the object itself is used.
    - Hierarchy and relationship rows are ignored (attribute hierarchies reference every column;
      relationship columns are added as roots from the model metadata).
    - Everything else (RLS, calculation items, KPIs, unknown types) becomes a root: always in use.
    Returns (edges, roots, notes) where notes lists the source types seen and any unmapped referenced types.
    """
    edges, roots, seen, unmapped = {}, set(), set(), set()
    for r in dmv.to_dict("records"):
        src_type = _k(r.get("Object Type")).upper()
        seen.add(src_type)
        ref_type = r.get("Referenced Object Type")
        target = _dmv_node(ref_type, r.get("Referenced Table"), r.get("Referenced Object"))
        if target is None:
            unmapped.add(_k(ref_type).upper())
            continue
        if "HIERARCHY" in src_type or "RELATIONSHIP" in src_type:
            continue
        follows = ("MEASURE" in src_type or "PARTITION" in src_type or src_type in ("COLUMN", "TABLE")
                   or ("CALC" in src_type and ("COLUMN" in src_type or "TABLE" in src_type)))
        src = _dmv_node(src_type, r.get("Table Name"), r.get("Object Name")) if follows else None
        if src is not None:
            if src != target:
                edges.setdefault(src, set()).add(target)
            continue
        roots.add(target)   # RLS, calculation items, KPIs and anything unrecognised: always in use
    notes = sorted(seen) + ([f"unmapped referenced types: {sorted(unmapped)}"] if unmapped else [])
    return edges, roots, notes


def find_used_objects(roots: set, edges: dict, sort_by: dict, group_by: dict,
                      calc_table_of_column: dict, hierarchy_columns: dict, all_columns=()) -> set:
    """
    Breadth-first walk from the roots. A used column also pulls in its Sort By and Group By columns.
    A column of a calculated table pulls in the table (and so the table expression's sources).
    A used hierarchy pulls in all of its level columns; an unresolved hierarchy name pulls in every
    hierarchy with that name. Map keys are original names; matching is case-insensitive.
    """
    sb = {(_k(t), _k(c)): _k(v) for (t, c), v in sort_by.items() if v}
    gb = {(_k(t), _k(c)): [_k(x) for x in v] for (t, c), v in group_by.items()}
    ct = {(_k(t), _k(c)) for (t, c) in calc_table_of_column}
    hc = {(_k(t), _k(h)): [_k(x) for x in cols] for (t, h), cols in hierarchy_columns.items()}
    by_name = {}
    for (t, h) in hc:
        by_name.setdefault(h, []).append(t)
    cols_by_name = {}
    for (t, c) in all_columns:
        cols_by_name.setdefault(_k(c), []).append(_k(t))

    used, queue = set(), deque(roots)
    while queue:
        n = queue.popleft()
        if n in used:
            continue
        used.add(n)
        nxt = set(edges.get(n, ()))
        kind, t, name = n
        if kind == "Column":
            if sb.get((t, name)):
                nxt.add(("Column", t, sb[(t, name)]))
            nxt |= {("Column", t, g) for g in gb.get((t, name), ())}
            if (t, name) in ct:
                nxt.add(("Table", t, ""))
        elif kind == "Hierarchy":
            nxt |= {("Column", t, c) for c in hc.get((t, name), ())}
        elif kind == "AnyHierarchy":
            for table in by_name.get(name, ()):
                nxt.add(("Hierarchy", table, name))
        elif kind == "AnyColumn":
            for table in cols_by_name.get(name, ()):
                nxt.add(("Column", table, name))
        queue.extend(x for x in nxt if x not in used)
    return used


def usage_confidence(scan_enabled: bool, scan_failed: bool, reports_total: int, reports_scanned: int,
                     other_downstream: dict, lineage_available: bool, unscanned_names=(), query_logs=None) -> tuple:
    """
    Returns (level, explanation). Levels:
      High    every bound Power BI report was read and nothing else depends on the model
              (or other dependents exist but their queries were seen in the query logs)
      Medium  some (not all) reports unread, or other items depend on the model
      Low     no reports found, scan off, or lineage unavailable
      Unknown scan failed, or none of the bound reports could be read
    query_logs: None (not checked), ("ok", text), ("partial", reason) or ("failed", message).
    Only "ok" (logs that verifiably cover the window) can raise the level.
    """
    logs_ok = bool(query_logs) and query_logs[0] == "ok"
    if logs_ok:
        blind = (f"Also {query_logs[1]}; Excel pivots and ad-hoc DAX in that window are included, "
                 "but anything used less often than that can still be missed.")
    elif query_logs and query_logs[0] == "partial":
        blind = (f"Query logs were read but can't vouch for the window ({query_logs[1]}), so they didn't raise "
                 "confidence; Excel and ad-hoc DAX use may be missed.")
    else:
        blind = ("Excel/Analyze in Excel, ad-hoc DAX queries and reports you can't access are not visible"
                 + (f" (query-log check failed: {str(query_logs[1])[:120]})." if query_logs else
                    "; set MONITORING_DAYS (needs workspace monitoring) to check them."))
    if not scan_enabled:
        return "Low", f"Report scan was turned off; only the model's own references were checked. {blind}"
    if scan_failed:
        return "Unknown", f"Report scan failed, so report usage is unknown. Treat every row as unverified. {blind}"
    if reports_total and reports_scanned == 0:
        return "Unknown", (f"None of the {reports_total} bound reports could be read (usually missing Contributor "
                           f"access), so a hidden field may still sit in a visual. {blind}")
    deps = (", ".join(f"{n} {t}" for t, n in sorted(other_downstream.items())) if other_downstream else "")
    if not lineage_available:
        level = "Medium" if logs_ok else "Low"
        return level, (f"Lineage was incomplete or unavailable, so reports in other workspaces may be missing "
                       f"({reports_scanned} of {reports_total} found reports read). {blind}")
    if reports_total == 0:
        extra = f" Other dependent items: {deps}." if deps else ""
        return ("Medium" if logs_ok else "Low"), (
            f"No Power BI reports are bound to this model, so visible objects may still be used elsewhere.{extra} {blind}")
    notes, level = [], "High"
    if reports_scanned < reports_total:
        level = "Medium"
        names = ", ".join(list(unscanned_names)[:5])
        notes.append(f"{reports_total - reports_scanned} of {reports_total} reports could not be read"
                     + (f" ({names})" if names else ""))
    if other_downstream:
        if not logs_ok:
            level = "Medium"
        notes.append(f"other items depend on this model and were not parsed ({deps})"
                     + ("; their queries are covered by the query logs" if logs_ok else ""))
    detail = "; ".join(notes) + ". " if notes else "All bound Power BI reports were read. "
    return level, detail + blind


def judge_query_logs(coverage: dict, days: int, reports_total: int, now=None) -> tuple:
    """
    ('ok', text) only if the logs can really vouch for the window; otherwise ('partial', reason).
    The library caps its query fetch at 50,000 rows, so a busier model can't be fully scored.
    """
    now = now or pd.Timestamp.now(tz="UTC")
    q, xl, first = coverage.get("queries", 0), coverage.get("excel", 0), coverage.get("first")
    if days < 14:
        return "partial", f"only {days} days of query logs requested (14+ needed to rely on them)"
    if first is None:
        return "partial", "no workspace monitoring data found for the window"
    covered = (now - first).days
    if covered < 0.9 * days:
        return "partial", f"monitoring data only goes back {covered} days of the {days} requested"
    if q >= 50000:
        return "partial", f"{q:,} queries in the window; the library scores at most 50,000, so usage may be missed"
    if reports_total > 0 and q == 0:
        return "partial", "no queries logged for this model even though reports exist (renamed model, or logs not capturing)"
    return "ok", f"query logs for {days} days checked ({q:,} queries, {xl:,} from Excel)"


def unused_objects(columns: pd.DataFrame, measures: pd.DataFrame, used: set, excluded_tables: set,
                   confidence_level: str, column_sizes: dict | None = None, direct_lake: bool = False,
                   edges: dict | None = None, query_log_days: int = 0) -> pd.DataFrame:
    column_sizes = column_sizes or {}
    edges = edges or {}
    any_col_names = {n[2] for n in used if n[0] == "AnyColumn"}
    used_measure_names = {n[2] for n in used if n[0] == "Measure"}
    rows, nodes = [], {}
    for c in columns.to_dict("records"):
        t, name = c["Table Name"], c["Column Name"]
        node = _col(t, name)
        if t in excluded_tables or node in used or _k(name) in any_col_names:
            continue
        size = int(column_sizes.get((t, name), 0) or 0)
        nodes[node] = len(rows)
        rows.append({"Object Type": "Column", "Table Name": t, "Object Name": name, "Is Hidden": bool(c["Is Hidden"]),
                     "Size Bytes": size,
                     "Size Note": "Not loaded in memory (Direct Lake): size unknown" if direct_lake and size == 0 else ""})
    for m in measures.to_dict("records"):
        if m["Table Name"] in excluded_tables or _k(m["Measure Name"]) in used_measure_names:
            continue
        nodes[_meas(m["Measure Name"])] = len(rows)
        rows.append({"Object Type": "Measure", "Table Name": m["Table Name"], "Object Name": m["Measure Name"],
                     "Is Hidden": bool(m["Is Hidden"]), "Size Bytes": 0, "Size Note": ""})

    # Removal order: an unused object that other unused objects still reference must go after them.
    referrers = {i: [] for i in range(len(rows))}
    for src, targets in edges.items():
        if src in nodes:
            for tgt in targets:
                if tgt in nodes and tgt != src:
                    r = rows[nodes[src]]
                    referrers[nodes[tgt]].append(f"{r['Table Name']}[{r['Object Name']}]" if r["Object Type"] == "Column"
                                                 else f"[{r['Object Name']}]")
    for i, r in enumerate(rows):
        r["Used Only By Unused"] = ", ".join(sorted(referrers[i]))

    df = pd.DataFrame(rows, columns=["Object Type", "Table Name", "Object Name", "Is Hidden", "Size Bytes",
                                     "Size Note", "Used Only By Unused"])
    df["Confidence"] = confidence_level

    # Hiding stops NEW use but doesn't break existing visuals or pivots, so the real test is the query log.
    # Short actions per row; the full procedure is stated once in the summary section.
    logs = "logs clear" if query_log_days >= 14 else "check logs"

    def recommend(row):
        after = f" After: {row['Used Only By Unused']}." if row["Used Only By Unused"] else ""
        if confidence_level in ("Low", "Unknown"):
            return "Don't remove yet (confidence gap)."
        steps = f"{logs} → back up → remove" if row["Is Hidden"] else f"hide → {logs} → back up → remove"
        if confidence_level == "Medium":
            return f"Likely: check unread reports first; then {steps}." + after
        if row["Is Hidden"]:
            return f"Strong candidate: {steps}." + after
        return f"{steps[0].upper()}{steps[1:]}." + after

    df["Recommendation"] = df.apply(recommend, axis=1) if len(df) else pd.Series(dtype=str)
    return df.sort_values(["Size Bytes", "Object Type"], ascending=[False, True]).reset_index(drop=True)


# %% [markdown]
# ### 2e · Documentation and change tracking

# %% [engine]
# ---------- Documentation ----------

def documentation_rows(tables, columns, measures, expressions, skip_tables: set, long_chars: int,
                       short_chars: int = 80, skip_expression_tables: set = frozenset()):
    """Object-level documentation inventory (with fingerprints for change tracking) plus findings."""
    inv, out = [], []

    def add(obj_type, table, name, description, expression, language, hidden, lineage):
        has_desc = bool((description or "").strip())
        has_expr = bool(expression)
        has_cmt = has_comment(expression, language) if has_expr else False
        inv.append({
            "Object Type": obj_type, "Table Name": table, "Object Name": name, "Is Hidden": bool(hidden),
            "Has Description": has_desc, "Has Expression": has_expr, "Has Comment": has_cmt,
            "Expression Length": len(expression or ""), "Expression Hash": expression_hash(expression),
            "Lineage Tag": lineage or "", "Description": description or "",
            "Is Generated": table in skip_tables,   # auto-date and field-parameter tables: inventoried, never flagged
        })
        if table in skip_tables or (obj_type == "Shared M Expression" and name == "DatabaseQuery"):
            return
        if obj_type in ("Calculated Table", "M Partition") and table in skip_expression_tables:
            has_expr_flag = False
        else:
            has_expr_flag = has_expr
        if not has_desc and not hidden and obj_type in ("Measure", "Table", "Column", "Calculated Column"):
            out.append(finding(
                "Documentation", "Descriptions", SEV_WARNING if obj_type == "Measure" else SEV_INFO,
                obj_type, table, name, "Missing description.",
                "Add one sentence in business terms: what it means, plus grain or filter context if relevant.",
            ))
        if has_expr_flag and not has_cmt and len(expression) >= short_chars:
            important = (not hidden and obj_type in ("Measure", "Calculated Column")
                         and len(expression) >= long_chars)
            out.append(finding(
                "Documentation", "Comments", SEV_WARNING if important else SEV_INFO, obj_type, table, name,
                f"{language} expression has no comments ({len(expression)} chars).",
                "Add a header comment: purpose, inputs, and any business rule or edge case.",
            ))

    for t in tables.to_dict("records"):
        add("Table", t["Table Name"], t["Table Name"], t["Description"], None, "DAX", t["Is Hidden"], t.get("Lineage Tag"))
    for c in columns.to_dict("records"):
        expr = c["Expression"] if c["Column Type"] == "Calculated" else None
        add("Calculated Column" if expr else "Column", c["Table Name"], c["Column Name"], c["Description"],
            expr, "DAX", c["Is Hidden"], c.get("Lineage Tag"))
    for m in measures.to_dict("records"):
        add("Measure", m["Table Name"], m["Measure Name"], m["Description"], m["Expression"], "DAX",
            m["Is Hidden"], m.get("Lineage Tag"))
    for e in expressions.to_dict("records"):
        add(e["Object Type"], e["Table Name"], e["Object Name"], e.get("Description", ""), e["Expression"],
            e["Language"], True, e.get("Lineage Tag"))
    return pd.DataFrame(inv), out


WORKLIST_COLUMNS = ["Priority", "Object Type", "Table Name", "Object Name", "Needs", "Expression Length",
                    "Current Description", "Draft Description", "Draft Comment", "Approved", "Lineage Tag"]
_WORKLIST_ORDER = {"Measure": 1, "Calculated Column": 2, "Table": 3, "Calculation Item": 4, "Calculated Table": 4,
                   "M Partition": 5, "Shared M Expression": 5, "Column": 6}


def doc_worklist(findings: pd.DataFrame, inventory: pd.DataFrame, changes: pd.DataFrame | None = None) -> pd.DataFrame:
    """
    One row per object that needs documentation, ready for drafts to be filled in:
    objects whose expression changed but whose description didn't come first, then measures,
    calculated columns, tables, other expressions and columns. The Draft and Approved columns
    are left blank for the agent and the model owner. Lineage Tag identifies the object even if renamed.
    """
    needs, stale = {}, set()
    if findings is not None and len(findings):
        for r in findings[findings["Source"] == "Documentation"].to_dict("records"):
            key = (r["Object Type"], r["Table Name"], r["Object Name"])
            needs.setdefault(key, set()).add("description" if r["Category"] == "Descriptions" else "comment")
    if changes is not None and len(changes):
        for r in changes[changes["Description_May_Be_Stale"].astype(bool)].to_dict("records"):
            key = (r["Object_Type"], r["Table_Name"], r["Object_Name"])
            stale.add(key)
            needs.setdefault(key, set())
    inv = {}
    if inventory is not None and len(inventory):
        inv = {(r["Object Type"], r["Table Name"], r["Object Name"]): r for r in inventory.to_dict("records")}
    rows = []
    for key, what in needs.items():
        item = inv.get(key, {})
        parts = (["review description (expression changed)"] if key in stale else []) + \
                [w for w in ("description", "comment") if w in what]
        rows.append({
            "Priority": 0 if key in stale else _WORKLIST_ORDER.get(key[0], 7),
            "Object Type": key[0], "Table Name": key[1], "Object Name": key[2], "Needs": " + ".join(parts),
            "Expression Length": int(item.get("Expression Length", 0) or 0),
            "Current Description": item.get("Description", "") or "",
            "Draft Description": "", "Draft Comment": "", "Approved": "",
            "Lineage Tag": item.get("Lineage Tag", "") or "",
        })
    df = pd.DataFrame(rows, columns=WORKLIST_COLUMNS)
    return df.sort_values(["Priority", "Expression Length"], ascending=[True, False], kind="stable").reset_index(drop=True)


def compute_changes(previous: pd.DataFrame, current: pd.DataFrame) -> pd.DataFrame:
    """
    Compare two documentation snapshots (delta column names, i.e. underscores) for one model.
    Matches on Lineage_Tag when present (survives renames), otherwise on type + table + name.
    """
    cols = ["Change", "Object_Type", "Table_Name", "Object_Name", "Previous_Name", "Description_May_Be_Stale"]
    if previous is None or previous.empty:
        return pd.DataFrame(columns=cols)

    def keyed(df):
        df = df.copy()
        df["_key"] = df.apply(lambda r: r["Lineage_Tag"] if r.get("Lineage_Tag") else
                              f'{r["Object_Type"]}|{r["Table_Name"]}|{r["Object_Name"]}', axis=1)
        return df.drop_duplicates("_key").set_index("_key")

    previous = previous.copy()
    namekey = lambda df: df["Object_Type"].astype(str) + "|" + df["Table_Name"].astype(str) + "|" + df["Object_Name"].astype(str)
    cur_tags = dict(zip(namekey(current), current["Lineage_Tag"]))
    missing_tag = previous["Lineage_Tag"].fillna("").astype(str) == ""
    previous.loc[missing_tag, "Lineage_Tag"] = namekey(previous[missing_tag]).map(cur_tags).fillna("")
    p, c = keyed(previous), keyed(current)
    rows = []
    for k in c.index.difference(p.index):
        r = c.loc[k]
        rows.append(["Added", r["Object_Type"], r["Table_Name"], r["Object_Name"], "", False])
    for k in p.index.difference(c.index):
        r = p.loc[k]
        rows.append(["Removed", r["Object_Type"], r["Table_Name"], r["Object_Name"], "", False])
    for k in c.index.intersection(p.index):
        a, b = p.loc[k], c.loc[k]
        renamed = (a["Object_Name"] != b["Object_Name"]) or (a["Table_Name"] != b["Table_Name"])
        expr_changed = a["Expression_Hash"] != b["Expression_Hash"]
        desc_changed = a["Description"] != b["Description"]
        stale = bool(expr_changed and not desc_changed and str(b["Description"]).strip())
        if renamed:
            rows.append(["Renamed", b["Object_Type"], b["Table_Name"], b["Object_Name"],
                         f'{a["Table_Name"]}.{a["Object_Name"]}', stale])
        if expr_changed:
            rows.append(["Expression changed", b["Object_Type"], b["Table_Name"], b["Object_Name"], "", stale])
        elif desc_changed:
            rows.append(["Description changed", b["Object_Type"], b["Table_Name"], b["Object_Name"], "", False])
    return pd.DataFrame(rows, columns=cols)




# %% [markdown]
# ### 2f · Ranking, summaries and data dictionary

# %% [engine]
# ---------- Agent-ready summary ----------

_AREA_RANK = {  # lower = more important, applied within the same severity
    ("BPA", "Error Prevention"): 1, ("BPA", "DAX Expressions"): 2, ("BPA", "Performance"): 3,
    ("Star schema", None): 4, ("Usage", None): 5, ("BPA", "Maintenance"): 6, ("BPA", "Formatting"): 7,
    ("BPA", "Naming Conventions"): 8, ("Documentation", None): 9,
}


# BPA rules that fire often but rarely matter as much as structural problems: rank them with Maintenance.
NOISY_BPA_RULES = {
    "Do not use floating point data types", "Set IsAvailableInMdx to false on non-attribute columns",
    "Set IsAvailableInMdx to true on necessary columns", "Minimize Power Query transformations",
    "Large tables should be partitioned", "Avoid using calculated columns", "Reduce usage of calculated tables",
    "Reduce usage of calculated columns that use the RELATED function", "Check if dynamic row level security (RLS) is necessary",
    "Limit row level security (RLS) logic", "Partition name should match table name for single partition tables",
}


def _area_rank(source, category, rule=None):
    if source == "BPA" and rule in NOISY_BPA_RULES:
        return 6.5
    if source == "Star schema":
        return 2.5          # structural problems sit right after DAX correctness
    return _AREA_RANK.get((source, category), _AREA_RANK.get((source, None), 10))


# Short, verified fixes for common BPA rules (the rule descriptions are long and some oversell DIVIDE).
BPA_SHORT_FIX = {
    "Use the DIVIDE function for division": "Replace a / b with DIVIDE(a, b) (no third argument, so blanks stay blank). Compare old vs new first.",
    "Avoid using the IFERROR function": "Find what error it hides. a/b by zero returns infinity, not an error; DIVIDE(a, b) returns blank instead, which changes visuals.",
    "Filter column values with proper syntax": "Replace FILTER('T', 'T'[Col] = x) with KEEPFILTERS('T'[Col] = x) inside CALCULATE.",
    "Filter measure values by columns, not tables": "Iterate VALUES('T'[Key]) at the grain the business rule means, not the whole table; compare results.",
    "Use the TREATAS function instead of INTERSECT for virtual relationships": "Use TREATAS(VALUES(Src[Key]), Target[Key]); INTERSECT keeps its first argument's lineage.",
    "Avoid adding 0 to a measure": "Remove '+ 0' (also flags DIVIDE(a,b,0) / IFERROR(x,0)); show zeros via the visual instead.",
    "Measures should not be direct references of other measures": "Repoint visuals to the original measure, then hide -> check logs -> remove the copy.",
    "No two measures should have the same definition": "Keep one, repoint visuals, then hide -> check logs -> remove the duplicate.",
    "Avoid using '1-(x/y)' syntax": "Rewrite 1 - x/y as DIVIDE(y - x, y) so blanks and zero denominators behave.",
    "Avoid addition or subtraction of constant values to results of divisions": "Fold the constant into the numerator, e.g. DIVIDE(x - y, y) instead of x/y - 1.",
    "The EVALUATEANDLOG function should not be used in production models": "Remove the EVALUATEANDLOG wrapper.",
    "Do not use floating point data types": "Change Double columns to Fixed Decimal (Currency) unless precision beyond 4 decimals is needed.",
    "Avoid using calculated columns": "Move the logic upstream (Power Query or the lakehouse) where possible.",
    "Remove auto-date table": "First repoint visuals that use the built-in date hierarchy to the marked date table, then turn off Auto date/time (turning it off breaks those visuals).",
    "Model should have a date table": "Add a date table and mark it as a date table.",
    "Date/calendar tables should be marked as a date table": "Mark the table as a date table.",
    "Provide format string for measures": "Set a format string on each measure.",
    "Do not summarize numeric columns": "Set Summarize By = None on numeric key/attribute columns.",
    "Hide foreign keys": "Hide fact-table key columns used only for relationships.",
    "Relationship columns should be of the same data type": "Make both relationship columns the same data type (ideally integer).",
}


def _short_fix(rule: str, description: str) -> str:
    if rule in BPA_SHORT_FIX:
        return BPA_SHORT_FIX[rule]
    text = re.sub(r"\s+", " ", str(description or "")).strip()
    m = re.match(r"(.{10,200}?[.!?])(\s|$)", text)
    return m.group(1) if m else (text[:200].rstrip() + ("…" if len(text) > 200 else ""))


def rank_findings(findings: pd.DataFrame) -> pd.DataFrame:
    """Individual findings, most important first (for top_findings.csv)."""
    if findings is None or findings.empty:
        return pd.DataFrame(columns=["Dataset Name"] + FINDING_COLUMNS)
    f = findings.copy()
    f["_sev"] = f["Severity"].map(SEVERITY_ORDER).fillna(3)
    f["_area"] = [_area_rank(s_, c_, r_) for s_, c_, r_ in zip(f["Source"], f["Category"], f["Finding"])]
    return f.sort_values(["Dataset Name", "_sev", "_area"]).drop(columns=["_sev", "_area"]).reset_index(drop=True)


BIG_UNUSED_MB = 100  # unused columns this large rank just after DAX issues: real memory and refresh cost


def group_issues(findings: pd.DataFrame, unused: pd.DataFrame | None = None, confidence_level: str = "") -> pd.DataFrame:
    """
    Collapse findings for ONE model into actionable issue types:
    one row per BPA rule, per star-schema finding type, per documentation gap type, and one row for unused objects.
    """
    cols = ["Severity", "Area", "Issue", "Count", "Examples", "Fix"]
    rows = []
    f = findings if findings is not None and len(findings) else pd.DataFrame(columns=FINDING_COLUMNS)

    def examples(df):
        names = []
        for r in df.to_dict("records"):
            n = r["Object Name"]
            if r["Object Type"] in ("Column", "Calculated Column") and r["Table Name"] and not str(n).startswith("'"):
                n = f"{r['Table Name']}[{n}]"
            if n not in names:
                names.append(str(n))
        return ", ".join(names[:3]) + (f" (+{len(names) - 3} more)" if len(names) > 3 else "")

    worst = lambda sev: min(sev, key=lambda x: SEVERITY_ORDER.get(x, 3))
    bpa = f[f["Source"] == "BPA"]
    for (cat, rule), g in bpa.groupby(["Category", "Finding"], sort=False):
        rows.append({"Severity": worst(g["Severity"]), "Area": f"BPA: {cat}", "Issue": rule, "Count": len(g),
                     "Examples": examples(g), "Fix": _short_fix(rule, g["Suggestion"].iloc[0]),
                     "_rank": _area_rank("BPA", cat, rule)})
    star = f[f["Source"] == "Star schema"]
    for text, g in star.groupby("Finding", sort=False):
        rows.append({"Severity": worst(g["Severity"]), "Area": "Star schema", "Issue": text, "Count": len(g),
                     "Examples": examples(g), "Fix": g["Suggestion"].iloc[0], "_rank": _area_rank("Star schema", None)})
    if unused is not None and len(unused):
        hidden = int(unused["Is Hidden"].sum())
        mb = unused["Size Bytes"].sum() / 1_048_576
        strong = (confidence_level == "High" and hidden > 0) or (confidence_level in ("High", "Medium") and mb >= BIG_UNUSED_MB)
        rows.append({"Severity": SEV_WARNING if strong else SEV_INFO, "Area": "Usage",
                     "Issue": f"Unused objects ({hidden} hidden, {len(unused) - hidden} visible)"
                              + (f", ~{mb:.1f} MB" if mb >= 0.1 else ""),
                     "Count": len(unused),
                     "Examples": ", ".join((unused["Table Name"] + "[" + unused["Object Name"] + "]").head(3)),
                     "Fix": f"Confidence {confidence_level}. See the unused-objects section; never delete straight from the list.",
                     "_rank": 2.6 if mb >= BIG_UNUSED_MB else _area_rank("Usage", None)})
    # Documentation: measures get their own rows (they matter most); everything else is ONE summary row,
    # so table/column/M-partition gaps can never crowd real issues out of the priority list.
    doc = f[f["Source"] == "Documentation"]
    meas_doc, other_doc = doc[doc["Object Type"] == "Measure"], doc[doc["Object Type"] != "Measure"]
    for cat, g in meas_doc.groupby("Category", sort=False):
        long_ones = g[g["Severity"] == SEV_WARNING]
        issue = "Visible measures without descriptions" if cat == "Descriptions" else "Measures without comments"
        if cat == "Comments" and len(long_ones):
            issue += f" ({len(long_ones)} long)"
        rows.append({"Severity": worst(g["Severity"]), "Area": "Documentation", "Issue": issue, "Count": len(g),
                     "Examples": examples(long_ones if len(long_ones) else g), "Fix": g["Suggestion"].iloc[0],
                     "_rank": _area_rank("Documentation", None)})
    if len(other_doc):
        parts = []
        for (cat, otype), g in other_doc.groupby(["Category", "Object Type"], sort=False):
            plural = len(g) != 1
            what = ("without descriptions" if plural else "without a description") if cat == "Descriptions" \
                else ("without comments" if plural else "without a comment")
            parts.append(f"{len(g)} {otype}{'s' if plural else ''} {what}")
        rows.append({"Severity": worst(other_doc["Severity"]), "Area": "Documentation",
                     "Issue": "Other documentation gaps", "Count": len(other_doc), "Examples": "; ".join(parts),
                     "Fix": "Lower priority: describe user-facing tables/columns; add header comments to Power Query steps.",
                     "_rank": _area_rank("Documentation", None) + 0.5})
    if not rows:
        return pd.DataFrame(columns=cols)
    out = pd.DataFrame(rows)
    out["_sev"] = out["Severity"].map(SEVERITY_ORDER).fillna(3)
    out = out.sort_values(["_sev", "_rank", "Count"], ascending=[True, True, False])
    return out[cols].reset_index(drop=True)


def show_markdown(text: str) -> None:
    """Render markdown in the notebook output. Front ends without rich output show the same text as plain text."""
    try:
        from IPython.display import display as _ipython_display
        _ipython_display({"text/markdown": text, "text/plain": text}, raw=True)
    except Exception:
        print(text)


def _md_cell(value) -> str:
    text = (str(value).replace("\r\n", " ").replace("\r", " ").replace("\n", " ")
            .replace("|", "\\|").replace("`", "'")).strip()
    return ("\\" + text) if text[:1] in ("#", "-", "+", "*", ">", "=") else text


def _md_name(value) -> str:
    """For names placed inside `inline code`."""
    return str(value).replace("`", "'")


def _md_table(df, cols, limit, more_hint="CSV"):
    """GitHub/CommonMark table, preceded by a blank line so it always renders."""
    if df is None or len(df) == 0:
        return "\n_None._\n"
    rows = df[cols].head(limit).values.tolist()
    lines = ["", "| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    lines += ["| " + " | ".join(_md_cell(v) for v in r) + " |" for r in rows]
    more = f"\n_…{len(df) - limit} more in the {more_hint}._" if len(df) > limit else ""
    return "\n".join(lines) + more + "\n"


def _fence(code: str, lang: str) -> str:
    """Code fence that can't be broken by backticks inside the code."""
    code = str(code or "").replace("\r\n", "\n").replace("\r", "\n")
    longest = max([len(m) for m in re.findall(r"`+", code)] + [0])
    fence = "`" * max(3, longest + 1)
    return f"{fence}{lang}\n{code}\n{fence}"


def model_summary_markdown(model: str, status: str, score: dict, issues: pd.DataFrame, confidence: dict,
                           unscanned: pd.DataFrame, unused: pd.DataFrame, roles: pd.DataFrame,
                           doc: pd.DataFrame, changes: pd.DataFrame, issue_limit: int = 12,
                           has_previous: bool = False, dictionary_file: str = "", sizes_available: bool = True,
                           short_chars: int = 80, relationships: pd.DataFrame | None = None,
                           worklist_file: str = "", worklist_count: int = 0) -> str:
    """One model's section: everything SKILL.md asks the agent to report, already ranked and capped."""
    md = [f"## {model}", "", f"**Status:** {status}", ""]
    shown = [f"{k}: {v}" for k, v in (score or {}).items() if k not in ("Dataset Name", "Status") and v not in (None, "")]
    if shown:
        md += ["**Scorecard:** " + " · ".join(shown), ""]
    if status.startswith("FAILED"):
        md.append("_Model could not be read, so nothing else was analyzed. See Steps that failed._\n")
        return "\n".join(md)

    md += ["### Priority issues (grouped, most important first)",
           _md_table(issues, ["Severity", "Area", "Issue", "Count", "Examples", "Fix"], issue_limit, "top_issues.csv")]

    if not confidence:
        md += ["### Unused objects — not run", "", "_The dependency step failed, so unused objects were not analyzed._", ""]
    else:
        md += [f"### Unused objects — confidence: {confidence.get('Confidence')}", "", confidence.get("Confidence Detail", "")]
        if unscanned is not None and len(unscanned):
            md += ["", "Reports not read: " + "; ".join(f"{r['Report Name']} ({str(r['Error'])[:80]})"
                                                       for r in unscanned.head(10).to_dict("records"))]
        u = unused.copy() if unused is not None and len(unused) else pd.DataFrame()
        if len(u):
            md += ["", "Removal procedure: hide (stops new use; existing visuals and pivots keep working) → check query "
                       "logs for 2–4 weeks → back up the model → remove. \"After:\" means remove those objects first."]
            u["Size MB"] = [("" if t == "Measure" else "n/a" if (note or not sizes_available) else f"{b / 1_048_576:.1f}")
                            for t, b, note in zip(u["Object Type"], u["Size Bytes"], u["Size Note"])]
            u["Visibility"] = u["Is Hidden"].astype(bool).map({True: "hidden", False: "visible"})
            md.append(_md_table(u, ["Object Type", "Table Name", "Object Name", "Visibility", "Size MB", "Recommendation"],
                                15, "unused_candidates.csv"))
        else:
            md += ["", "_No unused objects found._", ""]

    md.append("### Model shape")
    if relationships is not None and len(relationships):
        rel = relationships
        m2m = int(((rel["From Cardinality"] == "Many") & (rel["To Cardinality"] == "Many")).sum())
        both = int((rel["Cross Filter"] == "BothDirections").sum())
        md += ["", f"Relationships: {len(rel)} ({int((~rel['Is Active'].astype(bool)).sum())} inactive, "
                   f"{both} bi-directional, {m2m} many-to-many). Full list in the dictionary file."]
    if roles is not None and len(roles):
        md.append("")
        for role, g in roles.groupby("Role", sort=True):
            names = list(g["Table Name"])
            md.append(f"- **{role}** ({len(names)}): " + ", ".join(names[:15]) + (" …" if len(names) > 15 else ""))
        md.append("")
    else:
        md += ["", "_Not available._", ""]

    md.append("### Documentation")
    if doc is not None and len(doc):
        if "Is Generated" in doc.columns:          # coverage counts the same objects the findings do
            doc = doc[~doc["Is Generated"].astype(bool)]

        def cov(otype, visible_only=False):
            d = doc[doc["Object Type"] == otype]
            if visible_only:
                d = d[~d["Is Hidden"]]
            return f"{int(d['Has Description'].sum())}/{len(d)}" if len(d) else "0/0"
        meas = doc[doc["Object Type"] == "Measure"]
        md += ["", f"Measures: {cov('Measure')} described, {int(meas['Has Comment'].sum())}/{len(meas)} commented · "
                   f"Visible tables: {cov('Table', True)} described · Visible columns: {cov('Column', True)} described"]
        needs_comment = ~meas["Has Comment"] & (meas["Expression Length"] >= short_chars)
        gaps = meas[(~meas["Is Hidden"]) & (~meas["Has Description"] | needs_comment)].copy()
        gaps = gaps.sort_values("Expression Length", ascending=False)
        if len(gaps):
            gaps["Needs"] = [" + ".join(x for x, need in (("description", not d), ("comment", (not c) and n >= short_chars)) if need)
                             for d, c, n in zip(gaps["Has Description"], gaps["Has Comment"], gaps["Expression Length"])]
            md += ["", "Visible measures needing documentation (longest first):",
                   _md_table(gaps, ["Object Name", "Table Name", "Expression Length", "Needs"], 10, "worklist file")]
        else:
            md.append("")
        if worklist_file and worklist_count:
            md += [f"Worklist for drafting descriptions and comments: `{worklist_file}` ({worklist_count} objects).", ""]
    else:
        md += ["", "_Not available._", ""]

    md.append("### Changes since previous run")
    if not has_previous:
        md += ["", "_First run for this model (or first since an upgrade): change tracking starts with the next run._", ""]
    elif changes is None or len(changes) == 0:
        md += ["", "_No changes since the previous run._", ""]
    else:
        order = {"Expression changed": 1, "Renamed": 2, "Removed": 3, "Description changed": 4, "Added": 5}
        c = changes.copy()
        c["_o"] = c["Change"].map(order).fillna(9) - c["Description_May_Be_Stale"].astype(bool) * 1
        counts = c["Change"].value_counts().to_dict()
        stale = int(c["Description_May_Be_Stale"].astype(bool).sum())
        md += ["", ", ".join(f"{k}: {v}" for k, v in counts.items()) + f" · descriptions possibly stale: {stale}"]
        detail = c[c["Change"] != "Added"].sort_values("_o").rename(columns={
            "Object_Type": "Object Type", "Table_Name": "Table Name", "Object_Name": "Object Name",
            "Previous_Name": "Previous Name", "Description_May_Be_Stale": "Description May Be Stale"})
        if len(detail):
            md.append(_md_table(detail, ["Change", "Object Type", "Table Name", "Object Name", "Previous Name",
                                         "Description May Be Stale"], 10, "mh_changes table"))
        else:
            md.append("")
    if dictionary_file:
        md.append(f"_Full DAX and Power Query for review or documentation: `{dictionary_file}`._\n")
    return "\n".join(md)


def workspace_summary_markdown(meta: dict, scorecard: pd.DataFrame, model_sections: dict, failures: pd.DataFrame,
                               detail_models: int = 3) -> str:
    md = [f"# Model health summary — {meta['workspace']}",
          f"Run `{meta['run_id']}` · {meta['run_ts']:%Y-%m-%d %H:%M} UTC · Model Health {meta.get('notebook_version', '')} · "
          f"semantic-link-labs {meta['labs_version']} · {len(scorecard)} model(s)\n"]
    if scorecard is None or scorecard.empty:
        md.append("**No models were analyzed.** Check the DATASETS parameter and the failed steps below.\n")
    else:
        sort_cols = [c for c in ("Errors", "Key Warnings", "Warnings") if c in scorecard.columns]
        sc = scorecard.assign(**{c: pd.to_numeric(scorecard[c], errors="coerce") for c in sort_cols}) \
            .sort_values(sort_cols, ascending=False, na_position="last")
        sc = sc.assign(**{c: sc[c].map(lambda v: "" if pd.isna(v) else int(v)) for c in sort_cols})
        md += ["## Scorecard", _md_table(sc, list(sc.columns), 200)]
        ok = sc[sc["Status"].astype(str).str.startswith(("OK", "Partial"))]
        detail = list(ok["Dataset Name"]) if len(ok) <= detail_models else list(ok["Dataset Name"].head(2))
        if len(ok) > detail_models:
            md.append(f"_{len(ok)} models scanned; detail below is for the 2 with the most errors and key warnings "
                      f"(formatting and documentation excluded). "
                      f"Each model has its own `summary_<model>.md`._\n")
        for name in detail:
            md.append(model_sections.get(name, ""))
    if failures is not None and len(failures):
        md += ["## Steps that failed", _md_table(failures, ["Dataset Name", "Step", "Error"], 50)]
    return "\n".join(md)


def split_markdown(text: str, max_chars: int = 150_000) -> list:
    """Split a long markdown file at '## ' section boundaries so each part fits an agent's upload limit."""
    if len(text) <= max_chars:
        return [text]
    sections = re.split(r"(?m)^(?=## )", text)
    parts, cur = [], ""
    for sec in sections:
        if cur and len(cur) + len(sec) > max_chars:
            parts.append(cur)
            cur = ""
        cur += sec
    if cur:
        parts.append(cur)
    return parts


def safe_name(name: str) -> str:
    return re.sub(r"[^\w\-]+", "_", str(name)).strip("_")[:80] or "model"


def unique_file_names(models: list) -> dict:
    """{model name: file stem}; models whose safe names collide get a short id suffix."""
    stems = {}
    counts = {}
    for m in models:
        counts[safe_name(m["name"])] = counts.get(safe_name(m["name"]), 0) + 1
    for m in models:
        stem = safe_name(m["name"])
        stems[m["name"]] = f"{stem}_{str(m['id'])[:8]}" if counts[stem] > 1 else stem
    return stems


def dictionary_markdown(model: str, tables: pd.DataFrame, roles: dict, columns: pd.DataFrame,
                        measures: pd.DataFrame, skip_tables: set, expressions: pd.DataFrame | None = None,
                        max_code: int = 4000, header: str = "", relationships: pd.DataFrame | None = None) -> str:
    """Data dictionary with full DAX and Power Query (M), for an agent to review code or draft documentation."""
    def code(text):
        text = str(text or "")
        return text if len(text) <= max_code else text[:max_code] + "\n// …(truncated)"

    expressions = expressions if expressions is not None else pd.DataFrame(
        columns=["Object Type", "Table Name", "Object Name", "Expression", "Language", "Description"])
    md = [f"# Data dictionary — {model}", header,
          "Hidden objects are marked *(hidden)*. Descriptions shown as `—` are missing.", ""]
    if relationships is not None and len(relationships):
        r = relationships.copy()
        r["From"] = r["From Table"] + "[" + r["From Column"] + "]"
        r["To"] = r["To Table"] + "[" + r["To Column"] + "]"
        r["Cardinality"] = r["From Cardinality"].str.lower() + "-to-" + r["To Cardinality"].str.lower()
        r["Active"] = r["Is Active"].map({True: "yes", False: "no"})
        md += ["## Relationships", _md_table(r, ["From", "To", "Cardinality", "Cross Filter", "Active"], 1000)]
    for t in tables.sort_values("Table Name").to_dict("records"):
        name = t["Table Name"]
        if name in skip_tables:
            continue
        md += [f"## {name} — {roles.get(name, '')}{' *(hidden)*' if t['Is Hidden'] else ''}", "",
               _md_cell(t["Description"] or "—"), ""]
        cols = columns[columns["Table Name"] == name]
        data_cols = cols[cols["Column Type"] != "Calculated"]
        if len(data_cols):
            md.append(_md_table(data_cols.assign(Hidden=data_cols["Is Hidden"].map({True: "yes", False: ""}),
                                                 Desc=data_cols["Description"].replace("", "—")),
                                ["Column Name", "Data Type", "Hidden", "Desc"], 500))
        tex = expressions[expressions["Table Name"] == name]
        for e in tex.to_dict("records"):
            if e["Object Type"] == "M Partition":
                md += [f"**Power Query (`{_md_name(e['Object Name'])}`)**", _fence(code(e["Expression"]), "powerquery"), ""]
            elif e["Object Type"] == "Calculated Table":
                md += ["**Calculated table expression**", _fence(code(e["Expression"]), "dax"), ""]
            elif e["Object Type"] == "Calculation Item":
                md += [f"**Calculation item `{_md_name(e['Object Name'])}`**: {_md_cell(e.get('Description') or '—')}",
                       _fence(code(e["Expression"]), "dax"), ""]
        for c in cols[cols["Column Type"] == "Calculated"].to_dict("records"):
            md += [f"**Calculated column `{_md_name(c['Column Name'])}`**{' *(hidden)*' if c['Is Hidden'] else ''}: "
                   f"{_md_cell(c['Description'] or '—')}", _fence(code(c["Expression"]), "dax"), ""]
        for m in measures[measures["Table Name"] == name].sort_values("Measure Name").to_dict("records"):
            extras = ", ".join(x for x in (m.get("Display Folder") and f"folder: {m['Display Folder']}",
                                           m.get("Format String") and f"format: {m['Format String']}") if x)
            md += [f"### [{m['Measure Name']}]{' *(hidden)*' if m['Is Hidden'] else ''}" + (f" ({extras})" if extras else ""),
                   "", _md_cell(m["Description"] or "—"), "", _fence(code(m["Expression"]), "dax"), ""]
    shared = expressions[expressions["Object Type"] == "Shared M Expression"]
    if len(shared):
        md += ["## Shared Power Query expressions and parameters", ""]
        for e in shared.to_dict("records"):
            md += [f"**`{_md_name(e['Object Name'])}`**: {_md_cell(e.get('Description') or '—')}",
                   _fence(code(e["Expression"]), "powerquery"), ""]
    return "\n".join(md)

# %% [markdown]
# ## Step 3 — Engine: Fabric readers
# Function definitions that read from Fabric. Every call opens models and reports read-only. Nothing runs until Step 4.
#
# ### 3a · Readers

# %% [engine]
import os
import time
import base64
import traceback
import sempy.fabric as fabric
import sempy_labs as labs
from sempy_labs.tom import connect_semantic_model
from sempy_labs.report import get_report_definition
from sempy_labs._helper_functions import format_dax_object_name, get_downstream_relations
import sempy_labs._icons as icons

FILES_ROOT = "/lakehouse/default/Files"   # where Fabric mounts the notebook's default lakehouse

TABLE_COLUMNS = ["Table Name", "Is Hidden", "Description", "Lineage Tag", "Data Columns", "Visible Columns", "Measures",
                 "Is Calc Group", "Is Field Parameter", "Is Auto Date", "Is Agg Table", "Is Date Table", "Is Calc Table",
                 "Is What-if", "Storage Mode"]
COLUMN_COLUMNS = ["Table Name", "Column Name", "Column Type", "Data Type", "Is Hidden", "Description", "Lineage Tag",
                  "Expression", "Sort By Column", "Is Key"]
MEASURE_COLUMNS = ["Table Name", "Measure Name", "Expression", "Description", "Is Hidden", "Lineage Tag",
                   "Display Folder", "Format String"]


def list_models(workspace) -> list:
    """
    Every semantic model in the workspace as [{'name', 'id', 'is_default'}].
    is_default marks the models Fabric creates automatically for a lakehouse or warehouse (same name as the item).
    """
    dfD = fabric.list_datasets(workspace=workspace, mode="rest")
    try:
        items = fabric.list_items(workspace=workspace)
        defaults = set(
            items.groupby("Display Name")
            .filter(lambda x: "SemanticModel" in set(x["Type"]) and bool({"Lakehouse", "Warehouse"} & set(x["Type"])))
            ["Display Name"]
        )
    except Exception:
        defaults = set()
    return [{"name": r["Dataset Name"], "id": str(r["Dataset Id"]), "is_default": r["Dataset Name"] in defaults}
            for r in dfD.to_dict("records")]


def read_model_metadata(dataset, workspace) -> dict:
    """One read-only TOM connection; pulls everything Phase 1 needs."""
    with connect_semantic_model(dataset=dataset, workspace=workspace, readonly=True) as tom:
        m = tom.model
        date_tables = {t.Name for t in tom.all_date_tables()} | {t.Name for t in m.Tables if str(t.DataCategory) == "Time"}
        tables, columns, measures, rels, hier_cols, expressions = [], [], [], [], [], []
        key_cols, calc_table_cols, group_by, field_param_refs, agg_base_refs = set(), {}, {}, set(), set()

        for t in m.Tables:
            is_calc_table = tom.is_calculated_table(table_name=t.Name)
            is_field_param = tom.is_field_parameter(table_name=t.Name)
            calc_expr = next((p.Source.Expression or "" for p in t.Partitions if str(p.SourceType) == "Calculated"), "")
            data_cols = [c for c in t.Columns if str(c.Type) != "RowNumber"]
            tables.append({
                "Table Name": t.Name, "Is Hidden": bool(t.IsHidden), "Description": t.Description or "",
                "Lineage Tag": t.LineageTag or "",
                "Data Columns": len(data_cols), "Visible Columns": sum(1 for c in data_cols if not c.IsHidden),
                "Measures": t.Measures.Count,
                "Is Calc Group": t.CalculationGroup is not None,
                "Is Field Parameter": is_field_param,
                "Is Auto Date": tom.is_auto_date_table(table_name=t.Name),
                "Is Agg Table": tom.is_agg_table(table_name=t.Name),
                "Is Date Table": t.Name in date_tables,
                "Is Calc Table": is_calc_table,
                "Is What-if": is_calc_table and "GENERATESERIES" in calc_expr.upper() and not is_field_param,
                "Storage Mode": next((str(p.Mode) for p in t.Partitions), ""),
            })
            if calc_expr:   # NAMEOF in any calculated table (field parameters that fail the library's strict check too)
                field_param_refs |= nameof_references(calc_expr)
            policy = getattr(t, "RefreshPolicy", None)
            policy_src = getattr(policy, "SourceExpression", None) if policy is not None else None
            if policy_src:
                expressions.append({"Object Type": "M Partition", "Table Name": t.Name, "Object Name": "Incremental refresh source",
                                    "Expression": policy_src, "Language": "M", "Description": "", "Lineage Tag": ""})
            for h in t.Hierarchies:
                for lvl in h.Levels:
                    hier_cols.append({"Table Name": t.Name, "Hierarchy Name": h.Name, "Column Name": lvl.Column.Name})
            for p in t.Partitions:
                stype = str(p.SourceType)
                if stype == "M":
                    expressions.append({"Object Type": "M Partition", "Table Name": t.Name, "Object Name": p.Name,
                                        "Expression": p.Source.Expression or "", "Language": "M",
                                        "Description": p.Description or "", "Lineage Tag": ""})
                elif stype == "Calculated":
                    expressions.append({"Object Type": "Calculated Table", "Table Name": t.Name, "Object Name": t.Name,
                                        "Expression": p.Source.Expression or "", "Language": "DAX",
                                        "Description": t.Description or "", "Lineage Tag": ""})
            if t.CalculationGroup is not None:
                for ci in t.CalculationGroup.CalculationItems:
                    expressions.append({"Object Type": "Calculation Item", "Table Name": t.Name, "Object Name": ci.Name,
                                        "Expression": ci.Expression or "", "Language": "DAX",
                                        "Description": ci.Description or "", "Lineage Tag": ""})

        for c in tom.all_columns():
            tname = c.Parent.Name
            ctype = str(c.Type)
            columns.append({
                "Table Name": tname, "Column Name": c.Name, "Column Type": ctype,
                "Data Type": str(c.DataType), "Is Hidden": bool(c.IsHidden or c.Parent.IsHidden),
                "Description": c.Description or "", "Lineage Tag": c.LineageTag or "",
                "Expression": (c.Expression or "") if ctype == "Calculated" else "",
                "Sort By Column": c.SortByColumn.Name if c.SortByColumn is not None else "",
                "Is Key": bool(c.IsKey),
            })
            if c.IsKey:
                key_cols.add((tname, c.Name))
            if ctype == "CalculatedTableColumn":
                calc_table_cols[(tname, c.Name)] = tname
            alt = getattr(c, "AlternateOf", None)
            if alt is not None:   # aggregation mapping: the base column/table must not be flagged unused
                if getattr(alt, "BaseColumn", None) is not None:
                    agg_base_refs.add(_col(alt.BaseColumn.Parent.Name, alt.BaseColumn.Name))
                if getattr(alt, "BaseTable", None) is not None:
                    agg_base_refs.add(_tbl(alt.BaseTable.Name))
            rcd = c.RelatedColumnDetails
            if rcd is not None:
                group_by[(tname, c.Name)] = [g.GroupingColumn.Name for g in rcd.GroupByColumns if g.GroupingColumn is not None]

        for mm in tom.all_measures():
            measures.append({
                "Table Name": mm.Parent.Name, "Measure Name": mm.Name, "Expression": mm.Expression or "",
                "Description": mm.Description or "", "Is Hidden": bool(mm.IsHidden or mm.Parent.IsHidden),
                "Lineage Tag": mm.LineageTag or "",
                "Display Folder": mm.DisplayFolder or "", "Format String": mm.FormatString or "",
            })

        for r in m.Relationships:
            rels.append({
                "Relationship": format_dax_object_name(r.FromTable.Name, r.FromColumn.Name) + " -> "
                                + format_dax_object_name(r.ToTable.Name, r.ToColumn.Name),
                "From Table": r.FromTable.Name, "From Column": r.FromColumn.Name,
                "To Table": r.ToTable.Name, "To Column": r.ToColumn.Name,
                "From Cardinality": str(r.FromCardinality), "To Cardinality": str(r.ToCardinality),
                "Cross Filter": str(r.CrossFilteringBehavior), "Is Active": bool(r.IsActive),
            })

        for e in m.Expressions:
            expressions.append({"Object Type": "Shared M Expression", "Table Name": "", "Object Name": e.Name,
                                "Expression": e.Expression or "", "Language": "M",
                                "Description": e.Description or "", "Lineage Tag": e.LineageTag or ""})
        is_direct_lake = bool(tom.is_direct_lake())

    hier_map = {}
    for h in hier_cols:
        hier_map.setdefault((h["Table Name"], h["Hierarchy Name"]), []).append(h["Column Name"])
    return {
        "tables": pd.DataFrame(tables, columns=TABLE_COLUMNS),
        "columns": pd.DataFrame(columns, columns=COLUMN_COLUMNS),
        "measures": pd.DataFrame(measures, columns=MEASURE_COLUMNS),
        "relationships": pd.DataFrame(rels, columns=["Relationship", "From Table", "From Column", "To Table", "To Column",
                                                     "From Cardinality", "To Cardinality", "Cross Filter", "Is Active"]),
        "hierarchy_map": hier_map,
        "expressions": pd.DataFrame(expressions, columns=["Object Type", "Table Name", "Object Name", "Expression",
                                                          "Language", "Description", "Lineage Tag"]),
        "key_columns": key_cols, "calc_table_columns": calc_table_cols, "group_by": group_by,
        "field_param_refs": field_param_refs, "agg_base_refs": agg_base_refs, "is_direct_lake": is_direct_lake,
    }


def read_dependencies(dataset, workspace) -> pd.DataFrame:
    return fabric.evaluate_dax(
        dataset=dataset, workspace=workspace,
        dax_string="""
        SELECT [TABLE] AS [Table Name], [OBJECT] AS [Object Name], [OBJECT_TYPE] AS [Object Type],
               [REFERENCED_TABLE] AS [Referenced Table], [REFERENCED_OBJECT] AS [Referenced Object],
               [REFERENCED_OBJECT_TYPE] AS [Referenced Object Type]
        FROM $SYSTEM.DISCOVER_CALC_DEPENDENCY
        """,
    )


def find_bound_reports(dataset_id, workspace_id):
    """
    Reports bound directly to the model (any workspace, via lineage), merged with reports found in the model's
    own workspace, plus counts of other DIRECT dependents (paginated reports, composite models, ...).
    The model itself and indirect (transitive) dependents are not counted.
    Returns (reports: list[dict], other_downstream: dict[type, count], lineage_available: bool).
    """
    ds = str(dataset_id).lower()
    reports, other, seen = [], {}, set()
    lineage_ok = True
    try:
        rel = get_downstream_relations(item=dataset_id, workspace=workspace_id) or {}
        direct = {str(x.get("itemId", "")).lower() for x in rel.get("relations", [])
                  if str(x.get("dependentOnItemId", "")).lower() == ds}
        non_self = [it for it in rel.get("items", []) if str(it.get("id", "")).lower() != ds]
        if rel.get("continuationToken") or rel.get("continuationUri"):
            lineage_ok = False   # more pages exist; this notebook doesn't follow them -> don't claim completeness
            print("   lineage response is paged; treating cross-workspace coverage as incomplete")
        elif non_self and not direct:
            lineage_ok = False   # items but no usable relations: unexpected response shape
            print("   lineage response had items but no direct relations; treating coverage as incomplete")
        for it in rel.get("items", []):
            iid = str(it.get("id", "")).lower()
            if iid == ds or iid not in direct or iid in seen:
                continue
            seen.add(iid)
            if it.get("type") == "Report":
                reports.append({"Report Name": it.get("displayName"), "Report Id": str(it.get("id")),
                                "Report Workspace Id": str(it.get("workspaceId") or workspace_id)})
            else:
                other[it.get("type", "Unknown")] = other.get(it.get("type", "Unknown"), 0) + 1
    except Exception as ex:
        lineage_ok = False
        print(f"   lineage lookup unavailable ({type(ex).__name__}); checking this workspace only")
    # Same-workspace list as a safety net (catches anything lineage missed)
    try:
        dfR = fabric.list_reports(workspace=workspace_id)
        dfR = dfR[dfR["Dataset Id"].astype(str).str.lower() == ds]
        for r in dfR.to_dict("records"):
            rid = str(r["Id"]).lower()
            if rid in seen:
                continue
            seen.add(rid)
            if str(r.get("Report Type", "PowerBIReport")) == "PaginatedReport":
                other["PaginatedReport"] = other.get("PaginatedReport", 0) + 1
            else:
                reports.append({"Report Name": r["Name"], "Report Id": str(r["Id"]), "Report Workspace Id": str(workspace_id)})
    except Exception as ex:
        if not lineage_ok:
            raise RuntimeError(f"Could not list reports by lineage or in the workspace: {ex}")
    return reports, other, lineage_ok


def read_report_fields(report_id, workspace_id):
    """
    Download a report definition (read-only) and extract every referenced field.
    Returns (format, nodes, problems). Any unparseable JSON part is a problem: the caller marks the
    report as not fully read (its fields found so far are still counted as used).
    """
    parts = get_report_definition(report=report_id, workspace=workspace_id, return_dataframe=True)
    docs, problems = [], []
    for r in parts.to_dict("records"):
        path, payload = str(r.get("path", "")), r.get("payload")
        if not path.endswith(".json"):
            continue
        try:
            docs.append((path, json.loads(base64.b64decode(payload or "").decode("utf-8-sig"))))
        except Exception as ex:
            problems.append(f"{path}: {type(ex).__name__}")
    if not docs:
        problems.append("no readable JSON in the report definition")
    nodes = set()
    for _, doc in docs:
        extract_report_fields(doc, out=nodes)
    return report_format([p for p, _ in docs]), nodes, problems


def read_previous_docs(table_name, workspace_id, dataset_ids, exclude_run_id=None) -> pd.DataFrame:
    """
    Latest earlier snapshot of mh_documentation for the given models, filtered in Spark so history size
    doesn't matter. Returns an empty frame on the first run (table missing). The current run is excluded,
    so re-running a cell after saving never compares a run with itself.
    """
    from pyspark.sql import functions as F
    name = next((n for n in (table_name, f"dbo.{table_name}") if spark.catalog.tableExists(n)), None)
    if name is None:
        return pd.DataFrame()
    t = spark.read.table(name)
    needed = ["Run_Timestamp", "Workspace_Id", "Dataset_Id", "Dataset_Name", "Object_Type", "Table_Name",
              "Object_Name", "Lineage_Tag", "Expression_Hash", "Description"]
    missing = [c for c in needed if c not in t.columns]
    if missing:
        print(f"   {table_name} is from an older notebook version (missing {missing}); change tracking starts now.")
        return pd.DataFrame()
    t = t.where((F.col("Workspace_Id") == str(workspace_id)) & F.col("Dataset_Id").isin([str(d) for d in dataset_ids]))
    if exclude_run_id and "Run_Id" in t.columns:
        t = t.where(F.col("Run_Id") != str(exclude_run_id))
    latest = t.groupBy("Dataset_Id").agg(F.max("Run_Timestamp").alias("_mx"))
    t = t.join(latest, on="Dataset_Id").where(F.col("Run_Timestamp") == F.col("_mx")).select(*needed)
    return t.toPandas()


def query_log_coverage(dataset_name, workspace_id, days) -> dict:
    """
    How much the workspace-monitoring logs can actually vouch for: rows for this model, Excel rows,
    and how far back monitoring data exists at all (monitoring doesn't backfill).
    """
    from sempy_labs import query_workspace_monitoring
    safe = str(dataset_name).replace("\\", "\\\\").replace('"', '\\"')
    kql = (
        f"SemanticModelLogs | where Timestamp >= ago({days}d)\n"
        f"| summarize FirstAny = min(Timestamp),\n"
        f"  Queries = countif(OperationName == \"QueryEnd\" and ItemName == \"{safe}\"),\n"
        f"  Excel = countif(OperationName == \"QueryEnd\" and ItemName == \"{safe}\" and ApplicationName == \"Excel\")"
    )
    df = query_workspace_monitoring(query=kql, workspace=workspace_id, language="kql")
    if df is None or len(df) == 0:
        return {"queries": 0, "excel": 0, "first": None}
    r = df.iloc[0]
    first = pd.to_datetime(r.get("FirstAny"), utc=True, errors="coerce")
    return {"queries": int(r.get("Queries") or 0), "excel": int(r.get("Excel") or 0),
            "first": None if pd.isna(first) else first}


def read_query_log_usage(dataset_id, workspace_id, days) -> set:
    """
    Objects seen in workspace-monitoring query logs (DAX, plus MDX from Excel), via semantic-link-labs.
    Read-only. Needs workspace monitoring enabled on the workspace.
    """
    from sempy_labs.semantic_model import find_unused_objects
    df = find_unused_objects(dataset=dataset_id, workspace=workspace_id, method="WorkspaceMonitoring",
                             workspace_monitoring_days=days, visualize=False)
    nodes = set()
    if df is None or len(df) == 0:
        return nodes
    for r in df[df["UsageCount"] > 0].to_dict("records"):
        if str(r["Object Type"]) == "Measure":
            nodes.add(_meas(r["Object Name"]))
        elif str(r["Object Type"]) == "Column":
            nodes.add(_col(r["Table Name"], r["Object Name"]))
    return nodes


def read_bpa(dataset, workspace) -> pd.DataFrame:
    df = labs.run_model_bpa(dataset=dataset, workspace=workspace, return_dataframe=True, extended=False, export=False)
    if df is None or len(df) == 0:
        return pd.DataFrame(columns=["Category", "Rule Name", "Severity", "Object Type", "Object Name", "Description"])
    df = df[~df["Rule Name"].isin(BPA_RULES_SUPERSEDED)].copy()
    df["Severity"] = df["Severity"].replace(icons.severity_mapping)
    return df


def read_column_sizes(dataset, workspace) -> pd.DataFrame:
    stats = labs.vertipaq_analyzer(dataset=dataset, workspace=workspace, visualize=False) or {}
    cols = stats.get("Columns", pd.DataFrame())
    if cols is None or cols.empty:
        return pd.DataFrame()
    if "Type" in cols.columns:
        cols = cols[cols["Type"].astype(str) != "RowNumber"]
    cols = cols[~cols["Column Name"].astype(str).str.startswith("RowNumber-")]
    keep = [c for c in ["Table Name", "Column Name", "Type", "Cardinality", "Total Size", "Data Size", "Dictionary Size"] if c in cols.columns]
    return cols[keep].copy()

# %% [markdown]
# ### 3b · Analyze one model

# %% [engine]
def _bpa_table(object_name: str) -> str:
    m = re.match(r"^'((?:[^']|'')+)'\[", str(object_name))
    return m.group(1).replace("''", "'") if m else ""


def analyze_model(model, workspace) -> dict:
    dataset, dataset_id = model["name"], model["id"]
    out = {"findings": [], "log": []}

    def step(name, fn):
        t0 = time.time()
        try:
            result = fn()
            out["log"].append({"Step": name, "Status": "OK", "Seconds": round(time.time() - t0, 1), "Error": ""})
            return result
        except Exception as ex:
            out["log"].append({"Step": name, "Status": "Failed", "Seconds": round(time.time() - t0, 1),
                               "Error": f"{type(ex).__name__}: {str(ex)[:500]}"})
            print(f"   ! {name} failed: {type(ex).__name__}: {str(ex)[:200]}")
            return None

    meta = step("Read model metadata", lambda: read_model_metadata(dataset, workspace))
    if meta is None:
        return out
    tdf = meta["tables"]
    auto_date = set(tdf.loc[tdf["Is Auto Date"], "Table Name"])
    agg_tables = set(tdf.loc[tdf["Is Agg Table"], "Table Name"])
    field_params = set(tdf.loc[tdf["Is Field Parameter"], "Table Name"])
    calc_groups = set(tdf.loc[tdf["Is Calc Group"], "Table Name"])
    what_ifs = set(tdf.loc[tdf["Is What-if"], "Table Name"])

    # Star schema (each analysis step is guarded, so one surprise can't cost the model's other results)
    out["relationships"] = meta["relationships"]
    classified = step("Star schema", lambda: classify_tables(tdf, meta["relationships"]))
    if classified is None:
        classified = pd.DataFrame(columns=["Table Name", "Role"])
    else:
        out["findings"] += step("Star schema findings", lambda: star_schema_findings(classified, meta["relationships"])) or []
    out["star_schema"] = classified
    out["meta"] = {"tables": tdf, "columns": meta["columns"], "measures": meta["measures"],
                   "expressions": meta["expressions"], "relationships": meta["relationships"], "skip_tables": auto_date}

    # Documentation (auto-generated tables are inventoried but not flagged)
    docs = step("Documentation", lambda: documentation_rows(
        tdf, meta["columns"], meta["measures"], meta["expressions"],
        skip_tables=auto_date | field_params, long_chars=LONG_EXPRESSION_CHARS,
        short_chars=SHORT_EXPRESSION_CHARS, skip_expression_tables=what_ifs))
    if docs is not None:
        out["documentation"], doc_findings = docs
        out["findings"] += doc_findings

    # Column sizes
    sizes = {}
    if RUN_VERTIPAQ:
        col_sizes = step("Vertipaq Analyzer", lambda: read_column_sizes(dataset, workspace))
        if col_sizes is not None and not col_sizes.empty and "Total Size" in col_sizes.columns:
            sizes = {(r["Table Name"], r["Column Name"]): r.get("Total Size", 0) or 0 for r in col_sizes.to_dict("records")}
            out["column_sizes"] = col_sizes.sort_values("Total Size", ascending=False).head(TOP_N_COLUMNS)

    # Unused objects
    dmv = step("Read dependencies", lambda: read_dependencies(dataset, workspace))

    def unused_analysis():
        edges, roots, dmv_types = build_dependency_edges(dmv)
        for rel in meta["relationships"].to_dict("records"):
            roots |= {_col(rel["From Table"], rel["From Column"]), _col(rel["To Table"], rel["To Column"])}
        roots |= {_col(t, c) for t, c in meta["key_columns"]}
        roots |= meta["field_param_refs"]
        roots |= meta["agg_base_refs"]
        # Every column of calc-group and field-parameter tables is structural
        for c in meta["columns"].to_dict("records"):
            if c["Table Name"] in calc_groups | field_params:
                roots.add(_col(c["Table Name"], c["Column Name"]))

        scan_failed, reports_total, reports_scanned, other, lineage_ok = False, 0, 0, {}, True
        unscanned = []
        if SCAN_REPORTS:
            bound = step("Find bound reports", lambda: find_bound_reports(dataset_id, workspace))
            if bound is None:
                scan_failed = True
            else:
                reports, other, lineage_ok = bound
                reports_total = len(reports)
                scan_log = []
                for r in reports:
                    entry = {"Report Name": r["Report Name"], "Report Id": r["Report Id"],
                             "Report Workspace Id": r["Report Workspace Id"],
                             "Format": "", "Scanned": False, "Fields Found": 0, "Error": ""}
                    try:
                        fmt, nodes, problems = read_report_fields(r["Report Id"], r["Report Workspace Id"])
                        roots |= nodes  # whatever was read still counts as used
                        entry.update({"Format": fmt, "Fields Found": len(nodes)})
                        if problems:
                            entry["Error"] = "Partly unreadable: " + "; ".join(problems)[:300]
                        else:
                            entry["Scanned"] = True
                            reports_scanned += 1
                    except Exception as ex:
                        entry["Error"] = f"{type(ex).__name__}: {str(ex)[:300]}"
                    if not entry["Scanned"]:
                        unscanned.append(r["Report Name"])
                    scan_log.append(entry)
                out["report_scan"] = pd.DataFrame(scan_log, columns=["Report Name", "Report Id", "Report Workspace Id",
                                                                     "Format", "Scanned", "Fields Found", "Error"])

        query_logs = None
        if MONITORING_DAYS > 0:
            seen = step("Query-log check", lambda: read_query_log_usage(dataset_id, workspace, MONITORING_DAYS))
            if seen is None:
                failed = next(l for l in reversed(out["log"]) if l["Step"] == "Query-log check")
                query_logs = ("failed", failed["Error"])
            else:
                roots |= seen   # whatever the logs saw counts as used, even if coverage turns out partial
                cov = step("Query-log coverage", lambda: query_log_coverage(dataset, workspace, MONITORING_DAYS))
                query_logs = (judge_query_logs(cov, MONITORING_DAYS, reports_total) if cov is not None
                              else ("partial", "coverage could not be measured"))

        sort_by = {(c["Table Name"], c["Column Name"]): c["Sort By Column"]
                   for c in meta["columns"].to_dict("records") if c["Sort By Column"]}
        used = find_used_objects(roots, edges, sort_by, meta["group_by"], meta["calc_table_columns"], meta["hierarchy_map"],
                                 list(zip(meta["columns"]["Table Name"], meta["columns"]["Column Name"])))
        level, detail = usage_confidence(SCAN_REPORTS, scan_failed, reports_total, reports_scanned, other,
                                         lineage_ok, unscanned, query_logs)
        excluded = auto_date | agg_tables | calc_groups | field_params
        unused = unused_objects(meta["columns"], meta["measures"], used, excluded, level, sizes,
                                meta["is_direct_lake"], edges,
                                MONITORING_DAYS if query_logs and query_logs[0] == "ok" else 0)
        out["unused"] = unused
        out["confidence"] = pd.DataFrame([{
            "Confidence": level, "Confidence Detail": detail, "Reports Found": reports_total,
            "Reports Scanned": reports_scanned, "Other Dependent Items": json.dumps(other),
            "Excluded Tables": ", ".join(sorted(excluded)), "DMV Object Types": ", ".join(dmv_types),
            "Query Logs": ("Not checked" if not query_logs else
                           f"Checked {MONITORING_DAYS} days" if query_logs[0] == "ok" else
                           f"Partial: {query_logs[1]}" if query_logs[0] == "partial" else "Failed"),
        }])
        for u in unused.to_dict("records"):
            size_note = f" Uses ~{u['Size Bytes'] / 1_048_576:.1f} MB." if u["Size Bytes"] > 1_048_576 else ""
            strong = level == "High" and u["Is Hidden"]
            out["findings"].append(finding(
                "Usage", "Unused objects", SEV_WARNING if strong else SEV_INFO,
                u["Object Type"], u["Table Name"], u["Object Name"],
                f"Nothing found that uses it (reports, DAX, relationships, sort/group-by, RLS, field parameters).{size_note}",
                f"{u['Recommendation'].rstrip('.')}. Confidence: {level}.",
            ))

    if dmv is not None:
        step("Unused objects", unused_analysis)

    # BPA
    out["bpa_ran"] = False
    if RUN_BPA:
        bpa = step("Best Practice Analyzer", lambda: read_bpa(dataset, workspace))
        if bpa is not None:
            out["bpa_ran"] = True
            home = dict(zip(meta["measures"]["Measure Name"], meta["measures"]["Table Name"])) if len(meta["measures"]) else {}
            for b in bpa.to_dict("records"):
                name, otype = b.get("Object Name", ""), b.get("Object Type", "")
                table = (home.get(name, "") if otype == "Measure" else name if otype in ("Table", "Calculated Table")
                         else _bpa_table(name))
                out["findings"].append(finding(
                    "BPA", b.get("Category", ""), b.get("Severity", ""), otype, table, name,
                    b.get("Rule Name", ""), b.get("Description", ""),
                ))
    return out

# %% [markdown]
# ## Step 4 — Preflight
# Checks the setup before the scan starts, so a missing lakehouse, a mistyped model name or a permission gap shows up in seconds with a plain message.

# %% [engine]
# Pipelines pass parameters as strings: normalise them.
WORKSPACE = (str(WORKSPACE).strip() or None) if WORKSPACE is not None else None
DATASETS = as_list(DATASETS)
SKIP_DATASETS = as_list(SKIP_DATASETS)
RUN_BPA, RUN_VERTIPAQ, SCAN_REPORTS, WRITE_TO_LAKEHOUSE = map(as_bool, (RUN_BPA, RUN_VERTIPAQ, SCAN_REPORTS, WRITE_TO_LAKEHOUSE))
TOP_N_COLUMNS, TOP_FINDINGS_PER_MODEL, TOP_ISSUES_PER_MODEL, LONG_EXPRESSION_CHARS, SHORT_EXPRESSION_CHARS = map(
    int, (TOP_N_COLUMNS, TOP_FINDINGS_PER_MODEL, TOP_ISSUES_PER_MODEL, LONG_EXPRESSION_CHARS, SHORT_EXPRESSION_CHARS))
MONITORING_DAYS = max(0, min(30, int(MONITORING_DAYS or 0)))
TABLE_PREFIX = str(TABLE_PREFIX)


def _preflight(ok: bool, label: str, detail: str = "") -> None:
    print(("  [ok]   " if ok else "  [warn] ") + label + (f": {detail}" if detail else ""))


print("Preflight")

# 1. Lakehouse (needed for files, tables and change tracking)
HAS_LAKEHOUSE = os.path.isdir(FILES_ROOT)
if WRITE_TO_LAKEHOUSE and not HAS_LAKEHOUSE:
    raise RuntimeError(
        "No lakehouse is attached to this notebook, so results can't be saved. "
        "Attach one in the Explorer pane (Add lakehouse) and run again, "
        "or set WRITE_TO_LAKEHOUSE = False in Step 1 to see results in the notebook only."
    )
_preflight(HAS_LAKEHOUSE or not WRITE_TO_LAKEHOUSE,
           "Lakehouse attached" if HAS_LAKEHOUSE else "No lakehouse: results will only show in this notebook")

# 2. Workspace
try:
    WORKSPACE_ID = fabric.resolve_workspace_id(WORKSPACE)
    WORKSPACE_NAME = fabric.resolve_workspace_name(WORKSPACE_ID)
except Exception as ex:
    raise RuntimeError(
        f"The workspace {WORKSPACE!r} could not be opened ({type(ex).__name__}: {str(ex)[:200]}). "
        "Check the WORKSPACE name in Step 1 and that you are a member of it."
    ) from ex
_preflight(True, f"Workspace '{WORKSPACE_NAME}'",
           "" if WORKSPACE else "chosen by default (the attached lakehouse's workspace, else this notebook's); "
                                "set WORKSPACE in Step 1 to scan a different one")

# 3. Models
ALL_MODELS = list_models(WORKSPACE_ID)
models, _missing, _left_out = select_models(ALL_MODELS, DATASETS, SKIP_DATASETS)
_available = ", ".join(sorted(m["name"] for m in ALL_MODELS)[:40]) or "(none)"
if not ALL_MODELS:
    raise ValueError(f"No semantic models were found in workspace '{WORKSPACE_NAME}'. "
                     "Set WORKSPACE in Step 1 to the workspace that holds the models.")
if not models:
    raise ValueError(
        f"Nothing to scan in workspace '{WORKSPACE_NAME}'. "
        + (f"Not found: {_missing}. " if _missing else "")
        + f"Models in this workspace: {_available}. Fix DATASETS / SKIP_DATASETS in Step 1."
    )
if _missing:
    _preflight(False, f"Not found in '{WORKSPACE_NAME}' and skipped", f"{_missing}. Available: {_available}")
if _left_out:
    _preflight(True, "Default lakehouse/warehouse models left out", f"{_left_out}. Name them in DATASETS to include them")
for _name in duplicate_names(models):
    _preflight(False, f"Two models are named '{_name}'", "results are kept per name, so only one will be reported. Rename one, or scan them in separate runs")
_preflight(True, f"{len(models)} model(s) to scan", ", ".join(m["name"] for m in models[:15]) + (" …" if len(models) > 15 else ""))
if len(models) > 10 and not DATASETS:
    _preflight(False, "Large scope", "DATASETS is empty, so every model is scanned. For a first run, name one small model in Step 1")

# 4. Can the first model's metadata be opened? (XMLA + Contributor/Write). A warning only: the scan tries every model.
try:
    with connect_semantic_model(dataset=models[0]["name"], workspace=WORKSPACE_ID, readonly=True) as _tom:
        _table_count = _tom.model.Tables.Count
    _preflight(True, f"Model metadata readable ('{models[0]['name']}', {_table_count} tables)")
except Exception as ex:
    _preflight(False, f"Could not open '{models[0]['name']}'",
               f"{type(ex).__name__}: {str(ex)[:200]}. Usual causes: XMLA endpoints are off for the tenant or capacity, "
               "or you have Build but not Contributor (or Write) on the model. The scan will still try each model")

# 5. Options
if MONITORING_DAYS and MONITORING_DAYS < 14:
    _preflight(False, f"MONITORING_DAYS = {MONITORING_DAYS}", "query logs are read, but fewer than 14 days can't raise confidence")
_preflight(True, "Checks", ", ".join(n for n, on in (("best practices", RUN_BPA), ("column sizes", RUN_VERTIPAQ),
                                                      ("report usage", SCAN_REPORTS), ("query logs", MONITORING_DAYS > 0)) if on))
print("Preflight passed.")

# %% [markdown]
# ## Step 5 — Scan
# Analyzes each model in turn. A step that fails for one model is recorded and the scan carries on. Each run of this cell is a new run with its own Run Id.

# %%
RUN_ID = str(uuid.uuid4())
RUN_TS = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
print(f"Run {RUN_ID} · workspace '{WORKSPACE_NAME}' · {len(models)} model(s)")

results = {}
for i, model in enumerate(models, 1):
    print(f"[{i}/{len(models)}] {model['name']}")
    t0 = time.time()
    try:
        results[model["name"]] = analyze_model(model, WORKSPACE_ID)
    except Exception:
        results[model["name"]] = {"findings": [], "log": [{"Step": "Analyze model", "Status": "Failed", "Seconds": 0.0,
                                                           "Error": traceback.format_exc()[-800:]}]}
    _failed = [l["Step"] for l in results[model["name"]]["log"] if l["Status"] == "Failed"]
    print(f"   {time.time() - t0:.0f}s · {len(results[model['name']]['findings'])} findings"
          + (f" · failed steps: {', '.join(_failed)}" if _failed else ""))
print("Scan finished.")

# %% [markdown]
# ## Step 6 — Engine: combine, compare with the previous run, rank
# Turns the scan results into the scorecard, the grouped issues, the summaries, the data dictionaries and the documentation worklists. Nothing is saved yet.

# %% [engine]
MODEL_IDS = {m["name"]: m["id"] for m in models}


def stack(key):
    frames = []
    for ds, res in results.items():
        if key == "findings":
            df = pd.DataFrame(res.get("findings", []), columns=FINDING_COLUMNS)
        elif key == "log":
            df = pd.DataFrame(res.get("log", []))
        else:
            df = res.get(key)
        if df is None or len(df) == 0:
            continue
        df = df.copy()
        df.insert(0, "Dataset Name", ds)
        df.insert(1, "Dataset Id", MODEL_IDS.get(ds, ""))
        frames.append(df)
    if not frames:
        return pd.DataFrame()
    df = pd.concat(frames, ignore_index=True)
    df.insert(0, "Workspace Id", str(WORKSPACE_ID))
    df.insert(0, "Workspace Name", WORKSPACE_NAME)
    df.insert(0, "Run Timestamp", RUN_TS)
    df.insert(0, "Run Id", RUN_ID)
    return df


def delta_name(c: str) -> str:
    return re.sub(r"[^0-9A-Za-z_]", "_", c).strip("_")


def to_delta_safe(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = [delta_name(c) for c in df.columns]
    for c in df.columns:
        if df[c].dtype == object or pd.api.types.is_string_dtype(df[c].dtype):   # object in pandas 2, str in pandas 3
            df[c] = df[c].map(lambda v: "" if v is None or (isinstance(v, float) and pd.isna(v)) else str(v)).astype(object)
    return df


def by_model(df, ds):
    return df[df["Dataset Name"] == ds] if df is not None and len(df) else pd.DataFrame()


outputs = {
    "findings": stack("findings"),
    "unused_objects": stack("unused"),
    "usage_confidence": stack("confidence"),
    "star_schema_tables": stack("star_schema"),
    "relationships": stack("relationships"),
    "documentation": stack("documentation"),
    "column_sizes": stack("column_sizes"),
    "report_scan": stack("report_scan"),
    "run_log": stack("log"),
}

# Changes since the previous run (filtered in Spark; empty on the first run)
outputs["changes"] = pd.DataFrame()
PREVIOUS_FOUND = set()
if "spark" in globals() and not outputs["documentation"].empty:
    try:
        prev_all = read_previous_docs(f"{TABLE_PREFIX}documentation", WORKSPACE_ID, list(MODEL_IDS.values()),
                                      exclude_run_id=RUN_ID)
        cur_all = to_delta_safe(outputs["documentation"])
        frames = []
        for ds, ds_id in MODEL_IDS.items():
            prev = prev_all[prev_all["Dataset_Id"] == ds_id] if len(prev_all) else prev_all
            cur = cur_all[cur_all["Dataset_Id"] == ds_id]
            if prev is None or prev.empty or cur.empty:
                continue
            PREVIOUS_FOUND.add(ds)
            ch = compute_changes(prev, cur)
            if not ch.empty:
                ch.insert(0, "Dataset Name", ds)
                ch.insert(1, "Dataset Id", ds_id)
                frames.append(ch)
        if frames:
            ch = pd.concat(frames, ignore_index=True)
            for i, (k, v) in enumerate((("Run Id", RUN_ID), ("Run Timestamp", RUN_TS),
                                        ("Workspace Name", WORKSPACE_NAME), ("Workspace Id", str(WORKSPACE_ID)))):
                ch.insert(i, k, v)
            outputs["changes"] = ch
    except Exception as ex:
        print(f"Change tracking skipped: {type(ex).__name__}: {str(ex)[:200]}")

# Status, scorecard and grouped issues per model (each model in its own try, so one odd model can't stop the run)
f, doc, conf, log = (outputs[k] for k in ("findings", "documentation", "usage_confidence", "run_log"))
failures = log[log["Status"] == "Failed"] if not log.empty else pd.DataFrame(columns=["Dataset Name", "Step", "Error"])
FILE_STEMS = unique_file_names(models)
KEY_EXCLUDED = {"Formatting", "Naming Conventions"}
score_rows, issue_frames, sections, dictionaries, worklists = [], [], {}, {}, {}
for ds in results:
    try:
        fm = by_model(failures, ds)
        failed_steps = list(fm["Step"]) if len(fm) else []
        if "Read model metadata" in failed_steps or "Analyze model" in failed_steps:
            first_err = [l for l in str(fm["Error"].iloc[0]).strip().splitlines() if l.strip()]
            status = f"FAILED at {failed_steps[0]}: {(first_err[-1] if first_err else '')[:160]}"
        elif failed_steps:
            status = "Partial: " + ", ".join(failed_steps) + " failed (see Steps that failed)"
        else:
            status = "OK"
        fd, dd, ud, cd = by_model(f, ds), by_model(doc, ds), by_model(outputs["unused_objects"], ds), by_model(conf, ds)
        md_ = dd[dd["Object Type"] == "Measure"] if len(dd) else dd
        failed_model = status.startswith("FAILED")
        level = cd["Confidence"].iloc[0] if len(cd) else "Not run"

        def count(mask_fn):
            return None if failed_model else (int(mask_fn(fd).sum()) if len(fd) else 0)

        bpa_ran = results[ds].get("bpa_ran", False)
        score = {
            "Dataset Name": ds, "Status": status.split(":")[0].split(" (")[0],
            "Errors": count(lambda d: d["Severity"] == SEV_ERROR) if bpa_ran else None,
            "Key Warnings": count(lambda d: (d["Severity"] == SEV_WARNING) & (d["Source"] != "Documentation")
                                  & ~d["Category"].isin(KEY_EXCLUDED)),
            "Warnings": count(lambda d: d["Severity"] == SEV_WARNING),
            "Info": count(lambda d: d["Severity"] == SEV_INFO),
            "Measures": None if failed_model else len(md_),
            "Described": f"{md_['Has Description'].mean() * 100:.0f}%" if len(md_) else "",
            "Commented": f"{md_['Has Comment'].mean() * 100:.0f}%" if len(md_) else "",
            "Unused": None if (failed_model or not len(cd)) else len(ud),
            "Unused Confidence": "" if failed_model else level,
        }
        score_rows.append(score)
        issues = group_issues(fd, ud, level)
        if len(issues):
            issue_frames.append(issues.assign(**{"Dataset Name": ds}))
        rs = by_model(outputs["report_scan"], ds)
        meta_ = results[ds].get("meta")
        stem_ = FILE_STEMS.get(ds, safe_name(ds))
        dict_file = f"dictionary_{stem_}.md" if meta_ else ""
        wl = doc_worklist(fd, dd, by_model(outputs["changes"], ds))
        if len(wl):
            worklists[ds] = wl
        sections[ds] = model_summary_markdown(
            ds, status, score, issues, cd.iloc[0].to_dict() if len(cd) else {},
            rs[~rs["Scanned"].astype(bool)] if len(rs) else rs, ud, by_model(outputs["star_schema_tables"], ds),
            dd, by_model(outputs["changes"], ds), TOP_ISSUES_PER_MODEL,
            has_previous=ds in PREVIOUS_FOUND, dictionary_file=dict_file,
            sizes_available="column_sizes" in results[ds], short_chars=SHORT_EXPRESSION_CHARS,
            relationships=meta_["relationships"] if meta_ else None,
            worklist_file=f"doc_worklist_{stem_}.csv", worklist_count=len(wl))
        if not bpa_ran and not failed_model:
            sections[ds] = sections[ds].replace("**Status:** OK", "**Status:** OK (BPA not run, so Errors is blank)", 1)
        if meta_:
            roles_ = dict(zip(results[ds]["star_schema"]["Table Name"], results[ds]["star_schema"]["Role"]))
            dictionaries[ds] = dictionary_markdown(
                ds, meta_["tables"], roles_, meta_["columns"], meta_["measures"], meta_["skip_tables"],
                meta_["expressions"], header=f"Workspace: {WORKSPACE_NAME} · run {RUN_TS:%Y-%m-%d %H:%M} UTC",
                relationships=meta_["relationships"])
    except Exception as ex:
        print(f"! Summary for {ds} could not be built: {type(ex).__name__}: {ex}")
        score_rows.append({"Dataset Name": ds, "Status": "Summary error"})
        sections[ds] = f"## {ds}\n\n**Status:** Summary error: {type(ex).__name__}: {str(ex)[:200]}\n"

scorecard = pd.DataFrame(score_rows, columns=["Dataset Name", "Status", "Errors", "Key Warnings", "Warnings", "Info",
                                              "Measures", "Described", "Commented", "Unused", "Unused Confidence"])
for _c in ("Errors", "Key Warnings", "Warnings", "Info", "Measures", "Unused"):
    scorecard[_c] = scorecard[_c].map(lambda v: "" if v is None or (isinstance(v, float) and pd.isna(v)) else int(v)).astype(object)
scorecard = scorecard.astype(object).where(scorecard.notna(), "")
top_issues = (pd.concat(issue_frames, ignore_index=True) if issue_frames
              else pd.DataFrame(columns=["Dataset Name", "Severity", "Area", "Issue", "Count", "Examples", "Fix"]))
top_issues = top_issues[["Dataset Name"] + [c for c in top_issues.columns if c != "Dataset Name"]]
top_findings = rank_findings(f).groupby("Dataset Name").head(TOP_FINDINGS_PER_MODEL) if len(f) else rank_findings(f)
if len(top_findings):
    top_findings = top_findings.assign(Fix=[_short_fix(r, d) if src == "BPA" else d for src, r, d in
                                            zip(top_findings["Source"], top_findings["Finding"], top_findings["Suggestion"])])
summary = workspace_summary_markdown(
    {"workspace": WORKSPACE_NAME, "run_id": RUN_ID, "run_ts": RUN_TS, "labs_version": _labs_version,
     "notebook_version": NOTEBOOK_VERSION},
    scorecard, sections, failures)

# %% [markdown]
# ## Step 7 — Results
# The same summary your agent gets: the scorecard for every model, then the ranked issues, unused objects, model shape and documentation gaps for up to three models. With more than three, the two with the most errors and key warnings are shown, and every model has its own `summary_<model>.md` in the lakehouse.

# %%
show_markdown(summary)

# %% [markdown]
# ## Step 8 — Save
# Writes the files to `Files/model_health/latest/` (plus a dated copy under `runs/`), then appends the delta tables. Files go first, so a table problem can't stop them. Running this cell twice for the same run saves nothing twice.

# %% [engine]
UNUSED_COLS = ["Dataset Name", "Object Type", "Table Name", "Object Name", "Is Hidden", "Size Bytes", "Size Note",
               "Used Only By Unused", "Confidence", "Recommendation"]
if "_SAVED" not in globals():
    _SAVED = set()   # (run id, what) pairs already written in this session

if not WRITE_TO_LAKEHOUSE:
    print("WRITE_TO_LAKEHOUSE is False, so nothing was saved. The results are in Step 7.")
else:
    if not os.path.isdir(FILES_ROOT):
        print("No default lakehouse is mounted, so the summary files were skipped.")
    elif (RUN_ID, "files") in _SAVED:
        print(f"Files for run {RUN_ID[:8]} are already saved.")
    else:
        stamp = f"{RUN_TS:%Y%m%d_%H%M}_{RUN_ID[:8]}"
        latest_dir = f"{FILES_ROOT}/model_health/latest"
        os.makedirs(latest_dir, exist_ok=True)
        for old in os.listdir(latest_dir):  # never leave a previous run's files behind
            if old.endswith((".md", ".csv")):
                os.remove(os.path.join(latest_dir, old))
        unused_out = outputs["unused_objects"]
        unused_out = unused_out[UNUSED_COLS] if len(unused_out) else pd.DataFrame(columns=UNUSED_COLS)

        def file_header(model_name):
            return (f"# Model health — {model_name}\nWorkspace: {WORKSPACE_NAME} · run `{RUN_ID}` · "
                    f"{RUN_TS:%Y-%m-%d %H:%M} UTC · Model Health {NOTEBOOK_VERSION} · semantic-link-labs {_labs_version}\n\n")

        text_files = {"summary.md": summary}
        text_files.update({f"summary_{FILE_STEMS.get(ds, safe_name(ds))}.md": file_header(ds) + sec
                           for ds, sec in sections.items()})
        for ds, d in dictionaries.items():
            parts = split_markdown(d)
            stem = FILE_STEMS.get(ds, safe_name(ds))
            for n, part in enumerate(parts, 1):
                suffix = "" if len(parts) == 1 else f"_part{n}"
                note = "" if len(parts) == 1 else f"_Part {n} of {len(parts)} of the data dictionary for {ds}._\n\n"
                text_files[f"dictionary_{stem}{suffix}.md"] = note + part
        csv_files = {"top_issues.csv": top_issues, "top_findings.csv": top_findings, "unused_candidates.csv": unused_out}
        csv_files.update({f"doc_worklist_{FILE_STEMS.get(ds, safe_name(ds))}.csv": wl for ds, wl in worklists.items()})
        for folder in (latest_dir, f"{FILES_ROOT}/model_health/runs/{stamp}"):
            os.makedirs(folder, exist_ok=True)
            for fname, text in text_files.items():
                with open(f"{folder}/{fname}", "w", encoding="utf-8") as fh:
                    fh.write(text)
            for fname, frame in csv_files.items():
                frame.to_csv(f"{folder}/{fname}", index=False)
        _SAVED.add((RUN_ID, "files"))
        print(f"Wrote {len(text_files) + len(csv_files)} files to Files/model_health/latest/ (copy in runs/{stamp}/)")

    table_errors = []
    for name, df in outputs.items():
        table_name = f"{TABLE_PREFIX}{name}"
        if df.empty or (RUN_ID, table_name) in _SAVED:
            continue
        try:
            labs.save_as_delta_table(dataframe=to_delta_safe(df), delta_table_name=table_name,
                                     write_mode="append", merge_schema=True)
            _SAVED.add((RUN_ID, table_name))
            print(f"Appended {len(df):>6} rows -> {table_name}")
        except Exception as ex:
            table_errors.append(table_name)
            print(f"! Could not append to {table_name}: {type(ex).__name__}: {str(ex)[:200]}")
    if table_errors:
        print(f"\n{len(table_errors)} table(s) failed. Run this cell again to retry only those. If the tables were created "
              f"by an older version of this notebook, drop them or set TABLE_PREFIX to a new value (for example 'mh2_') "
              f"and run again. The summary files are unaffected.")

# %% [markdown]
# ## Step 9 — Copy-paste summary
# Only needed if you can't download `summary.md` from the lakehouse: this prints it as plain text to paste into your agent.

# %%
_cut = summary if len(summary) <= 12000 else summary[:max(summary.rfind("\n## ", 0, 12000), 2000)]
print(_cut + ("\n\n…(cut at a section boundary; the full text is in Files/model_health/latest/summary.md)"
              if len(_cut) < len(summary) else ""))

# %% [markdown]
# ## What to do next
#
# - **Give your agent `Files/model_health/latest/summary.md`.** For one model in depth, add `summary_<model>.md` and `dictionary_<model>.md` (full DAX and Power Query).
# - **Unused objects:** read the confidence level first.
#   - Never delete straight from the list. Hiding an object stops *new* use, but existing visuals and Excel pivots keep working, so waiting for complaints proves nothing.
#   - The safe sequence is: hide → check the query logs for 2–4 weeks (`MONITORING_DAYS`, needs workspace monitoring) → back up the model → remove.
#   - At **Low** or **Unknown** confidence, remove nothing.
#   - "After:" in a recommendation means those objects have to go first.
#   - For Direct Lake models, a size of "n/a" means "not loaded in memory", not "small".
# - **Documentation:** `doc_worklist_<model>.csv` lists what needs a description or comment, changed measures first. Have your agent fill the Draft columns from the dictionary file, then review them yourself. Nothing is written to the model.
# - **Back up before any removal:** save the model definition with `labs.get_semantic_model_bim(dataset=..., workspace=...)` to the lakehouse, or keep a .pbix or Git copy.
# - **Trend:** every run appends to the `mh_` tables under a new Run Id, so a Power BI report on them shows whether health is improving. The SQL endpoint can lag a few minutes behind new rows.
