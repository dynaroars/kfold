#!/usr/bin/env python3
"""Analyze one submitted Makefile with kfold and print the result as JSON.

Run by server.py in a separate process with a timeout and KFOLD_SANDBOX=1,
so $(shell ...) never runs and includes stay inside the temporary tree.

Input (stdin, JSON): {"makefile": text, "tristate": bool, "config": text}
Output (stdout, JSON): {"variables": {...}, "objects": [...], "evaluation": {...}}
"""
import json
import os
import pathlib
import shutil
import sys
import tempfile

os.environ["KFOLD_SANDBOX"] = "1"
ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import settings  # noqa: E402
settings.logger_level = 0
from alg import Run  # noqa: E402
from objects import object_conditions, predicted_objects  # noqa: E402

HIDDEN = ("__rule", "src", "obj")


def text(cond):
    return " ".join(str(cond).split())


def main():
    req = json.load(sys.stdin)
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="kfold_web_"))
    try:
        (tmp / "Makefile").write_text(req.get("makefile", ""))
        tristate = bool(req.get("tristate", True))
        (tmp / "skbuild.ini").write_text(
            "[COMMON]\nuse_tristate = %s\n" % ("yes" if tristate else "no"))
        runner = Run(tmp / "Makefile", use_tristate=tristate)
        cache = runner.go()
        kb = runner.all_kbuilds[0]
        variables = {}
        for name, var in sorted(kb.state.states.items()):
            if name.startswith(HIDDEN):
                continue
            variables[name] = [[str(w), text(c)] for w, c in var.valconds.items()]
        origins = {}
        conds, kinds = object_conditions(runner, origins=origins)
        objects = [{"path": p, "kind": kinds[p], "cond": text(c),
                    "origins": sorted(w for _, w in origins.get(p, ()))}
                   for p, c in sorted(conds.items())]
        evaluation = None
        if req.get("config", "").strip():
            cfg = tmp / "config"
            cfg.write_text(req["config"])
            built = predicted_objects(runner, conds, cfg)
            evaluation = {"built": sorted(built),
                          "not_built": sorted(set(conds) - built)}
        shutil.rmtree(str(cache), ignore_errors=True)
        print(json.dumps({"variables": variables, "objects": objects,
                          "evaluation": evaluation,
                          "parse_error": getattr(kb, "parse_error", None)}))
    finally:
        shutil.rmtree(str(tmp), ignore_errors=True)


if __name__ == "__main__":
    main()
