# Interpreting findings and common fixes

**Before replacing any measure:** run the old and new versions side by side in a DAX query (`EVALUATE SUMMARIZECOLUMNS(<a few grouping columns>, "Old", [Old], "New", [New])`) and confirm they match across several filter combinations.

## BPA DAX rules and their rewrites

| Rule | Instead of | Write | Watch out for |
|---|---|---|---|
| Use the DIVIDE function for division | `[Sales] / [Units]` | `DIVIDE([Sales], [Units])` | Leave out the third argument. `DIVIDE(a, b, 0)` returns 0 instead of blank, which stops blank rows from hiding and slows visuals. |
| Avoid using the IFERROR function | `IFERROR([A] / [B], BLANK())` | `DIVIDE([A], [B])` | In DAX, `x/0` returns infinity and `0/0` returns NaN, not an error, so the IFERROR never fired for those cases. DIVIDE returns blank, which **changes what visuals show** (∞ becomes blank), so confirm that's wanted. If IFERROR masks a type conversion or a lookup failure, fix that cause instead. |
| Filter column values with proper syntax | `CALCULATE([Sales], FILTER('Product', 'Product'[Color] = "Red"))` | `CALCULATE([Sales], KEEPFILTERS('Product'[Color] = "Red"))` | KEEPFILTERS keeps the original behaviour of intersecting with existing filters. Without it, an outer filter on Color would be overwritten. |
| Filter measure values by columns, not tables | `CALCULATE([Sales], FILTER('Sales', [Margin] > 0))` | `CALCULATE([Sales], FILTER(VALUES('Sales'[OrderID]), [Margin] > 0))` | **This changes the grain** at which `[Margin]` is tested: per order instead of per row. Pick the grain the business rule means, then compare old vs new. |
| Use TREATAS instead of INTERSECT | `CALCULATE([Sales], INTERSECT(ALL('Sales'[CustKey]), VALUES('Promo'[CustKey])))` | `CALCULATE([Sales], TREATAS(VALUES('Promo'[CustKey]), 'Sales'[CustKey]))` | INTERSECT keeps the lineage of its **first** argument, so the original filters Sales. TREATAS makes the target explicit. |
| Avoid adding 0 to a measure | `[Sales] + 0` | `[Sales]` | The rule also fires on `DIVIDE(a, b, 0)` and `IFERROR(x, 0)`. Same fix: return blank. If zeros really must show, use a deliberate, documented `COALESCE([Sales], 0)` on the specific visual's measure. "Show items with no data" shows the row, but the value stays blank. |
| Measures should not be direct references of other measures | `[Sales Copy] = [Sales]` | Repoint visuals to `[Sales]`, then hide → check query logs → remove the copy | Copies are sometimes kept on purpose for a different format string. Check first. |
| No two measures should have the same definition | Two identical expressions | Keep one, repoint visuals, then hide → check query logs → remove the other | Same as above. |
| EVALUATEANDLOG should not be used in production | A debugging wrapper left in | Remove the wrapper | |

General: use `VAR` for any sub-expression that's repeated. It's clearer and often faster.

## Star schema findings

- **Disconnected table:** usually a slicer list, a what-if table missed by detection, or something left over. If it's intended, hide what users shouldn't pick and add a description. If not, relate it to the model or remove it.
- **Fact not related to the date table:** time intelligence on that fact silently uses the wrong dates, or none. Relate the fact's date key to the date dimension.
- **Snowflaked dimension / bridge:**
  - A chained dimension such as Product → Category: flatten Category's attributes into Product, either in Power Query or upstream in the lakehouse gold layer.
  - A real bridge table for many-to-many: leave it as is and document it.
- **One-to-one relationship:** the two tables are usually one entity, so merge them.
- **Bi-directional / many-to-many (BPA):** keep these only when they're really needed, and document why in the table description.

## Severity triage

- **Error:** fix now. These break results or the model.
- **Warning:** fix in the next cleanup pass.
- **Info:** batch these. Documentation on hidden or short expressions is lowest priority.
