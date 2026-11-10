# DAX review checklist

Use this when the user asks for a DAX review and you have `dictionary_<model>.md`. Review only code you can see. The dictionary's **Relationships** table tells you which relationships exist, which are inactive, and which filter both ways.

## Before you start

- Review the measures the user names. If they name none, take the 10 longest visible measures, then offer to continue.
- For each measure, first write one line saying what it computes. If you can't tell, say so and ask; don't guess.
- Text alone can't show speed or data problems. Say "test this" where a point depends on either.

## 1. Correctness

| Look for | Why it matters | Draft fix |
|---|---|---|
| `a / b` | Division by zero returns infinity or NaN rather than blank. | `DIVIDE(a, b)`. Skip this when the denominator is a constant. |
| `FILTER('Table', 'Table'[Col] = x)` as a `CALCULATE` filter | Filters the whole table instead of one column. It's slower and can change results through related tables. | `KEEPFILTERS('Table'[Col] = x)`. `KEEPFILTERS` keeps the old behaviour of intersecting with existing filters on that column. |
| A measure called inside an iterator over a fact table, e.g. `SUMX(Sales, [Margin])` | Each row triggers context transition. It's slow on large tables, and wrong when the table has duplicate rows, because each duplicate picks up all its twins. | Iterate a dimension or `VALUES('Table'[Key])` at the grain the rule means, or use the column expression directly. |
| `VAR x = [Measure]` then `CALCULATE(x, …)` | A variable holds the value from where it was defined. `CALCULATE` doesn't recalculate it. | Put the measure inside `CALCULATE`: `CALCULATE([Measure], …)`. |
| Time intelligence (`TOTALYTD`, `DATESYTD`, `SAMEPERIODLASTYEAR`, `DATEADD`…) on a fact table's date column | These functions need the date table's date column: one row per day, whole years, no gaps, marked as a date table. | Use `'Date'[Date]`. If the dictionary shows no Date dimension, say so first. |
| `USERELATIONSHIP(a, b)` | Works only if an inactive relationship between those two columns exists. | Check the Relationships table. If it's missing, flag it. |
| `[Measure] + 0`, `IF(ISBLANK([M]), 0, [M])`, `DIVIDE(a, b, 0)` | Forces zeros, so rows that should be hidden appear, and visuals slow down. | Return blank. If zeros must show, use a documented `COALESCE([M], 0)` for that one visual's measure. |
| `IFERROR(…)`, `ISERROR(…)` | Hides the real error and slows the engine. | Find what fails. For division, `DIVIDE`. For conversions or lookups, fix the cause. |
| `VALUES('T'[Col])` used as a single value | Raises an error when more than one value is visible. | `SELECTEDVALUE('T'[Col])`, which returns blank instead (or a default you pass). |
| `ALLSELECTED` inside an iterator | Its result depends on the visual's query, and inside iterators it can return surprising totals. | Compute the `ALLSELECTED` total in a variable outside the iterator. Mark as "test this". |
| `SUMMARIZE('T', 'T'[Col], "Name", <expression>)` | Adding calculated columns in `SUMMARIZE` can return unexpected results. | `ADDCOLUMNS(SUMMARIZE('T', 'T'[Col]), "Name", CALCULATE(<expression>))`. |
| Hard-coded dates, names or thresholds | A business rule hidden in code. | Flag it for a description or comment; suggest a parameter table if it changes often. |
| Bi-directional relationships or `CROSSFILTER(…, Both)` on the path | Can create ambiguous filter paths and unexpected totals. | Flag it and ask why it's needed. |

## 2. Performance

| Look for | Draft fix |
|---|---|
| The same sub-expression written more than once | Compute it once in a `VAR`. |
| `FILTER(ALL('Table'), …)` over a whole table | Filter only the columns needed: `FILTER(ALL('Table'[Col]), …)`. |
| `COUNTROWS(FILTER('T', 'T'[Col] = x))` | `CALCULATE(COUNTROWS('T'), KEEPFILTERS('T'[Col] = x))`. |
| Nested iterators over large tables (`SUMX` inside `SUMX`) | Reduce the outer table to the needed grain with `VALUES` or `SUMMARIZE`, or move the row-level calculation upstream to a column in the lakehouse. |
| `EARLIER` | Replace with a `VAR` captured in the outer row context. |
| Long `IF(…, IF(…, IF(…)))` chains | `SWITCH(TRUE(), …)`. This is mainly readability. |

Performance verdicts are always "test this": the user can time old and new in DAX query view or with Performance analyzer.

## 3. Readability

- `VAR` / `RETURN`, one idea per variable, and a final `RETURN` of a named variable.
- Columns written as `'Table'[Column]`; measures written as `[Measure]` with no table name.
- A format string and a display folder (the dictionary shows both next to the measure name).
- A description, and a header comment on anything longer than a few lines.

## Reply format

A table, at most 10 measures per reply:

| Measure | Verdict | Issue | Draft rewrite | How to verify |
|---|---|---|---|---|
| name | OK / Improve / Risk | one line | full expression, or "—" | the check to run |

- **Risk** means results may be wrong. **Improve** means the result is right but slower or harder to maintain. **OK** needs no rewrite.
- Give a rewrite only when you can show the whole expression. Otherwise describe the change.
- End with: "These are drafts. Compare old and new before replacing:"
  ```dax
  EVALUATE
  SUMMARIZECOLUMNS(
      'Date'[Year], 'Product'[Category],
      "Old", [Measure],
      "New", <draft expression>
  )
  ```
  Tell the user to swap in grouping columns that matter for the measure and to check a few filter combinations, including an empty one.
