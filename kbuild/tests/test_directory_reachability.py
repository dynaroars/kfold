"""Directory traversal must propagate new guards and stop on cycles."""

import pathlib

import z3

from alg import Run
from helpers.zsolver import ZSolver, disj


def test_shared_directory_reached_later_and_cycle_terminates(tmp_path: pathlib.Path):
    for directory in ("a", "b", "c", "shared"):
        (tmp_path / directory).mkdir()
    (tmp_path / "Makefile").write_text("obj-y += a/ b/\n")
    (tmp_path / "a" / "Makefile").write_text("obj-$(CONFIG_A) += ../shared/\n")
    (tmp_path / "b" / "Makefile").write_text("obj-$(CONFIG_B) += ../c/\n")
    (tmp_path / "c" / "Makefile").write_text("obj-y += ../shared/\n")
    (tmp_path / "shared" / "Makefile").write_text("obj-y += x.o ../a/\n")

    runner = Run(tmp_path)
    runner.go()
    shared = [kb for kb in runner.all_kbuilds if kb.makefile.parent == tmp_path / "shared"]
    assert len(shared) == 2
    assert len(runner.all_kbuilds) == 6

    guards = [kb.state.states["obj-y"].valconds["x.o"] for kb in shared]
    combined = disj(*guards)
    solver = ZSolver(runner.mysettings)
    a, a_values = solver.get_sort("CONFIG_A")
    b, b_values = solver.get_sort("CONFIG_B")
    expected = z3.Or(a == a_values["y"], b == b_values["y"])
    assert solver.is_valid(combined == expected)
