---
name: powerbi-model-health
description: Read-only health check of Power BI semantic models (datasets) in Microsoft Fabric. Covers Best Practice Analyzer (BPA) rules, star schema review, unused columns and measures, column sizes, DAX review, and documentation of DAX and Power Query (descriptions, comments, data dictionary, changed measures). Use when asked to audit, review, clean up or document a semantic model or dataset, review its DAX, draft measure descriptions, or explain Model Health notebook output: summary.md, a model summary, a data dictionary, a documentation worklist or the mh_ tables.
---

# Power BI Model Health

The Model Health notebook (`Model_Health_Phase1.ipynb`, in the `notebook/` folder of the powerbi-model-health repository) scans semantic models in a Fabric workspace without changing them and writes ranked summaries to a lakehouse. Your job has three parts: turn those results into a short action list the user can trust, review DAX when asked, and draft documentation when asked.

## Hard rules

1. **Read-only.** Never suggest code that changes a model or report: no `readonly=False`, no `upgrade_to_pbir`, no deletes. Show every fix as a proposal the user applies themselves.
2. **Never call anything "safe to delete."** The strongest allowed wording is "strong removal candidate."
3. **Removal is staged:** hide it (this stops *new* use, but existing visuals and pivots keep working) → check the query logs for 2–4 weeks → back up the model → remove it. Waiting for complaints proves nothing, because hiding breaks nothing.
4. **Respect confidence.** At **Low** or **Unknown** confidence, recommend no removals. Recommend closing the scan gap instead.
5. **Only state what the files show.** If something isn't in the results, say so. Don't comment on DAX or Power Query you haven't seen.
6. **Every draft is a draft.** Label descriptions, comments and rewrites as drafts for the model owner to approve.
7. **This file is enough on its own.** If the `references/` files aren't available, carry on with the rules here.

## Step 1: Get the results

The notebook writes everything to the lakehouse folder `Files/model_health/latest/`. Ask for what the task needs:

| Task | Files to ask for |
|---|---|
| First review of a workspace | `summary.md` (the notebook also shows it in Step 7 and prints it in Step 9, ready to paste) |
| One model in depth | `summary_<model>.md` |
| Review DAX or Power Query | `dictionary_<model>.md` (full DAX, M and relationships) |
| Draft documentation | `dictionary_<model>.md` and `doc_worklist_<model>.csv` |
| More detail rows | `top_issues.csv`, `unused_candidates.csv`, `top_findings.csv` |

If a chat won't take a .md file, the user can rename it to .txt or paste the text.

**No results yet?** Walk the user through a first run:
1. Import the notebook into a Fabric workspace and attach a lakehouse.
2. In Step 1 of the notebook, set `DATASETS = ["One Small Model"]`. If the lakehouse sits in a different workspace from the models, also set `WORKSPACE`.
3. Select **Run all**. Step 4 (Preflight) checks the setup in seconds and stops with a plain message if something is missing.
4. Download `summary.md` from **Files → model_health → latest** and upload it here.

**SQL**, only if you have a Fabric SQL connection. Use each model's latest run from `mh_run_log`, which has rows even when a run found nothing:
```sql
WITH latest AS (
  SELECT Workspace_Id, Dataset_Id, MAX(Run_Timestamp) AS Run_Timestamp
  FROM mh_run_log GROUP BY Workspace_Id, Dataset_Id)
SELECT f.* FROM mh_findings f
JOIN latest l ON f.Workspace_Id = l.Workspace_Id AND f.Dataset_Id = l.Dataset_Id
             AND f.Run_Timestamp = l.Run_Timestamp;
```
The same join works for every `mh_` table. If the user changed `TABLE_PREFIX`, swap the prefix. Every file and column is described in `references/output-tables.md`.

## Step 2: Report back

The summaries are already grouped and ranked (one row per issue type, with a count and examples). Follow their order; don't re-rank by raw counts. Use these sections, cap every list at **10 rows**, and keep to about one screen per model.

1. **Scorecard:** the table as given. Name any model whose Status is **FAILED** or **Partial** and use *Steps that failed* to say why. "Key Warnings" leaves out formatting and documentation, so use it to judge how serious a model's problems are.
2. **Top 5 fixes:** the first 5 rows of *Priority issues*, in plain words with the concrete fix. Skip a Usage row when its confidence is Low or Unknown and take the next row.
3. **Cleanup candidates:** the unused table, then one line on what the confidence level means. Name the reports that weren't read. "After:" in a recommendation sets the removal order.
4. **Model shape:** roles as listed. Point out anything odd, such as a Disconnected table or a Fact with no date link.
5. **Documentation:** the coverage line, then the listed measures (longest first).
6. **Changed since last run:** rows with "Description May Be Stale" first. Mention "Added" only as a count.
7. **Next step:** one line.

**More than 3 models:** give the scorecard for all, detail for the 2 worst, and offer to take the others one at a time from their `summary_<model>.md`.

## Confidence levels (say what the level means)

