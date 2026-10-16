#!/usr/bin/env python3
"""Check that two dumps of Linux target conditions are logically equivalent.

Each dump is a pickle {path: sexpr} of kfold conditions (tristate domain),
e.g. produced before and after a change to branch merging. Every pair of
formulas that differs syntactically is checked for equivalence with Z3.
Usage: check_merge_equivalence.py BEFORE.pkl AFTER.pkl
"""
import pickle
import re
import sys
import pathlib

import z3

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
import helpers.zsolver as zsolver  # noqa: E402
import settings  # noqa: E402


def main():
    before = pickle.load(open(sys.argv[1], "rb"))
    after = pickle.load(open(sys.argv[2], "rb"))
    assert set(before) == set(after), "different path sets"
    mysettings = settings.Settings(ROOT / "results" / "workspaces" / "linux", use_tristate=True)
    solver = zsolver.ZSolver(mysettings)
    decls = {}

    def declare(text):
        for sym in set(re.findall(r"CONFIG_[A-Za-z0-9_]+", text)):
            if sym not in decls:
                zvar, values = solver.get_sort(sym)
                decls[sym] = zvar
                for v in values.values():
                    decls[str(v)] = v

    differing = [p for p in before if before[p] != after[p]]
    bad = []
    for p in differing:
        declare(before[p] + after[p])
        a = z3.parse_smt2_string(f"(assert {before[p]})", decls=decls)[0]
        b = z3.parse_smt2_string(f"(assert {after[p]})", decls=decls)[0]
        s = z3.Solver()
        s.add(a != b)
        if s.check() != z3.unsat:
            bad.append(p)
    print(f"{len(before)} paths, {len(differing)} syntactically different, "
          f"{len(bad)} not equivalent")
    for p in bad[:20]:
        print("  ", p)
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
