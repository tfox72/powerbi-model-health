---
name: powerbi-model-health
description: Read-only health check of Power BI semantic models (datasets) in Microsoft Fabric. Covers Best Practice Analyzer (BPA) DAX rules, star schema review, unused columns and measures, Vertipaq column sizes, documentation coverage, data dictionary and changed measures. Use when asked to audit, review, clean up or document a semantic model or dataset, review its DAX, or explain a model health summary.md, summary_<model>.md, dictionary_<model>.md or the mh_ tables.
---

# Power BI Model Health (Phase 1: read-only)

This skill goes with the Fabric notebook `assets/Model_Health_Phase1.ipynb`. The notebook does the scanning. You help the user run it, then turn its results into a short, trustworthy action list.

## Hard rules

1. **Read-only.** Never suggest code that changes a model or report in this phase: no `readonly=False`, no `upgrade_to_pbir`, no deletes. When the user wants a fix, show it as a proposal they apply themselves.
2. **Never call anything "safe to delete."** The strongest allowed wording is "strong removal candidate."
3. **Removal is staged:** hide it (this stops *new* use, but existing visuals and pivots keep working) → check the query logs for 2–4 weeks → back up the model → remove it. Waiting for complaints proves nothing, because hiding doesn't break anything. This applies to duplicate measures too, and to the "Remove only after" order.
4. **Respect confidence.** At **Low** or **Unknown** confidence, recommend no removals. Recommend fixing the scan gap instead.
5. **Only state what the data shows.** If something isn't in the results, say so. Don't guess at DAX or Power Query you haven't seen.
6. **If `references/` isn't available** (some Copilot Studio setups don't load skill resources), this file is enough on its own. The essential rules, DAX fixes and the three most common setup failures are all here.

## Step 1: Get the results

