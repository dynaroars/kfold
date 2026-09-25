"""Tristate (y/m/n) semantics of tools/kconfig_solver.KconfigSMT."""
import pathlib
import tempfile

import pytest
import z3

import settings
import helpers.zsolver as zsolver
from tools.kconfig_solver import KconfigSMT

KCONFIG = """
config MODULES
    bool "Modules"

config BUS
    tristate "Bus"

config DRV
    tristate "Driver"
    depends on BUS

config BOOLDRV
    bool "Bool driver"
    depends on BUS

config LIB
    tristate

config USER
    tristate "Library user"
    select LIB

config GHOSTY
    bool "Depends on an undefined symbol"
    depends on NOT_DEFINED_ANYWHERE

config NOTBUS
    bool "Only without BUS"
    depends on !BUS

config EQBUS
    bool "Only when BUS=m"
    depends on BUS = m
"""


@pytest.fixture(scope="module")
def env():
    with tempfile.TemporaryDirectory() as tmpdir:
        tmppath = pathlib.Path(tmpdir)
        (tmppath / "Kconfig").write_text(KCONFIG)
        mysettings = settings.Settings(tmppath, use_tristate=True)
        solver = zsolver.ZSolver(mysettings)
        ksmt = KconfigSMT(tmppath / "Kconfig")
        yield ksmt, solver, ksmt.get_constraints(solver)


def _val(solver, name, v):
    sym, optd = solver.get_sort(f"CONFIG_{name}")
    return sym == optd[{"y": "y", "m": "m", "n": ""}[v]]


def _sat(env, *assigns):
    _, solver, phi = env
    s = z3.Solver()
    s.add(phi, *[_val(solver, n, v) for n, v in assigns])
    return s.check() == z3.sat


def test_module_dependency_satisfies_depends_on(env):
    # DRV=m needs BUS on; BUS=m is enough.
    assert _sat(env, ("MODULES", "y"), ("BUS", "m"), ("DRV", "m"))
    assert not _sat(env, ("BUS", "n"), ("DRV", "m"))


def test_module_dependency_caps_tristate_at_m(env):
    assert not _sat(env, ("MODULES", "y"), ("BUS", "m"), ("DRV", "y"))


def test_bool_is_never_m_and_rounds_up(env):
    assert not _sat(env, ("BOOLDRV", "m"))
    # A bool depending on an m symbol may be y.
    assert _sat(env, ("MODULES", "y"), ("BUS", "m"), ("BOOLDRV", "y"))


def test_m_requires_modules(env):
    assert not _sat(env, ("MODULES", "n"), ("BUS", "m"))


def test_select_sets_lower_bound(env):
    assert not _sat(env, ("USER", "y"), ("LIB", "m"))
    assert not _sat(env, ("MODULES", "y"), ("USER", "m"), ("LIB", "n"))
    assert _sat(env, ("MODULES", "y"), ("USER", "m"), ("LIB", "m"))


def test_undefined_symbol_is_n(env):
    assert not _sat(env, ("GHOSTY", "y"))


def test_negated_dependency(env):
    assert _sat(env, ("BUS", "n"), ("NOTBUS", "y"))
    # !m = m, which still permits a bool (it rounds up).
    assert _sat(env, ("MODULES", "y"), ("BUS", "m"), ("NOTBUS", "y"))
    assert not _sat(env, ("BUS", "y"), ("NOTBUS", "y"))


def test_equality_against_m(env):
    assert _sat(env, ("MODULES", "y"), ("BUS", "m"), ("EQBUS", "y"))
    assert not _sat(env, ("BUS", "y"), ("EQBUS", "y"))


def test_cone_restricts_constraints(env):
    ksmt, solver, _ = env
    cone = ksmt.dependency_cone(["CONFIG_DRV"])
    assert cone == {"DRV", "BUS"}
    s = z3.Solver()
    s.add(ksmt.get_constraints(solver, cone), _val(solver, "BUS", "n"), _val(solver, "DRV", "y"))
    assert s.check() == z3.unsat


def test_promptless_symbol_follows_select():
    kconfig = """
config MODULES
    bool "Modules"

config HELPER
    tristate

config FS
    tristate "Filesystem"
    select HELPER
"""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmppath = pathlib.Path(tmpdir)
        (tmppath / "Kconfig").write_text(kconfig)
        mysettings = settings.Settings(tmppath, use_tristate=True)
        solver = zsolver.ZSolver(mysettings)
        ksmt = KconfigSMT(tmppath / "Kconfig")
        env = (ksmt, solver, ksmt.get_constraints(solver))
        # FS=m selects HELPER to m; HELPER has no prompt, so it cannot be y.
        assert not _sat(env, ("MODULES", "y"), ("FS", "m"), ("HELPER", "y"))
        assert _sat(env, ("MODULES", "y"), ("FS", "m"), ("HELPER", "m"))
        assert not _sat(env, ("FS", "n"), ("HELPER", "y"))
