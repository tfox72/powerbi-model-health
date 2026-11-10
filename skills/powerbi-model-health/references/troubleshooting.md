# Troubleshooting

Step 4 of the notebook (Preflight) catches the first four rows before the scan starts.

| Symptom (notebook output or `mh_run_log` Error) | Likely cause | Fix |
|---|---|---|
| "No lakehouse is attached to this notebook" | Preflight found no default lakehouse | Attach one in the Explorer pane, or set `WRITE_TO_LAKEHOUSE = False` to see results in the notebook only. |
| "Nothing to scan… Not found: […]" | A name in `DATASETS` doesn't match a model in the workspace | The message lists the models that exist. Fix the name (case doesn't matter), or set `WORKSPACE` if the models live elsewhere. |
| "No semantic models were found in workspace…" | `WORKSPACE` is empty, so the lakehouse's workspace was used | Set `WORKSPACE` in Step 1 to the workspace that holds the models. |
| "[warn] Could not open '<model>'" in Preflight | XMLA endpoints are off, or you have Build but not Contributor or Write | See the `Read model metadata` row below. The scan still tries every model. |
| "This notebook needs Fabric Runtime 1.3" | The session runs Spark 3.4 or older | Switch to Runtime 1.3 in the workspace Spark settings or in the attached Environment, then restart the session. |
| `semantic-link-labs is not installed` | The `%pip` cell was skipped and no Environment is selected | Run the `%pip` cell, or select the Environment in the toolbar. |
| `%pip` hangs or fails with a connection error | The workspace blocks outbound internet | Use the offline wheel option. Download the wheels on a PC, upload them to `Files/wheels`, and use the commented offline line. |
| `%pip` error in a pipeline run | Pipelines disable inline installs by default | Use an Environment, or add the boolean parameter `_inlineInstallationEnabled = True` to the notebook activity. |
| `%pip` not supported | High Concurrency session | Use an Environment. |
| "Tested with 0.18.1; you have X" | The Environment has a different version | Usually harmless. If a step fails, pin 0.18.1 in the Environment. |
| `Read model metadata` fails with an XMLA, permission or connection error | XMLA endpoints are off, or you lack Write on the model | Ask the Fabric admin to confirm XMLA endpoints are enabled for the tenant and capacity. Get **Contributor** on the workspace, or **Write** on the model. Build alone can query but can't read the full metadata. |
| Confidence **Low** with "Lineage was incomplete or unavailable" | The lineage API (beta) failed, returned more than one page, or returned an unexpected shape | Only reports found so far, plus those in the model's own workspace, were checked. Rerun later. The query-log check (`MONITORING_DAYS`) also lifts this to Medium. |
| `Query-log check` failed | Workspace monitoring isn't enabled on the workspace, or you lack access to its eventhouse | Ask a workspace admin to turn on workspace monitoring, or set `MONITORING_DAYS = 0`. |
| `Find bound reports` failed → confidence **Unknown** | Both the lineage API and the workspace report list failed | Check workspace access, then rerun. |
| Confidence **Unknown**: "None of the N bound reports could be read" | No Contributor access on the report workspaces | Get access. Until then, removal advice is withheld. |
| A report shows "Partly unreadable" | One file in its definition didn't parse | The fields that were read still count as used, but the report counts as not read. Share the file path from the error. |
| `mh_report_scan` Error contains 401/403 | You lack Contributor (or higher) on that report's workspace | Get access, or accept Medium confidence. That report's fields stay unverified. |
| Sizes are 0 with "Not loaded in memory (Direct Lake)" | Direct Lake columns that haven't been queried aren't in memory | Size is unknown, not small. Use the source delta table size if needed. |
| BPA or Vertipaq fails on one model | Unusual model features | The other checks still ran. Share the error text. |
| `mh_changes` lists everything as Added | It's the first run after an upgrade, or the earlier run had no fingerprints | Normal. The next run compares properly. |
| "Could not append to mh_…" / merge errors | A transient write problem, or the table was created by an older notebook version with different column types | Run Step 8 again: it retries only the tables that failed. If it keeps failing, drop the old `mh_` tables or set `TABLE_PREFIX` to a new value such as `"mh2_"`, then rerun. Summary files are written first, so they're unaffected. |
| "Files for run … are already saved" | Step 8 was run twice for the same scan | Nothing to do. Run Step 5 again for a new run. |
| Step 7 shows plain text instead of formatted tables | The notebook front end didn't render markdown | The content is the same. Open `summary.md` from the lakehouse for the formatted version. |
