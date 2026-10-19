"""Regression for GNU Make's multi-arm `else ifeq` blocks."""

import pathlib

import z3

import settings
from kbuild import Kbuild
from helpers.zsolver import ZSolver


def test_else_if_keeps_only_the_first_matching_arm(tmp_path: pathlib.Path):
    makefile = tmp_path / "Makefile"
    makefile.write_text(
        """\
ifeq ($(CONFIG_A),y)
obj-y += first.o
else ifeq ($(CONFIG_B),y)
obj-y += second.o
else
obj-y += last.o
endif
"""
    )
    kb = Kbuild(makefile, settings.Settings(tmp_path))
    kb.preprocess()
    kb.symexe()

    guards = kb.state.states["obj-y"].valconds
    assert set(guards) == {"first.o", "second.o", "last.o"}

    solver = ZSolver(kb.mysettings)
    a, a_values = solver.get_sort("CONFIG_A")
    b, b_values = solver.get_sort("CONFIG_B")
    for a_on, b_on, selected in (
        (True, True, "first.o"),
        (False, True, "second.o"),
        (False, False, "last.o"),
    ):
        assignment = z3.And(
            a == a_values["y" if a_on else ""],
            b == b_values["y" if b_on else ""],
        )
        for word, guard in guards.items():
            assert solver.is_valid(z3.Implies(assignment, guard if word == selected else z3.Not(guard)))
