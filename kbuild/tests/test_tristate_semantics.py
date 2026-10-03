import pathlib
import tempfile
import pytest
import z3

import settings
from kbuild import Kbuild
import helpers.zsolver as zsolver


def analyze_tristate(content: str, use_tristate: bool = True):
    with tempfile.TemporaryDirectory() as tmpdir:
        tmppath = pathlib.Path(tmpdir)
        mk_file = tmppath / "Makefile"
        mk_file.write_text(content)
        mysettings = settings.Settings(tmppath, use_tristate=use_tristate)
        kb = Kbuild(mk_file, mysettings)
        kb.preprocess()
        kb.symexe()
        return kb


def test_tristate_builtin_vs_module():
    content = """
obj-$(CONFIG_E1000) += e1000.o
"""
    # 1. Tristate mode enabled
    kb_tri = analyze_tristate(content, use_tristate=True)
    state = kb_tri.state
    obj_y = state.states.get("obj-y")
    obj_m = state.states.get("obj-m")

    assert obj_y is not None and "e1000.o" in obj_y.valconds
    assert obj_m is not None and "e1000.o" in obj_m.valconds

    cond_y = obj_y.valconds["e1000.o"]
    cond_m = obj_m.valconds["e1000.o"]

    solver = zsolver.ZSolver(kb_tri.mysettings)

    # Both conditions are satisfiable individually
    assert solver.is_sat(cond_y)
    assert solver.is_sat(cond_m)

    # Mutual exclusion: cannot be both built-in and loadable module simultaneously
    assert not solver.is_sat(z3.And(cond_y, cond_m))


def test_twostate_mode_default():
    content = """
obj-$(CONFIG_E1000) += e1000.o
"""
    # 2. Twostate mode (default)
    kb_two = analyze_tristate(content, use_tristate=False)
    state = kb_two.state
    obj_y = state.states.get("obj-y")
    obj_m = state.states.get("obj-m")

    assert obj_y is not None and "e1000.o" in obj_y.valconds
    # In twostate mode, obj-m is not generated from $(CONFIG_E1000)
    assert obj_m is None or "e1000.o" not in obj_m.valconds


def test_config_modules_gating():
    content = """
obj-$(CONFIG_E1000) += e1000.o
"""
    kb = analyze_tristate(content, use_tristate=True)
    obj_m = kb.state.states.get("obj-m")
    cond_m = obj_m.valconds["e1000.o"]

    solver = zsolver.ZSolver(kb.mysettings)
    mod_sym, mod_optd = solver.get_sort("CONFIG_MODULES")

    # If CONFIG_MODULES is disabled (!= y), module compilation is impossible
    non_modular_constraint = (mod_sym != mod_optd['y'])
    assert not solver.is_sat(z3.And(cond_m, non_modular_constraint, mod_sym == mod_optd['']))
