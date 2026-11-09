"""Convert a '# %%' cell-marked .py file into a Fabric-friendly .ipynb."""
import json
import re
import sys

src, dst = sys.argv[1], sys.argv[2]
text = open(src, encoding="utf-8").read()
parts = re.split(r"^# %%(.*)$", text, flags=re.M)
cells = []
# parts = [preamble, marker1, body1, marker2, body2, ...]
for marker, body in zip(parts[1::2], parts[2::2]):
    marker = marker.strip()
    body = body.strip("\n")
    if marker == "[markdown]":
        lines = [re.sub(r"^# ?", "", l) for l in body.splitlines()]
        cells.append({"cell_type": "markdown", "metadata": {}, "source": "\n".join(lines)})
    else:
        meta = {"tags": ["parameters"]} if marker == "[parameters]" else {}
        cells.append({"cell_type": "code", "metadata": meta, "execution_count": None,
                      "outputs": [], "source": body})

for c in cells:  # ipynb stores source as list of lines
    s = c["source"]
    c["source"] = [l + "\n" for l in s.split("\n")[:-1]] + [s.split("\n")[-1]]

nb = {
    "nbformat": 4, "nbformat_minor": 5,
    "metadata": {
        "kernel_info": {"name": "synapse_pyspark"},
        "kernelspec": {"name": "synapse_pyspark", "display_name": "Synapse PySpark", "language": "Python"},
        "language_info": {"name": "python"},
    },
    "cells": cells,
}
json.dump(nb, open(dst, "w", encoding="utf-8"), indent=1)
print(f"{len(cells)} cells -> {dst}")
