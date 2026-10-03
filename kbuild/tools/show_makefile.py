#!/usr/bin/env python3
"""Print the guarded variables of one Makefile analyzed in its tree's context.

Usage: show_makefile.py TREE REL/PATH/Makefile [--vars PATTERN]

TREE supplies the project settings (skbuild.ini); the Makefile is analyzed
on its own, without the guard under which its directory is reached.
"""
import argparse
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
import settings  # noqa: E402
from kbuild import Kbuild  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("tree")
    ap.add_argument("makefile")
    ap.add_argument("--vars", default=".", help="regex selecting variable names")
    args = ap.parse_args()
    tree = pathlib.Path(args.tree).resolve()
    s = settings.Settings(tree)
    kb = Kbuild(tree / args.makefile, s)
    kb.preprocess()
    kb.symexe()
    print("includes:", kb.include_stats, "parse error:", kb.parse_error)
    for name, var in sorted(kb.state.states.items()):
        if not re.search(args.vars, name):
            continue
        print(f"{name}:")
        for word, cond in var.valconds.items():
            print(f"    {word}  <-  {str(cond)}".replace("\n", " "))


if __name__ == "__main__":
    main()
