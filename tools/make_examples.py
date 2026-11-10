"""
Regenerate examples/ from the end-to-end test's synthetic workspace (no Fabric needed).
The models, reports and numbers are test fixtures, not real data.

Usage: python tools/make_examples.py
"""
import contextlib
import importlib.util
import io
import pathlib
import shutil

ROOT = pathlib.Path(__file__).resolve().parent.parent
KEEP = ["summary.md", "summary_Sales_Model.md", "dictionary_Sales_Model.md", "doc_worklist_Sales_Model.csv",
        "top_issues.csv", "unused_candidates.csv"]

spec = importlib.util.spec_from_file_location("e2e", ROOT / "tests" / "test_e2e.py")
e2e = importlib.util.module_from_spec(spec)
with contextlib.redirect_stdout(io.StringIO()):
    spec.loader.exec_module(e2e)          # runs every scenario once
    e2e.run_notebook()                    # then a clean, normal run
latest = pathlib.Path(e2e.FILES) / "model_health" / "latest"
out = ROOT / "examples"
out.mkdir(exist_ok=True)
for name in KEEP:
    shutil.copyfile(latest / name, out / name)
print(f"Wrote {len(KEEP)} example files to {out.relative_to(ROOT)}/")
