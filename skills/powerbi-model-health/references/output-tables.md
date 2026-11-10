# Outputs

## Files (for agents and people)

These are written to `Files/model_health/latest/` and replaced on every run, with a dated copy kept under `Files/model_health/runs/<date>_<runid>/`. Old files in `latest/` are deleted first, so nothing stale is left behind.

| File | Contents |
|---|---|
| `summary.md` | Scorecard for every model (Status, Errors, Key Warnings, which excludes formatting and docs, and so on), plus full sections for up to 3 models, or the 2 with the most errors and key warnings, and the failed steps. The notebook also shows it in Step 7 and prints it in Step 9. |
| `summary_<model>.md` | One model's sections, in this order: grouped Priority issues, unused objects with confidence and unread reports, model shape, documentation gaps (longest measures first), changes (stale first, Added as a count only). |
| `dictionary_<model>.md` | All relationships (direction, cardinality, cross-filter, active). Every table and column with its description. Every measure, calculated column, calculated table and calculation item with its full DAX. Every Power Query partition, incremental-refresh source and shared expression/parameter with its M. Auto-date tables are left out, and code over 4,000 characters is truncated. Files over ~150,000 characters are split into `_part1`, `_part2`… at table boundaries. Only written for models that could be read. |
| `doc_worklist_<model>.csv` | One row per object that needs a description or comment, in priority order: objects whose expression changed while the description didn't, then measures (longest first), calculated columns, tables, other expressions and columns. `Draft Description`, `Draft Comment` and `Approved` are blank for the agent and the owner to fill. `Lineage Tag` identifies the object even after a rename. Only written when something needs documenting. |
| `top_issues.csv` | Grouped issues for every model. One row per issue type, with Count, Examples and Fix. |
| `top_findings.csv` | Up to `TOP_FINDINGS_PER_MODEL` individual findings per model, ranked by severity, then area. |
| `unused_candidates.csv` | Every unused candidate (header-only when there are none). |

**How priority issues are ranked:** severity first (Error, Warning, Info). Within a severity, the order is:
1. BPA Error Prevention
2. DAX Expressions
3. Star schema
4. Unused columns of 100 MB or more (a Warning at High/Medium confidence)
5. Performance
6. Other unused objects
7. Maintenance, plus the noisy Performance rules (floating point, IsAvailableInMdx, partitioning, calculated columns, RLS)
8. Formatting
9. Naming
10. Documentation

Measure documentation gets its own rows; every other documentation gap is folded into one "Other documentation gaps" row.

## Delta tables

Every table starts with `Run_Id`, `Run_Timestamp`, `Workspace_Name`, `Workspace_Id`, `Dataset_Name` and `Dataset_Id`. Runs **append**, so take each model's latest run by joining on `Dataset_Id` and the max `Run_Timestamp` in `mh_run_log`. Joining on IDs survives renames. Each scan (Step 5) is one run; saving the same run twice writes nothing twice.

| Table | One row per | Key columns |
|---|---|---|
| `mh_findings` | issue | `Source` (BPA / Star schema / Usage / Documentation), `Category`, `Severity`, `Object_Type`, `Table_Name`, `Object_Name`, `Finding`, `Suggestion` |
| `mh_unused_objects` | unused column or measure | `Object_Type`, `Table_Name`, `Object_Name`, `Is_Hidden`, `Size_Bytes`, `Size_Note`, `Used_Only_By_Unused` (removal order), `Confidence`, `Recommendation` |
| `mh_usage_confidence` | model | `Confidence`, `Confidence_Detail`, `Query_Logs` (Checked N days / Partial: reason / Not checked / Failed), `Reports_Found`, `Reports_Scanned`, `Other_Dependent_Items`, `Excluded_Tables`, `DMV_Object_Types` |
| `mh_star_schema_tables` | table | `Role`, `Many_side_Relationships`, `One_side_Relationships`, `Many_to_many_Relationships`, `Visible_Columns`, `Measures`, `Is_Date_Table`, `Storage_Mode` |
| `mh_relationships` | relationship | `From_Table`, `From_Column`, `To_Table`, `To_Column`, `From_Cardinality`, `To_Cardinality`, `Cross_Filter`, `Is_Active` |
| `mh_documentation` | table, column, measure or expression | `Object_Type`, `Has_Description`, `Has_Expression`, `Has_Comment`, `Expression_Length`, `Expression_Hash`, `Lineage_Tag`, `Description`, `Is_Generated` (auto-date and field-parameter tables: listed but never flagged or counted in coverage) |
| `mh_changes` | change since the previous run | `Change` (Added / Removed / Renamed / Expression changed / Description changed), `Object_Type`, `Table_Name`, `Object_Name`, `Previous_Name`, `Description_May_Be_Stale` |
| `mh_column_sizes` | largest columns | `Table_Name`, `Column_Name`, `Cardinality`, `Total_Size` |
| `mh_report_scan` | report bound to the model | `Report_Name`, `Report_Id`, `Report_Workspace_Id`, `Format` (PBIR / PBIR-Legacy), `Scanned`, `Fields_Found`, `Error` |
| `mh_run_log` | notebook step per model | `Step`, `Status`, `Seconds`, `Error` |

## How "used" is decided

When in doubt, the scan counts an object as used. An object is used if a path leads to it from any of these:
- a report visual, filter, bookmark, report-level measure or visual calculation (PBIR and legacy reports)
- a relationship
- a key column
- row-level security, a calculation item, a KPI or a detail-rows expression
- a field parameter (NAMEOF)

From those starting points the scan follows:
- DAX dependencies
- Sort By and Group By columns
- calculated-table sources
- every level of any user hierarchy a report touches

Objects that appear in workspace monitoring query logs (when `MONITORING_DAYS` > 0) also count as used. That includes MDX queries from Excel. The logs raise confidence only when their coverage is verified: at least 14 days requested, monitoring data reaching back about that far, fewer than 50,000 queries, and some queries for the model if it has reports. Columns that aggregation tables map to (`AlternateOf`) and fields named by NAMEOF in any calculated table also count as used. Matching is case-insensitive, like DAX. A bare `[Name]` reference keeps every column with that name, and a hierarchy whose table can't be resolved keeps every hierarchy with that name. If any part of a report can't be parsed, the fields that were read still count as used, but the report is marked not fully read and confidence drops.

Lineage counts only the model's **direct** dependents, and never the model itself. Reports found in the model's own workspace are merged in as a safety net. If the lineage response is paged or has an unexpected shape, coverage is treated as incomplete and confidence drops.

Auto-date, aggregation, calculation-group and field-parameter tables are left out of the unused list.

## Table roles

| Role | Meaning |
|---|---|
| Fact | On the "many" side of relationships only. |
| Dimension | On the "one" side only. |
| Snowflaked dimension / bridge | On both sides. Flatten a chained dimension; leave a real bridge table alone. |
| Many-to-many participant | Joined only by many-to-many relationships. |
| Date dimension | Marked as a date table. |
| Measure table | No visible columns, holds measures. This is fine. |
| What-if parameter / Field parameter / Calculation group / Auto date table / Aggregation table | Special tables, labelled as such. Not flagged. |
| Inactive relationships only | Joined only through inactive relationships. Fine if measures use USERELATIONSHIP. |
| Disconnected | No relationships at all. Check whether that's intended. |
