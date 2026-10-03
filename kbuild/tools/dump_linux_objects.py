#!/usr/bin/env python3
"""Dump kfold's Linux object paths, kinds, and conditions to JSON.

Usage: dump_linux_objects.py OUT.json [PATH_PREFIX ...]
"""
import json
import pathlib
import shutil
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools"))
from alg import Run  # noqa: E402
from kfold_targets import object_conditions  # noqa: E402

runner = Run(ROOT / "results" / "workspaces" / "linux", use_tristate=True)
tmp = runner.go()
conds, kinds = object_conditions(runner)
shutil.rmtree(str(tmp), ignore_errors=True)
prefixes = tuple(sys.argv[2:]) or ("",)
out = {p: {"kind": kinds[p], "cond": str(c).replace("\n", " ")}
       for p, c in conds.items() if p.startswith(prefixes)}
pathlib.Path(sys.argv[1]).write_text(json.dumps(out, indent=1, sort_keys=True))
print(len(conds), "paths;", len(out), "written")
