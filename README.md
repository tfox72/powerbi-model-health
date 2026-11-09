# Power BI Model Health (Phase 1: read-only)

A Microsoft Fabric notebook plus an Agent Skill (`SKILL.md`) for auditing Power BI semantic models that live in Fabric workspaces. The notebook does the scanning and writes short, ranked, agent-ready summaries. The skill tells a Copilot (or Claude) agent how to run it and how to report the results.

**Nothing in any model or report is changed.** Models are opened read-only, BPA runs with `extended=False`, and report definitions are parsed in memory.

## What it checks

| Area | How |
|---|---|
| DAX and model best practices | Best Practice Analyzer (Semantic Link Labs). Rules this notebook covers better are dropped, and the rest come with short verified fixes. |
| Star schema | Each table gets a role (fact, dimension, snowflaked/bridge, many-to-many, measure table, parameters…), and the notebook flags disconnected tables, facts not joined to the date table, one-to-one relationships and inactive-only tables. |
| Unused columns and measures | DAX dependency graph, relationships, keys, sort-by/group-by, RLS, calculation items, field parameters, aggregation mappings, plus its own parser for every bound report (PBIR and legacy). Optional workspace-monitoring query logs (which include Excel) can be added. Each model gets an honest **confidence** level, and removal advice depends on it. |
| Documentation | Description and comment coverage, a full data dictionary (DAX + Power Query M + relationships), and change tracking between runs (flags measures whose DAX changed but whose description didn't). |
| Size | Vertipaq column sizes, matched against the unused list. |

## Quick start

1. **Fabric Runtime 1.3** (Spark 3.5) is required. The first cell checks for it.
2. Import `notebook/Model_Health_Phase1.ipynb` into a Fabric workspace and attach a lakehouse.
3. Set `DATASETS = ["One Small Model"]` (and `WORKSPACE` if the lakehouse lives elsewhere), then **Run all**.
4. Open the lakehouse **Files → model_health → latest** and give `summary.md` to your agent. If uploads are blocked, paste the copy the notebook prints at the end.

**Install options** (Step 0 in the notebook):
- A Fabric Environment with `semantic-link-labs==0.18.1`. This is the best option, and the only one that works in pipelines and High Concurrency sessions.
- `%pip`, the default.
- Offline wheels, when PyPI is blocked.

**Permissions:**
- XMLA endpoints enabled for the tenant and capacity.
- **Contributor** on the model's workspace, or **Write** on the model. Build alone isn't enough.
- **Contributor** on the report workspaces, to read report definitions.

## Outputs

`Files/model_health/latest/`:
- `summary.md`
- `summary_<model>.md`
- `dictionary_<model>.md`
- `top_issues.csv`
- `top_findings.csv`
- `unused_candidates.csv`

Delta tables (appended per run, keyed by `Run_Id`, `Workspace_Id`, `Dataset_Id`):
- `mh_findings`
- `mh_unused_objects`
- `mh_usage_confidence`
- `mh_star_schema_tables`
- `mh_relationships`
- `mh_documentation`
- `mh_changes`
- `mh_column_sizes`
- `mh_report_scan`
- `mh_run_log`

Full column reference: [`skill/references/output-tables.md`](skill/references/output-tables.md).

## Using the skill

`skill/` is a standard Agent Skill folder (`SKILL.md` + `references/` + `assets/`). For Copilot Studio, zip the folder contents and upload them as a skill. `SKILL.md` works on its own if the agent can't load the reference files.

## Repository layout

```
notebook/  Model_Health_Phase1.ipynb (import this) and model_health_src.py (the same code as cells, for review/diffs)
skill/     SKILL.md, references/, assets/ (bundled copy of the notebook)
tests/     test_core.py (pure logic), test_e2e.py (whole notebook vs. mocked Fabric), test_spark.py (real local Spark 3.5)
tools/     to_ipynb.py (build the notebook from the source), patch.py (helpers used during development)
```

## Development

Edit `notebook/model_health_src.py`, then rebuild and test:

```bash
python3 tools/to_ipynb.py notebook/model_health_src.py notebook/Model_Health_Phase1.ipynb
cp notebook/Model_Health_Phase1.ipynb skill/assets/
python3 tests/test_core.py && python3 tests/test_e2e.py
python3 tests/test_spark.py   # needs Java + pyspark==3.5.x
```

Tested against the source of semantic-link-labs 0.18.1 and semantic-link-sempy 0.14.3. It has **not yet been run on a live Fabric tenant**. See `CHANGELOG.md` for what only a live run can confirm.

## Roadmap

- **Phase 2 (not built):** write-mode notebook to apply descriptions, header comments and format strings, with a model backup first.
- **Phase 3 (not built):** staged cleanup (hide → check logs → remove) and a generated "Start Here" README page in reports.
