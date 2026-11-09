# Changelog

Each version went through independent code and skill/approach reviews. Scores are "trustworthy on first run, as far as can be verified without a live tenant."

## v5 (current)
- **Query-log coverage check.** The logs raise confidence only when their coverage is verified. That means at least 14 days requested, monitoring data reaching back about that far, under the library's 50,000-query cap, and some queries logged if the model has reports. Otherwise they're marked "Partial" and don't raise confidence (objects they saw still count as used).
- **Ranking:**
  - Star-schema problems rank right after DAX issues.
  - Noisy BPA Performance rules rank with Maintenance.
  - Unused columns of 100 MB or more become Warnings at High/Medium confidence.
- **Robustness:**
  - Every analysis step is guarded.
  - Models with zero tables are handled.
  - DMV rows containing NaN are handled.
  - DAX names containing an escaped `]]` are parsed correctly.
- **Data dictionary:**
  - Adds relationships and incremental-refresh source M.
  - Splits into parts above ~150,000 characters.
  - Model shape now shows relationship counts.
- **Fewer false "unused" flags:** aggregation base columns (`AlternateOf`) and NAMEOF references in any calculated table now count as used.
- **BPA rules:** "Ensure tables have relationships" and "Consider a star-schema…" are dropped because the notebook's star-schema checks cover them. The "Remove auto-date table" fix now says to repoint visuals first.
- **Polish:**
  - Shorter per-row removal actions, with the procedure stated once.
  - Blank Errors when BPA didn't run.
  - Previous names shown for renamed objects.
  - Escaped markdown block characters.
  - The paste fallback cuts at a section boundary.
  - `top_findings.csv` includes the curated fix.
  - Lineage-tag changes between runs no longer show as Added + Removed.
  - Schema-enabled lakehouse table names are handled.

## v4: code 8.5/10 · skill 8/10
- Fixed a crash on models with zero measures. Each model's summary is built independently.
- Lineage fails safe (paged or unexpected responses lower confidence). Runtime 1.3 check.
- Substring-based DMV typing. Unknown types are treated as used. Calculation items are protected.
- New optional `MONITORING_DAYS` query-log check (includes Excel).
- New removal procedure: hide → check logs → back up → remove.
- The dictionary gains Power Query M, calculated tables and calculation items. Curated BPA fixes. "Not run" states. Direct Lake sizes shown as n/a.
- Local real-Spark tests for change tracking and table writes.

## v3: code 6.5/10 · skill 8/10
- Grouped, ranked priority issues. 121 raw findings collapse to about 8 rows.
- Per-model summaries, data dictionary, workspace scorecard with Status, and stale-file cleanup.
- Case-insensitive matching, hierarchy alias fallback, removal-order notes, and honest Unknown/Low/Medium/High confidence.

## v2: code 7/10 · skill 7/10
- Own report parser (PBIR and legacy) instead of the library's, so same-named fields no longer collapse and hierarchies are found.
- Field-parameter, auto-date and aggregation false positives fixed. Agent-ready summary files. Change-tracking groundwork.

## v1: code 5/10 · skill 6/10
- First read-only notebook and skill.

## Only a live run can confirm
- The real shape of the Fabric lineage (downstream relations, beta) response, and which reports it can see.
- How Excel appears in workspace monitoring (`ApplicationName`), and query-log volumes.
- How real PBIR and legacy reports parse, and getDefinition permissions.
- Real BPA volume, and run time on large models.
- Arrow-enabled Spark conversion, and schema-enabled lakehouse naming.
- Whether M365 Copilot accepts `.md` uploads, and whether Copilot Studio loads the skill's reference files.
