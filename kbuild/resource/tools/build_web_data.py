#!/usr/bin/env python3
"""Precompute the Linux data served by the web interface.

Writes web/data/linux-v6.6.json.gz with, for each object path kfold extracts
from results/workspaces/linux, its kind, origins, a readable condition, and
the root of its condition in a shared node table. The table is hash-consed on
Z3 AST ids, so subformulas shared across objects are stored once. Nodes are
["t"], ["f"], ["eq", option, value], ["not", n], ["and", n...], ["or", n...].
The four evaluated profiles are stored as option values.
"""
import gzip
import json
import pathlib
import shutil
import sys
import time

import z3

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
from alg import Run  # noqa: E402
from objects import config_values, object_conditions  # noqa: E402

LINUX = ROOT / "results" / "workspaces" / "linux"
PROFILES = {
    "tinyconfig (i386)": "results/revalidation_builds/linux_configs/tinyconfig_i386/.config",
    "defconfig (x86-64)": "results/revalidation_builds/linux_configs/defconfig/.config",
    "Debian (x86-64)": "results/workspaces/linux/.config",
    "allmodconfig (x86-64)": "results/revalidation_builds/linux_configs/allmodconfig/.config",
}
MAX_TEXT = 1500


class Table:
    def __init__(self):
        self.nodes, self.ids, self.options = [], {}, set()

    def node(self, e):
        key = e.get_id()
        if key in self.ids:
            return self.ids[key]
        if z3.is_true(e):
            n = ["t"]
        elif z3.is_false(e):
            n = ["f"]
        else:
            k = e.decl().kind()
            if k == z3.Z3_OP_EQ:
                a, b = e.arg(0), e.arg(1)
                if a.decl().kind() != z3.Z3_OP_UNINTERPRETED:
                    a, b = b, a
                self.options.add(str(a))
                n = ["eq", str(a), str(b)]
            elif k == z3.Z3_OP_NOT:
                n = ["not", self.node(e.arg(0))]
            elif k in (z3.Z3_OP_AND, z3.Z3_OP_OR):
                n = ["and" if k == z3.Z3_OP_AND else "or"] + [self.node(c) for c in e.children()]
            else:
                raise ValueError(f"unexpected operator in {e}")
        self.ids[key] = len(self.nodes)
        self.nodes.append(n)
        return self.ids[key]


def main():
    t0 = time.monotonic()
    runner = Run(LINUX, use_tristate=True)
    tmp = runner.go()
    analysis_seconds = time.monotonic() - t0
    origins = {}
    conds, kinds = object_conditions(runner, origins=origins)
    shutil.rmtree(str(tmp), ignore_errors=True)
    table = Table()
    objects = {}
    for path in sorted(conds):
        cond = conds[path]
        root = table.node(cond if isinstance(cond, z3.ExprRef) else z3.BoolVal(bool(cond)))
        text = str(cond).replace("\n", " ")
        text = " ".join(text.split())
        objects[path] = {
            "kind": kinds[path],
            "root": root,
            "text": text if len(text) <= MAX_TEXT else text[:MAX_TEXT] + " ...",
            "origins": sorted(f"{mk}: {what}" for mk, what in origins.get(path, ())),
        }
    profiles = {}
    for name, cfg in PROFILES.items():
        values = config_values(ROOT / cfg)
        profiles[name] = {o: values[o] for o in table.options if o in values}
    data = {
        "tree": "Linux v6.6 (x86)",
        "commit": "ffc253263a1375a65fa6c9f62a893e9767fbebfa",
        "analysis_seconds": round(analysis_seconds, 1),
        "makefile_instances": len(runner.all_kbuilds),
        "nodes": table.nodes,
        "objects": objects,
        "profiles": profiles,
    }
    out = ROOT / "web" / "data" / "linux-v6.6.json.gz"
    out.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(out, "wt") as f:
        json.dump(data, f, separators=(",", ":"))
    print(f"{len(objects)} objects, {len(table.nodes)} nodes, "
          f"{out.stat().st_size // 1024} KB -> {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