**First run (the user hasn't run the notebook yet):**
1. In Fabric, import `Model_Health_Phase1.ipynb`.
2. Attach a lakehouse. Set `DATASETS = ["One Small Model"]`. If the lakehouse is in a different workspace from the models, also set `WORKSPACE = "Model Workspace"`.
3. Run all cells.
4. Open the lakehouse **Files → model_health → latest**, download `summary.md`, and upload it here.

If the chat won't take a .md file, rename it to .txt, or paste the summary the notebook prints at the end.

All files are in the lakehouse folder `Files/model_health/latest/`. Ask for whichever of these the user can give, best first:

1. **`summary.md`:** scorecard for every model, plus full sections for up to 3 models (or the 2 worst). This covers a first review. The notebook also prints it at the end, ready to paste.
2. **`summary_<model>.md`:** the same sections for one specific model.
3. **`dictionary_<model>.md`:** every table, column and measure with **full DAX**, plus Power Query (M), calculated tables and calculation items. You need it to review code or draft descriptions and comments. Without it, don't comment on specific DAX or M.
4. **`top_issues.csv`, `unused_candidates.csv`, `top_findings.csv`:** detail rows, if more are needed.
5. **SQL**, only if this agent has a SQL or Fabric data connection. Use each model's latest run, taken from `mh_run_log`, which always has a row even when a run found nothing:
   ```sql
   WITH latest AS (
     SELECT Workspace_Id, Dataset_Id, MAX(Run_Timestamp) AS Run_Timestamp
     FROM mh_run_log GROUP BY Workspace_Id, Dataset_Id)
   SELECT f.* FROM mh_findings f
   JOIN latest l ON f.Workspace_Id = l.Workspace_Id AND f.Dataset_Id = l.Dataset_Id
                AND f.Run_Timestamp = l.Run_Timestamp;
   ```
   The same join works for every `mh_` table. If the user changed `TABLE_PREFIX` (e.g. to `mh3_`), swap the prefix in these table names.

If they have no results yet, go to **Running the notebook** below.

## Step 2: Report back

The summary files are already ranked and grouped (one row per issue type, with a count and examples). Follow their order, and don't re-rank by raw counts. Use these sections, cap every list at **10 rows**, and keep the reply to about one screen per model.

1. **Scorecard:** the table as given. Name any model whose Status is **FAILED** or **Partial**, and use *Steps that failed* to say which step failed and why. "Key Warnings" leaves out formatting and documentation, so use it to judge how serious a model's problems are.
2. **Top 5 fixes:** the first 5 rows of *Priority issues*, explained in plain words with the concrete fix. Skip a Usage row if its confidence is Low or Unknown, and use the next row instead.
3. **Cleanup candidates:** the unused table, followed by one line on what the confidence level means (see below). Name the reports that weren't read. Respect "Remove only after" notes, because they set the removal order.
4. **Model shape:** roles as listed. Point out anything odd, such as a Disconnected table or a Fact with no date link.
5. **Documentation:** the coverage line, then the listed measures (longest first).
6. **Changed since last run:** rows with `Description_May_Be_Stale = True` first. Mention "Added" only as a count.
7. **Next step:** one line.

**More than 3 models:** give the scorecard for all of them, then detail only for the 2 worst, and offer to go through others one at a time using their `summary_<model>.md`.

## Confidence levels (repeat the meaning to the user)

- **High:** every Power BI report bound to the model was read, and either nothing else depends on it or verified query logs cover those other dependents.
- **Medium:** some reports couldn't be read (usually missing permissions), or paginated reports or other models depend on this one. Treat objects as *likely* candidates only, and check the named items first.
- **Low:** no reports were found, the scan was turned off, or lineage was unavailable, and no verified query logs exist. Visible objects may still be used from Excel or other workspaces. Verified logs lift Low to Medium.
- **Unknown:** the report scan failed, or none of the bound reports could be read. Every row is unverified.

Only **High** plus hidden earns the wording "strong removal candidate". The confidence detail says what the **query logs** showed:
- **Checked N days:** the logs verifiably cover the window, and their query and Excel counts are shown. Excel pivots and ad-hoc DAX run in that window were seen. Anything used less often than the window can still be missed.
- **Partial:** logs were read but can't vouch for the window (monitoring too new, nothing logged, or more than 50,000 queries). Objects they saw still count as used, but confidence wasn't raised.
- **Not checked / Failed:** suggest `MONITORING_DAYS` (needs workspace monitoring, 30-day default retention) before removing anything someone might use from Excel.

Before any removal, the user should back up the model. Saving the model definition with `labs.get_semantic_model_bim(...)` to the lakehouse, or keeping a .pbix or Git copy, both work.

At every level, Excel/Analyze in Excel, ad-hoc DAX queries and reports the user can't access are invisible. A hidden object that nothing uses is a far stronger candidate than a visible one. Auto-date, aggregation, calculation-group and field-parameter tables are deliberately left out of the unused list.

## Common DAX fixes (more in references/interpreting-findings.md)

- **Division:** `[A] / [B]` → `DIVIDE([A], [B])`. Leave out the third argument unless a 0 really has to show, because returning 0 instead of blank stops blank rows from hiding.
- **Boolean filter:** `CALCULATE([Sales], FILTER('Product', 'Product'[Color] = "Red"))` → `CALCULATE([Sales], KEEPFILTERS('Product'[Color] = "Red"))`.
- **IFERROR:** in DAX, `x/0` returns infinity and `0/0` returns NaN rather than an error, so `IFERROR(a/b, …)` often doesn't do what its author thought. `DIVIDE(a, b)` returns blank instead, which changes what visuals show, so confirm that's what's wanted. If IFERROR masks some other error, fix the cause.
- **Remove auto-date table:** first repoint visuals that use the built-in date hierarchy to the marked date table. Turning off Auto date/time breaks those visuals.

Always say: "Compare old vs new with a DAX query on a few filter combinations before replacing."

## Drafting documentation

- **Descriptions:** one sentence in business language saying what the number means and its grain. Don't restate the formula. Label every draft as a **draft** for a human to approve.
- **Header comment template:**
  ```
  // Purpose: <business meaning>
  // Inputs:  <key columns/measures>
  // Notes:   <filters, edge cases, owner>
  ```

## Running the notebook (only if asked or if there are no results yet)

Check these in order and stop at the first problem:

1. **Lakehouse:** one is attached to the notebook.
2. **Library:**
   - Best option: a Fabric Environment with `semantic-link-labs==0.18.1`. Then comment out the `%pip` cell.
   - Otherwise leave the `%pip` cell in place.
   - If PyPI is blocked, use the offline wheel instructions in the notebook.
   - Pipelines need either the Environment or `_inlineInstallationEnabled = True`.
3. **Parameters:** `WORKSPACE`, plus `DATASETS = ["One Small Model"]` for the first run.
4. **Permissions:**
   - XMLA endpoints enabled for the tenant and capacity.
   - **Contributor** on the model's workspace, or **Write** on each model. Build alone can query a model but can't read its full metadata.
   - **Contributor** on the report workspaces.
5. **Runtime:** Fabric Runtime 1.3 (Spark 3.5). The first code cell checks it.
6. **Upgrading from an earlier version:** drop the old `mh_` tables, or set `TABLE_PREFIX = "mh3_"`.

If a step fails, match the error in `mh_run_log` against `references/troubleshooting.md`. If that file isn't available, the three most common failures are:
- **"needs Fabric Runtime 1.3":** switch the workspace or Environment runtime.
- **`Read model metadata` XMLA/permission error:** you need Contributor, or Write on the model.
- **`Could not append to mh_…`:** an older notebook version created the tables. Drop them or change `TABLE_PREFIX`.

## Out of scope for Phase 1

Writing descriptions or comments into the model, converting reports, hiding or removing objects, and README pages. Outline the approach if asked, and say the write-mode notebook (Phase 2/3) **isn't built yet** and will need a model backup.
