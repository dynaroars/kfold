#!/usr/bin/env python3
"""Evaluate Kmax (kmaxall) conditions against archived builds.

Inputs are pickles written by tools/run_kmaxall.py, e.g. for Linux

    cd results/workspaces/linux
    ../../../tools/run_kmaxall.py ../../kmaxall_linux_x86.pickle \
        ../../kmaxall_linux_x86.meta.json -T -DSRCARCH=x86 Kbuild lib

which maps each path to an SMT-LIB condition over Boolean variables
``CONFIG_X`` (defined), ``CONFIG_X=y``, ``CONFIG_X=m``, and ``CONFIG_X=<v>``
for non-tristate values. Each variable is set from a normalized .config and
the condition is simplified. Metrics match tools/kfold_targets.compare.
Writes results/kmax_physical_validation.json.
"""
import json
import pathlib
import pickle
import sys

import z3

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools"))
from kfold_targets import compare, config_values, physical_objects  # noqa: E402
from evaluate_physical import SUBJECTS  # noqa: E402

PICKLES = {"Linux": ROOT / "results" / "kmaxall_linux_x86.pickle",
           "BusyBox": ROOT / "results" / "kmaxall_busybox.pickle"}


def value_of(name, configured):
    """Truth value of one Kmax variable under a .config."""
    if "=" in name:
        sym, want = name.split("=", 1)
        have = configured.get(sym, "")
        return have.strip('"') == want.strip('"')
    return configured.get(name, "") not in ("", "n")


def parse(smt):
    f = z3.parse_smt2_string(smt)
    return z3.And(*f) if len(f) else z3.BoolVal(True)


def load_conditions(pickle_path):
    """Return (local, with_dirs, unexpanded).

    kmaxall analyzes each directory separately, so an object's condition is
    relative to its own Makefile. ``with_dirs`` conjoins the recorded
    condition of every ancestor directory entry (``fs/``, ``fs/ext2/``), which
    is how the directory guards must be combined to predict a whole build."""
    raw = pickle.loads(pathlib.Path(pickle_path).read_bytes())
    dirs = {k: parse(v) for k, v in raw.items() if k.endswith("/")}
    local, with_dirs, unexpanded = {}, {}, []
    for path, smt in raw.items():
        if not path.endswith(".o"):
            continue
        if "$(" in path:
            unexpanded.append(path)
            continue
        cond = parse(smt)
        parts = path.split("/")[:-1]
        guards = [dirs[d] for d in ("/".join(parts[:i]) + "/" for i in range(1, len(parts) + 1))
                  if d in dirs]
        local[path] = cond
        with_dirs[path] = z3.And(cond, *guards) if guards else cond
    return local, with_dirs, unexpanded


def truth(expr, values, cache):
    """Truth value of a Boolean Z3 expression under ``values`` (variable name
    -> bool), memoized on AST ids so shared subterms are evaluated once."""
    stack = [(expr, False)]
    while stack:
        e, expanded = stack.pop()
        key = e.get_id()
        if key in cache:
            continue
        if z3.is_true(e) or z3.is_false(e):
            cache[key] = z3.is_true(e)
            continue
        if z3.is_const(e) and e.decl().kind() == z3.Z3_OP_UNINTERPRETED:
            cache[key] = values(str(e))
            continue
        kids = e.children()
        if not expanded:
            stack.append((e, True))
            stack.extend((c, False) for c in kids if c.get_id() not in cache)
            continue
        v = [cache[c.get_id()] for c in kids]
        k = e.decl().kind()
        if k == z3.Z3_OP_NOT:
            r = not v[0]
        elif k == z3.Z3_OP_AND:
            r = all(v)
        elif k == z3.Z3_OP_OR:
            r = any(v)
        elif k == z3.Z3_OP_IMPLIES:
            r = (not v[0]) or v[1]
        elif k in (z3.Z3_OP_EQ, z3.Z3_OP_IFF):
            r = v[0] == v[1]
        elif k == z3.Z3_OP_XOR:
            r = v[0] != v[1]
        elif k == z3.Z3_OP_ITE:
            r = v[1] if v[0] else v[2]
        else:
            raise ValueError(f"unsupported operator {e.decl()}")
        cache[key] = r
    return cache[expr.get_id()]


def evaluate(conds, configured):
    cache, memo = {}, {}

    def values(name):
        if name not in memo:
            memo[name] = value_of(name, configured)
        return memo[name]
    return {path for path, cond in conds.items() if truth(cond, values, cache)}


def evaluate_subject(name, pickle_path):
    local, with_dirs, unexpanded = load_conditions(pickle_path)
    print(name, "kmax objects", len(local), "unexpanded", len(unexpanded), flush=True)
    subject = next(s for s in SUBJECTS if s[0] == name)
    meta_file = pickle_path.with_suffix(".meta.json")
    out = {"subject": name, "source": subject[1],
           "pickle": str(pickle_path.relative_to(ROOT)),
           "run": json.loads(meta_file.read_text()) if meta_file.exists() else None,
           "universe": len(local), "unexpanded_paths": sorted(unexpanded),
           "profiles": {}}
    variants = {"local": local, "with_dirs": with_dirs}
    for pname, config, archive in subject[3]:
        configured = config_values(ROOT / (config or subject[1] + "/.config"))
        physical = physical_objects(ROOT / archive)
        out["profiles"][pname] = {}
        for v, conds in variants.items():
            predicted = evaluate(conds, configured)
            r = compare(predicted, physical, set(conds))
            out["profiles"][pname][v] = r
            print(name, pname, v, {k: r[k] for k in (
                "universe", "predicted", "tp", "fp", "fn_within_universe",
                "outside_universe", "precision_pct", "overlap_pct")}, flush=True)
    return out


def main():
    names = sys.argv[1:] or [n for n, p in PICKLES.items() if p.exists() and p.stat().st_size]
    out = [evaluate_subject(n, PICKLES[n]) for n in names]
    dest = ROOT / "results" / "kmax_physical_validation.json"
    dest.write_text(json.dumps(out, indent=1))
    print("wrote", dest)


if __name__ == "__main__":
    main()
