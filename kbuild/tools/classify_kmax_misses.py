#!/usr/bin/env python3
"""Classify Kmax's in-set misses on Linux (results/kmax_physical_validation.json):
how many are composite members in kfold's analysis and how many lie under
arch/x86/. Writes results/kmax_fn_classes.json."""
import json, sys, pathlib, shutil, collections
sys.path.insert(0, "src"); sys.path.insert(0, "tools")
from alg import Run
from kfold_targets import object_conditions
r = Run(pathlib.Path("results/workspaces/linux").resolve(), use_tristate=True); tmp = r.go()
conds, kinds = object_conditions(r)
shutil.rmtree(str(tmp), ignore_errors=True)
K = {e['subject']: e for e in json.load(open('results/kmax_physical_validation.json'))}['Linux']
out = {}
for p in K['profiles']:
    for v in ('local', 'with_dirs'):
        fn = K['profiles'][p][v]['fn_within_universe_paths']
        mem = sum(kinds.get(x) == 'member' for x in fn)
        arch = sum(x.startswith('arch/x86/') for x in fn)
        out[f"{p}/{v}"] = {"fn": len(fn), "kfold_members": mem, "arch_x86": arch}
        print(p, v, len(fn), 'members', mem, 'arch/x86', arch, flush=True)
json.dump(out, open('results/kmax_fn_classes.json', 'w'), indent=1)
