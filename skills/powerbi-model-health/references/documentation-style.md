# Documentation style guide

Use this when drafting descriptions and comments from `dictionary_<model>.md` and `doc_worklist_<model>.csv`. Nothing is written to the model in this phase: you return drafts, and the model owner approves them.

## The worklist

`doc_worklist_<model>.csv` has one row per object that needs work, already in priority order:

1. Objects whose expression changed while the description stayed the same ("review description (expression changed)")
2. Measures, longest first
3. Calculated columns
4. Tables
5. Calculation items and calculated tables
6. Power Query partitions and shared expressions
7. Columns

| Column | Meaning | Who fills it |
|---|---|---|
| `Priority`, `Object Type`, `Table Name`, `Object Name` | What to document | the notebook |
| `Needs` | `description`, `comment`, or both | the notebook |
| `Expression Length` | Size of the DAX or M, in characters | the notebook |
| `Current Description` | What the model says today | the notebook |
| `Draft Description`, `Draft Comment` | Your drafts | you |
| `Approved` | Left blank for the owner (yes / edited / no) | the owner |
| `Lineage Tag` | The object's stable ID. Keep it unchanged so drafts can be matched back, even after a rename. | the notebook |

Return the same columns in the same order, 15 rows per reply, as a table or CSV text. Don't drop or reorder rows. Leave `Draft Comment` empty when `Needs` doesn't include "comment".

## Descriptions

A description is what a report author sees when they hover over a field. Write for someone who knows the business but not the model.

- One sentence, two at most. Plain business words.
- Say **what it means**, its **grain or filters**, and its **unit**.
- Don't restate the formula or name DAX functions.
- Don't start with "This measure…".

| Object | Weak | Better |
|---|---|---|
| Measure | "Sum of Sales Amount." | "Total invoiced sales in USD, before returns and discounts." |
| Measure | "Calculates YTD using TOTALYTD." | "Invoiced sales from the start of the fiscal year to the last date in the current filter." |
| Calculated column | "Margin calc." | "Gross margin for the order line in USD: sales amount minus standard cost." |
| Table | "Sales table." | "One row per invoice line. Loaded nightly from the billing system; excludes voided invoices." |
| Column | "Customer key." | "Key that joins to Customer. Not meant for reports." |
| Column | "Status." | "Order status: Open, Shipped, Cancelled or Returned." |

For a table, lead with the grain ("One row per…"). For a key column, say what it joins to.

## DAX comments

Put a header above any expression longer than a few lines:

```dax
// Purpose: Share of orders delivered on or before the promised date.
// Inputs:  Orders[DeliveredDate], Orders[PromisedDate], [Order Count]
// Notes:   Excludes cancelled orders. Blank when no orders are in the filter.
```

- Comment the **why**: the business rule, the edge case, the reason for an unusual pattern.
- Don't narrate the code ("divide A by B").
- Add an inline `//` only where a line would surprise the next person, such as a hard-coded date or an `ALL` that removes a filter on purpose.

## Power Query (M) comments

Put a header at the top of the query, above `let`:

```powerquery
// Source:  Lakehouse table gold.fact_orders
// Purpose: Order lines for the Sales model.
// Steps:   Removes cancelled orders; keeps the last 5 fiscal years.
let
    Source = …
```

- Mention every step that **filters rows, removes columns or changes grain**. Those are the ones that explain "why doesn't my number match the source?"
- Note a step that is likely to stop query folding (for example a custom column with complex logic) as a point for the owner to check. You can't confirm folding from the text.
- Suggest meaningful step names in place of defaults like `#"Filtered Rows1"`, as a proposal only.

## When the meaning isn't in the code

Never invent business meaning. If the expression doesn't show what something is for, write the draft as a question:

- Draft Description: "Confirm with the owner: does this exclude intercompany sales?"

For "review description (expression changed)" rows, read the current description against the DAX in the dictionary. If it still fits, write "No change needed" in `Draft Description`. If it doesn't, redraft it.

## Every draft is a draft

Say so once at the top of your reply, and leave `Approved` blank. The owner decides what goes into the model.
