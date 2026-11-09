"""Replace whole top-level functions / exact text blocks in model_health_src.py."""
import re
import sys

import pathlib
PATH = str(pathlib.Path(__file__).resolve().parent.parent / "notebook" / "model_health_src.py")


def load():
    return open(PATH, encoding="utf-8").read()


def save(s):
    open(PATH, "w", encoding="utf-8").write(s)


def replace_func(src, name, new_code):
    """Replace 'def name(...)' through the line before the next top-level statement/comment/cell marker."""
    m = re.search(rf"^def {re.escape(name)}\(", src, flags=re.M)
    if not m:
        raise SystemExit(f"function {name} not found")
    start = m.start()
    nxt = re.search(r"^(?=\S)(?!def |\s)", src[m.end():], flags=re.M)
    # find next line that starts at column 0 and is not part of this def
    lines = src[start:].split("\n")
    end_offset = len(lines[0]) + 1
    for line in lines[1:]:
        if line and not line[0].isspace() and not line.startswith(")"):
            break
        end_offset += len(line) + 1
    body_end = start + end_offset
    # keep trailing blank lines out of the replaced block
    block = src[start:body_end].rstrip("\n")
    return src[:start] + new_code.rstrip("\n") + src[start + len(block):]


def replace_text(src, old, new, count=1):
    if src.count(old) != count:
        raise SystemExit(f"expected {count} match(es), found {src.count(old)} for:\n{old[:200]}")
    return src.replace(old, new)
