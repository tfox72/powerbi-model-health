# Model health summary — Finance WS
Run `1a6c0138-70d4-4ea7-97db-448be827c718` · 2026-11-10 23:58 UTC · Model Health 0.6.0 · semantic-link-labs 0.18.1 · 3 model(s)

## Scorecard

| Dataset Name | Status | Errors | Key Warnings | Warnings | Info | Measures | Described | Commented | Unused | Unused Confidence |
|---|---|---|---|---|---|---|---|---|---|---|
| Sales Model | OK | 0 | 1 | 4 | 19 | 3 | 33% | 0% | 3 | Medium |
| Tiny | OK | 0 | 1 | 1 | 5 | 0 |  |  | 2 | Low |
| Broken | FAILED at Read model metadata |  |  |  |  |  |  |  |  |  |

## Sales Model

**Status:** OK

**Scorecard:** Errors: 0 · Key Warnings: 1 · Warnings: 4 · Info: 19 · Measures: 3 · Described: 33% · Commented: 0% · Unused: 3 · Unused Confidence: Medium

### Priority issues (grouped, most important first)

| Severity | Area | Issue | Count | Examples | Fix |
|---|---|---|---|---|---|
| Warning | Star schema | Table has no relationships and has visible columns. | 1 | Store | If it is a slicer or parameter table, hide what users shouldn't pick and add a description; otherwise relate it to the model or remove it. |
| Warning | BPA: Formatting | Provide format string for measures | 1 | Unused | Set a format string on each measure. |
| Warning | BPA: Formatting | Do not summarize numeric columns | 1 | 'Sales'[Amount] | Set Summarize By = None on numeric key/attribute columns. |
| Warning | Documentation | Visible measures without descriptions | 1 | Param Measure | Add one sentence in business terms: what it means, plus grain or filter context if relevant. |
| Info | Usage | Unused objects (2 hidden, 1 visible) | 3 | Sales[Margin], _Measures[Column1], _Measures[Unused] | Confidence Medium. See the unused-objects section; never delete straight from the list. |
| Info | Documentation | Other documentation gaps | 16 | 5 Tables without descriptions; 10 Columns without descriptions; 1 Calculated Column without a description | Lower priority: describe user-facing tables/columns; add header comments to Power Query steps. |

### Unused objects — confidence: Medium

2 of 5 reports could not be read (Locked Report, Half Broken); other items depend on this model and were not parsed (1 PaginatedReport, 1 SemanticModel). Excel/Analyze in Excel, ad-hoc DAX queries and reports you can't access are not visible; set MONITORING_DAYS (needs workspace monitoring) to check them.

Reports not read: Locked Report (PermissionError: 403 Forbidden); Half Broken (Partly unreadable: definition/pages/p9/visuals/v9/visual.json: JSONDecodeError)

Removal procedure: hide (stops new use; existing visuals and pivots keep working) → check query logs for 2–4 weeks → back up the model → remove. "After:" means remove those objects first.

| Object Type | Table Name | Object Name | Visibility | Size MB | Recommendation |
|---|---|---|---|---|---|
| Column | Sales | Margin | visible | 0.0 | Likely: check unread reports first; then hide → check logs → back up → remove. |
| Column | _Measures | Column1 | hidden | 0.0 | Likely: check unread reports first; then check logs → back up → remove. |
| Measure | _Measures | Unused | hidden |  | Likely: check unread reports first; then check logs → back up → remove. |

### Model shape

Relationships: 2 (0 inactive, 0 bi-directional, 0 many-to-many). Full list in the dictionary file.

- **Auto date table** (1): LocalDateTable_abc
- **Date dimension** (1): Date
- **Dimension** (1): Product
- **Disconnected** (1): Store
- **Fact** (1): Sales
- **Field parameter** (1): Fields
- **Measure table** (1): _Measures

### Documentation

Measures: 1/3 described, 0/3 commented · Visible tables: 0/5 described · Visible columns: 0/10 described

Visible measures needing documentation (longest first):

| Object Name | Table Name | Expression Length | Needs |
|---|---|---|---|
| Param Measure | _Measures | 17 | description |

Worklist for drafting descriptions and comments: `doc_worklist_Sales_Model.csv` (18 objects).

### Changes since previous run

Added: 33, Removed: 1, Expression changed: 1 · descriptions possibly stale: 1

| Change | Object Type | Table Name | Object Name | Previous Name | Description May Be Stale |
|---|---|---|---|---|---|
| Expression changed | Measure | _Measures | Total Sales |  | True |
| Removed | Measure | _Measures | Gone |  | False |

_Full DAX and Power Query for review or documentation: `dictionary_Sales_Model.md`._

## Tiny

**Status:** OK

**Scorecard:** Errors: 0 · Key Warnings: 1 · Warnings: 1 · Info: 5 · Measures: 0 · Unused: 2 · Unused Confidence: Low

### Priority issues (grouped, most important first)

| Severity | Area | Issue | Count | Examples | Fix |
|---|---|---|---|---|---|
| Warning | Star schema | Table has no relationships and has visible columns. | 1 | Data | If it is a slicer or parameter table, hide what users shouldn't pick and add a description; otherwise relate it to the model or remove it. |
| Info | Usage | Unused objects (0 hidden, 2 visible) | 2 | Data[A], Data[B] | Confidence Low. See the unused-objects section; never delete straight from the list. |
| Info | Documentation | Other documentation gaps | 3 | 1 Table without a description; 2 Columns without descriptions | Lower priority: describe user-facing tables/columns; add header comments to Power Query steps. |

### Unused objects — confidence: Low

No Power BI reports are bound to this model, so visible objects may still be used elsewhere. Excel/Analyze in Excel, ad-hoc DAX queries and reports you can't access are not visible; set MONITORING_DAYS (needs workspace monitoring) to check them.

Removal procedure: hide (stops new use; existing visuals and pivots keep working) → check query logs for 2–4 weeks → back up the model → remove. "After:" means remove those objects first.

| Object Type | Table Name | Object Name | Visibility | Size MB | Recommendation |
|---|---|---|---|---|---|
| Column | Data | A | visible | 0.0 | Don't remove yet (confidence gap). |
| Column | Data | B | visible | 0.0 | Don't remove yet (confidence gap). |

### Model shape

- **Disconnected** (1): Data

### Documentation

Measures: 0/0 described, 0/0 commented · Visible tables: 0/1 described · Visible columns: 0/2 described

Worklist for drafting descriptions and comments: `doc_worklist_Tiny.csv` (3 objects).

### Changes since previous run

_First run for this model (or first since an upgrade): change tracking starts with the next run._

_Full DAX and Power Query for review or documentation: `dictionary_Tiny.md`._

## Steps that failed

| Dataset Name | Step | Error |
|---|---|---|
| Broken | Read model metadata | RuntimeError: XMLA endpoint disabled |
