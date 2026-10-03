import pathlib
import tempfile
import pytest
import z3

import settings
from kbuild import Kbuild
import helpers.zsolver as zsolver


def analyze_makefile_content(content: str):
    with tempfile.TemporaryDirectory() as tmpdir:
        tmppath = pathlib.Path(tmpdir)
        mk_file = tmppath / "Makefile"
        mk_file.write_text(content)
        mysettings = settings.Settings(tmppath)
        kb = Kbuild(mk_file, mysettings)
        kb.preprocess()
        kb.symexe()
        res = kb.state.resolve_composites()
        units = kb.state.get_units_by_type()
        return kb, res, units


def test_basic_composite_expansion():
    content = """
obj-y += foo.o
foo-objs := bar.o baz.o
"""
    kb, res, units = analyze_makefile_content(content)
    assert "foo.o" in res["composite_units"]
    assert "bar.o" in res["compilation_units"]
    assert "baz.o" in res["compilation_units"]
    assert "foo.o" not in res["compilation_units"]
    assert set(res["composite_map"]["foo.o"].keys()) == {"bar.o", "baz.o"}


def test_conditional_composite_subfeatures():
    content = """
obj-$(CONFIG_DRIVER) += mydriver.o
mydriver-objs := core.o
mydriver-$(CONFIG_EXTRA) += extra.o
"""
    kb, res, units = analyze_makefile_content(content)
    assert "mydriver.o" in res["composite_units"]
    assert "core.o" in res["compilation_units"]
    assert "extra.o" in res["compilation_units"]

    solver = zsolver.ZSolver(kb.mysettings)
    # core.o condition should imply CONFIG_DRIVER == 'y'
    core_cond = res["compilation_units"]["core.o"]
    driver_sym, optd = solver.get_sort("CONFIG_DRIVER")
    assert solver.is_valid(z3.Implies(driver_sym != optd['y'], z3.Not(core_cond)))

    # extra.o condition should require both CONFIG_DRIVER == 'y' and CONFIG_EXTRA == 'y'
    extra_cond = res["compilation_units"]["extra.o"]
    extra_sym, optd_extra = solver.get_sort("CONFIG_EXTRA")
    assert solver.is_valid(z3.Implies(extra_sym != optd_extra['y'], z3.Not(extra_cond)))


def test_nested_composite_expansion():
    content = """
obj-y += top.o
top-objs := mid.o direct.o
mid-objs := leaf1.o leaf2.o
"""
    kb, res, units = analyze_makefile_content(content)
    assert "top.o" in res["composite_units"]
    assert "mid.o" in res["composite_units"]
    assert "direct.o" in res["compilation_units"]
    assert "leaf1.o" in res["compilation_units"]
    assert "leaf2.o" in res["compilation_units"]
    assert "top.o" not in res["compilation_units"]
    assert "mid.o" not in res["compilation_units"]


def test_linux_bonding_driver_pattern():
    content = """
obj-$(CONFIG_BONDING) += bonding.o
bonding-objs := bond_main.o bond_3ad.o
proc-$(CONFIG_PROC_FS) += bond_procfs.o
bonding-objs += $(proc-y)
"""
    kb, res, units = analyze_makefile_content(content)
    assert "bonding.o" in res["composite_units"]
    assert "bond_main.o" in res["compilation_units"]
    assert "bond_3ad.o" in res["compilation_units"]
    assert "bond_procfs.o" in res["compilation_units"]

    solver = zsolver.ZSolver(kb.mysettings)
    proc_cond = res["compilation_units"]["bond_procfs.o"]
    bonding_sym, bonding_optd = solver.get_sort("CONFIG_BONDING")
    procfs_sym, procfs_optd = solver.get_sort("CONFIG_PROC_FS")

    # bond_procfs requires both CONFIG_BONDING and CONFIG_PROC_FS
    assert solver.is_valid(z3.Implies(bonding_sym != bonding_optd['y'], z3.Not(proc_cond)))
    assert solver.is_valid(z3.Implies(procfs_sym != procfs_optd['y'], z3.Not(proc_cond)))
