import pathlib
import tempfile
import pytest
import z3

import settings
import helpers.zsolver as zsolver
from tools.kconfig_solver import KconfigSMT


def test_kconfig_depends_on_enforcement():
    kconfig_content = """
config BUS_PCI
    bool "PCI Bus Support"

config DRIVER_E1000
    bool "Intel E1000 Gigabit Ethernet"
    depends on BUS_PCI
"""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmppath = pathlib.Path(tmpdir)
        kconf_file = tmppath / "Kconfig"
        kconf_file.write_text(kconfig_content)

        mysettings = settings.Settings(tmppath)
        solver = zsolver.ZSolver(mysettings)

        ksmt = KconfigSMT(kconf_file)
        phi_kconfig = ksmt.get_constraints(solver)

        driver_sym, driver_optd = solver.get_sort("CONFIG_DRIVER_E1000")
        bus_sym, bus_optd = solver.get_sort("CONFIG_BUS_PCI")

        # Target condition: compile E1000 driver
        target_cond = (driver_sym == driver_optd['y'])

        # Conjoin Kconfig rules with target condition
        conjoined = zsolver.conj(phi_kconfig, target_cond)

        s = z3.Solver()
        s.add(conjoined)
        assert s.check() == z3.sat

        # In any model where DRIVER_E1000 is y, BUS_PCI must also be y
        model = s.model()
        assert str(model.eval(bus_sym)) == str(bus_optd['y'])


def test_kconfig_select_enforcement():
    kconfig_content = """
config NET_CORE
    bool "Core Networking"

config NET_ETHERNET
    bool "Ethernet Driver Support"
    select NET_CORE
"""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmppath = pathlib.Path(tmpdir)
        kconf_file = tmppath / "Kconfig"
        kconf_file.write_text(kconfig_content)

        mysettings = settings.Settings(tmppath)
        solver = zsolver.ZSolver(mysettings)

        ksmt = KconfigSMT(kconf_file)
        phi_kconfig = ksmt.get_constraints(solver)

        eth_sym, eth_optd = solver.get_sort("CONFIG_NET_ETHERNET")
        core_sym, core_optd = solver.get_sort("CONFIG_NET_CORE")

        target_cond = (eth_sym == eth_optd['y'])
        conjoined = zsolver.conj(phi_kconfig, target_cond)

        s = z3.Solver()
        s.add(conjoined)
        assert s.check() == z3.sat

        model = s.model()
        assert str(model.eval(core_sym)) == str(core_optd['y'])


def test_kconfig_choice_block_exclusion():
    kconfig_content = """
choice
    prompt "Target Architecture"
    default ARCH_X86

config ARCH_X86
    bool "x86 Architecture"

config ARCH_ARM
    bool "ARM Architecture"

endchoice
"""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmppath = pathlib.Path(tmpdir)
        kconf_file = tmppath / "Kconfig"
        kconf_file.write_text(kconfig_content)

        mysettings = settings.Settings(tmppath)
        solver = zsolver.ZSolver(mysettings)

        ksmt = KconfigSMT(kconf_file)
        phi_kconfig = ksmt.get_constraints(solver)

        x86_sym, x86_optd = solver.get_sort("CONFIG_ARCH_X86")
        arm_sym, arm_optd = solver.get_sort("CONFIG_ARCH_ARM")

        # Conjoin choice constraint with both active simultaneously
        conflicting = zsolver.conj(phi_kconfig, z3.And(x86_sym == x86_optd['y'], arm_sym == arm_optd['y']))

        s = z3.Solver()
        s.add(conflicting)
        assert s.check() == z3.unsat


def test_buildable_witness_synthesis():
    kconfig_content = """
config NETWORKING
    bool "Networking Support"

config E1000
    bool "E1000 Support"
    depends on NETWORKING
"""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmppath = pathlib.Path(tmpdir)
        kconf_file = tmppath / "Kconfig"
        kconf_file.write_text(kconfig_content)

        mysettings = settings.Settings(tmppath)
        solver = zsolver.ZSolver(mysettings)

        ksmt = KconfigSMT(kconf_file)
        e1000_sym, e1000_optd = solver.get_sort("CONFIG_E1000")

        witness = ksmt.find_buildable_witness(e1000_sym == e1000_optd['y'], solver)
        assert witness is not None
        assert witness.get("CONFIG_E1000") == "y"
        assert witness.get("CONFIG_NETWORKING") == "y"

        out_dotconfig = tmppath / ".config"
        ksmt.write_dotconfig(witness, out_dotconfig)
        assert out_dotconfig.is_file()
        text = out_dotconfig.read_text()
        assert "CONFIG_E1000=y" in text
        assert "CONFIG_NETWORKING=y" in text
