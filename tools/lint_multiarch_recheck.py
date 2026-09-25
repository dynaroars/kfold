#!/usr/bin/env python3
"""Recheck `kfold lint` dead-everywhere findings under every architecture's Kconfig.

`kfold lint` parses one architecture's Kconfig, so an object enabled only by a
`select` or `depends on` declared under another architecture looks dead. This
reparses the tree's Kconfig with ARCH set to each other architecture and keeps
the objects whose Kbuild condition is unsatisfiable on all of them.

Usage: lint_multiarch_recheck.py [TREE] [LINT.json] [OUT.json]
"""
import json, os, sys, pathlib
ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'src')); import cli  # noqa: E402,F401
import z3, settings, helpers.zsolver as zsolver
from cli import cache
from kconfig_solver import KconfigSMT, formula_vars
tree = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else ROOT / 'results/workspaces/linux').resolve()
a = cache.load(tree)
f = json.load(open(sys.argv[2] if len(sys.argv) > 2 else os.path.expanduser('~/.cache/kfold-lint/lint_final2.json')))['findings']
rest = [x['file'] for x in f if x.get('class') == 'dead' and x['severity'] == 'error' and not x.get('bool_composite_container')]
alive = {}
for arch in ['arm64', 'arm', 'riscv', 'powerpc', 'mips', 's390', 'loongarch', 'sparc', 'm68k', 'xtensa', 'sh', 'arc', 'microblaze', 'openrisc', 'parisc', 'alpha', 'csky', 'nios2', 'hexagon', 'um']:
    todo = [p for p in rest if p not in alive]
    if not todo: break
    os.environ.update(ARCH=arch, SRCARCH=arch)
    try:
        k = KconfigSMT(tree / 'Kconfig', srctree=tree)
    except Exception as e:
        print(arch, 'parse failed', str(e)[:80], flush=True); continue
    solver = a.solver()
    n = 0
    for p in todo:
        cond = a.conds[p]
        names = [str(v) for v in formula_vars(cond) if str(v).startswith('CONFIG_')]
        phi = k.get_constraints(solver, k.dependency_cone(names))
        s = z3.Solver(); s.set('timeout', 10000); s.add(phi, cond)
        if s.check() == z3.sat:
            alive[p] = arch; n += 1
    print(arch, 'newly alive', n, 'remaining', len(rest) - len(alive), flush=True)
dead = sorted(set(rest) - set(alive))
json.dump({'checked': len(rest), 'alive_on': alive, 'dead_all_arches': dead}, open(sys.argv[3] if len(sys.argv) > 3 else 'lint_multiarch.json', 'w'), indent=1)
print('dead on all arches tried:', len(dead)); print('\n'.join(dead))
