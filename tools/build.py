"""
Build everything that is generated from a single source:

  notebook/model_health_src.py  ->  notebook/Model_Health_Phase1.ipynb
  skills/powerbi-model-health/  ->  dist/copilot/powerbi-model-health.zip   (SKILL.md at the zip root)
                                    dist/claude/powerbi-model-health.zip    (skill folder at the zip root)

Usage:
  python tools/build.py           build the notebook and both skill packages
  python tools/build.py --check   exit 1 if the committed notebook differs from what the source would build

The source file is plain Python split into cells by marker lines:
  # %% [markdown]     markdown cell (each line starts with "# ")
  # %% [parameters]   code cell tagged as the Fabric parameters cell
  # %% [engine]       code cell whose source is collapsed by default (function library)
  # %%                ordinary code cell
"""
import json
import pathlib
import re
import sys
import zipfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC = ROOT / "notebook" / "model_health_src.py"
NOTEBOOK = ROOT / "notebook" / "Model_Health_Phase1.ipynb"
SKILL_DIR = ROOT / "skills" / "powerbi-model-health"


def split_cells(text: str) -> list:
    """[(kind, body)] where kind is 'markdown', 'parameters', 'engine' or 'code'."""
    parts = re.split(r"^# %%(.*)$", text, flags=re.M)
    cells = []
    for marker, body in zip(parts[1::2], parts[2::2]):
        tag = marker.strip().strip("[]") or "code"
        cells.append((tag, body.strip("\n")))
    return cells


def build_notebook(text: str) -> dict:
    cells = []
    for kind, body in split_cells(text):
        if kind == "markdown":
            source = "\n".join(re.sub(r"^# ?", "", line) for line in body.splitlines())
            cell = {"cell_type": "markdown", "metadata": {}, "source": source}
        else:
            metadata = {}
            if kind == "parameters":
                metadata["tags"] = ["parameters"]
            elif kind == "engine":
                # Collapses the cell's source in Jupyter-compatible front ends; ignored where unsupported.
                metadata["jupyter"] = {"source_hidden": True}
            cell = {"cell_type": "code", "metadata": metadata, "execution_count": None, "outputs": [], "source": body}
        lines = cell["source"].split("\n")
        cell["source"] = [line + "\n" for line in lines[:-1]] + [lines[-1]]
        cells.append(cell)
    return {
        "nbformat": 4, "nbformat_minor": 5,
        "metadata": {
            "kernel_info": {"name": "synapse_pyspark"},
            "kernelspec": {"name": "synapse_pyspark", "display_name": "Synapse PySpark", "language": "Python"},
            "language_info": {"name": "python"},
        },
        "cells": cells,
    }


def notebook_text() -> str:
    return json.dumps(build_notebook(SRC.read_text(encoding="utf-8")), indent=1) + "\n"


def build_skill_packages() -> list:
    files = sorted(p for p in SKILL_DIR.rglob("*") if p.is_file())
    out = []
    for flavour, prefix in (("copilot", ""), ("claude", SKILL_DIR.name + "/")):
        target = ROOT / "dist" / flavour / f"{SKILL_DIR.name}.zip"
        target.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as z:
            for p in files:
                z.write(p, prefix + p.relative_to(SKILL_DIR).as_posix())
        out.append(target)
    return out


def main() -> int:
    text = notebook_text()
    if "--check" in sys.argv:
        if not NOTEBOOK.exists() or NOTEBOOK.read_text(encoding="utf-8") != text:
            print("Notebook is out of date: run `python tools/build.py`.")
            return 1
        print("Notebook matches its source.")
        return 0
    NOTEBOOK.write_text(text, encoding="utf-8")
    print(f"Built {NOTEBOOK.relative_to(ROOT)} ({len(json.loads(text)['cells'])} cells)")
    for target in build_skill_packages():
        print(f"Built {target.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
