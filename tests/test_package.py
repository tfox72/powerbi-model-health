"""
Packaging checks: everything generated is in sync with its source, and the skill meets the limits
of the places it will be used.
"""
import json
import pathlib
import re
import sys
import zipfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import build

SKILL = ROOT / "skills" / "powerbi-model-health"

# 1. The committed notebook is exactly what the source builds (one source of truth).
assert (ROOT / "notebook" / "Model_Health_Phase1.ipynb").read_text(encoding="utf-8") == build.notebook_text(), \
    "notebook is out of date: run `python tools/build.py`"
nb = json.loads(build.notebook_text())
kinds = [c["cell_type"] for c in nb["cells"]]
assert kinds[0] == "markdown" and "code" in kinds
params = [c for c in nb["cells"] if c["metadata"].get("tags") == ["parameters"]]
assert len(params) == 1, "exactly one parameters cell"
# The first executable line is the runtime check, and %pip comes before any other import of the library
code_cells = ["".join(c["source"]) for c in nb["cells"] if c["cell_type"] == "code"]
assert "pyspark.__version__" in code_cells[0] and code_cells[1].lstrip().startswith("%pip")
# Step headings are numbered 0..9 in order (the Fabric table of contents)
steps = [int(m.group(1)) for c in nb["cells"] if c["cell_type"] == "markdown"
         for m in [re.match(r"## Step (\d+)", "".join(c["source"]))] if m]
assert steps == list(range(10)), steps
# No copy of the notebook anywhere else in the repo
copies = [p for p in ROOT.rglob("*.ipynb") if "dist" not in p.parts and ".git" not in p.parts]
assert [p.relative_to(ROOT).as_posix() for p in copies] == ["notebook/Model_Health_Phase1.ipynb"], copies
print("notebook in sync with source; single copy")

# 2. Skill format: folder name matches the name in the frontmatter; description within the spec's limit.
text = (SKILL / "SKILL.md").read_text(encoding="utf-8")
front = re.match(r"---\n(.*?)\n---\n", text, flags=re.S)
assert front, "SKILL.md needs YAML frontmatter"
meta = dict(line.split(": ", 1) for line in front.group(1).splitlines())
assert set(meta) == {"name", "description"}, meta.keys()
assert meta["name"] == SKILL.name and re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", meta["name"])
assert len(meta["description"]) <= 1024, len(meta["description"])
assert "<" not in meta["description"] and ">" not in meta["description"], "no angle brackets in the description"
# Every reference the skill mentions exists, and every reference file is mentioned
mentioned = set(re.findall(r"references/([\w\-]+\.md)", text))
present = {p.name for p in (SKILL / "references").glob("*.md")}
assert mentioned == present, (mentioned ^ present)
# Resource files stay small: Microsoft documents a 20 KB read limit for text resources in Copilot Studio business skills
for p in SKILL.rglob("*"):
    if p.is_file():
        assert p.suffix == ".md", f"only markdown in the skill package: {p.name}"
        assert p.stat().st_size < 20_000, (p.name, p.stat().st_size)
print(f"skill ok: {len(text):,} chars, {len(present)} references")

# 3. The compact instructions fit Agent Builder's 8,000-character limit, with room to spare.
compact = (ROOT / "copilot" / "agent-instructions.md").read_text(encoding="utf-8")
assert len(compact) <= 7_800, len(compact)
for must in ("strong removal candidate", "doc_worklist_<model>.csv", "dictionary_<model>.md", "KEEPFILTERS", "Preflight"):
    assert must in compact and must in text, must
print(f"agent-instructions.md: {len(compact):,} of 8,000 chars")

# 4. Both packages build with the layout each product expects.
copilot_zip, claude_zip = build.build_skill_packages()
with zipfile.ZipFile(copilot_zip) as z:
    names = z.namelist()
    assert "SKILL.md" in names and "references/output-tables.md" in names, names      # SKILL.md at the zip root
with zipfile.ZipFile(claude_zip) as z:
    names = z.namelist()
    assert "powerbi-model-health/SKILL.md" in names, names                             # skill folder at the zip root
print("packages ok")

# 5. Docs point at things that exist: relative links in the README, file names in the skill.
readme = (ROOT / "README.md").read_text(encoding="utf-8")
for link in re.findall(r"\]\((?!https?://|#)([^)#]+)", readme):
    assert (ROOT / link).exists(), f"README links to a missing path: {link}"
src = (ROOT / "notebook" / "model_health_src.py").read_text(encoding="utf-8")
for fname in ("summary.md", "top_issues.csv", "top_findings.csv", "unused_candidates.csv", "doc_worklist_", "dictionary_"):
    assert fname in src and fname in (SKILL / "references" / "output-tables.md").read_text(encoding="utf-8"), fname
version = re.search(r'NOTEBOOK_VERSION = "([\d.]+)"', src).group(1)
assert f"Version {version}" in src and version in (ROOT / "CHANGELOG.md").read_text(encoding="utf-8"), version
print(f"docs ok (version {version})")
print("PACKAGE TESTS PASSED")