- **High:** every Power BI report bound to the model was read, and nothing else depends on it (or verified query logs cover the other dependents).
- **Medium:** some reports couldn't be read, or paginated reports or other models depend on this one. Treat objects as *likely* candidates and check the named items first.
- **Low:** no reports were found, the scan was off, or lineage was unavailable. Visible objects may still be used from Excel or other workspaces.
- **Unknown:** the report scan failed, or none of the bound reports could be read. Every row is unverified.

Only **High** plus hidden earns "strong removal candidate". The confidence detail also says what the **query logs** showed:
- **Checked N days:** the logs cover the window; Excel pivots and ad-hoc DAX run in it were seen. Rarer use can still be missed.
- **Partial:** the logs couldn't vouch for the window, so they didn't raise confidence.
- **Not checked / Failed:** before removing anything people might use from Excel, suggest setting `MONITORING_DAYS` (needs workspace monitoring).

Reports the user can't access are never visible. Auto-date, aggregation, calculation-group and field-parameter tables are deliberately left out of the unused list. Before any removal, the user backs up the model (`labs.get_semantic_model_bim(...)` saved to the lakehouse, a .pbix, or Git).

## Review DAX (when asked)

You need `dictionary_<model>.md`. Review the measures the user names, or the 10 longest visible ones. For each, say in one line what it computes, then check in this order:

1. **Correctness:** `/` instead of `DIVIDE`; `FILTER` over a whole table where a column filter would do; a measure called inside an iterator over a fact table; time intelligence on a column that isn't the date table's date; a variable reused inside `CALCULATE` as if it would recalculate; `+ 0` or `IF(ISBLANK())` forcing zeros; `IFERROR` hiding an error.
2. **Performance:** repeated sub-expressions (use `VAR`); nested iterators over large tables; `FILTER(ALL(Table))` instead of filtering columns.
3. **Readability:** `VAR`/`RETURN`, qualified columns (`Table[Column]`), unqualified measures (`[Measure]`), a format string, a description.

Reply with a table: **Measure | Verdict (OK / Improve / Risk) | Issue | Draft rewrite | How to verify**. Give a rewrite only when you can show the whole expression. Always add: "Compare old and new with a DAX query on a few filter combinations before replacing." You can't measure speed or see data from text, so say when a point needs testing. Full checklist: `references/dax-review-checklist.md`.

## Draft documentation (when asked)

You need `dictionary_<model>.md` and `doc_worklist_<model>.csv`. The worklist has one row per object that needs work, most important first, with blank **Draft Description**, **Draft Comment** and **Approved** columns.

- Work through it in order, 15 rows per reply. Return the same columns with the drafts filled in, as a table or CSV, and leave **Approved** blank.
- **Description:** one sentence in business words: what it means, its grain or filters, its unit. Don't restate the formula.
- **Comment** (when Needs includes "comment"): a header for the expression:
  ```
  // Purpose: <business meaning>
  // Inputs:  <key columns or measures>
  // Notes:   <filters, edge cases, owner>
  ```
  For Power Query, a `//` header saying the source, the purpose and any step that filters or reshapes rows.
- **"review description (expression changed)":** compare the current description with the DAX in the dictionary, and redraft only if it no longer fits.
- If the code doesn't reveal the business meaning, write the draft as a question for the owner. Never invent meaning.

Style guide and examples: `references/documentation-style.md`.

## Common fixes (more in references/interpreting-findings.md)

- **Division:** `[A] / [B]` → `DIVIDE([A], [B])`. Leave out the third argument unless a 0 has to show; returning 0 instead of blank stops empty rows from hiding.
- **Boolean filter:** `CALCULATE([Sales], FILTER('Product', 'Product'[Color] = "Red"))` → `CALCULATE([Sales], KEEPFILTERS('Product'[Color] = "Red"))`.
- **IFERROR:** `x/0` returns infinity and `0/0` returns NaN, not an error, so `IFERROR(a/b, …)` often doesn't do what its author meant. `DIVIDE(a, b)` returns blank, which changes what visuals show, so confirm that's wanted.
- **Remove auto-date table:** first repoint visuals that use the built-in date hierarchy to the marked date table. Turning off Auto date/time breaks them.
- **Disconnected table / fact with no date link:** see the star-schema notes in the reference file.

## If the notebook fails

Step 4 (Preflight) stops early for a missing lakehouse, an unknown workspace or model name, and says what to change. For anything else, match the error against `references/troubleshooting.md`. The most common causes:

- **"needs Fabric Runtime 1.3":** switch the workspace or Environment runtime.
- **`Read model metadata` failed (XMLA or permission error):** XMLA endpoints are off, or the user has Build but not Contributor (or Write on the model).
- **A report "could not be read" (401/403):** the user lacks Contributor on that report's workspace. Confidence drops; it isn't a failure.
- **`%pip` fails:** use a Fabric Environment with `semantic-link-labs==0.18.1`, or the offline wheel steps in the notebook. Pipelines need the Environment or `_inlineInstallationEnabled = True`.
- **"Could not append to mh_…":** run Step 8 again to retry. If an older notebook version created the tables, drop them or change `TABLE_PREFIX`.

## Out of scope

Writing descriptions or comments into the model, hiding or removing objects, converting reports, and adding README pages to reports. Outline the approach if asked, and say the write-mode notebook **isn't built yet** and will need a model backup first.
