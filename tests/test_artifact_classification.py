import pathlib
import tempfile
import pytest
import z3

import settings
from kbuild import Kbuild


def analyze_content(content: str):
    with tempfile.TemporaryDirectory() as tmpdir:
        tmppath = pathlib.Path(tmpdir)
        mk_file = tmppath / "Makefile"
        mk_file.write_text(content)
        mysettings = settings.Settings(tmppath)
        kb = Kbuild(mk_file, mysettings)
        kb.preprocess()
        kb.symexe()
        return kb.state.get_units_by_type(solver=kb.solver)


def test_hostprogs_isolation():
    content = """
obj-y += kernel_mod.o
hostprogs-y += fixdep genksyms
userprogs-y += bpf_helper
always-y += check_arch
"""
    units = analyze_content(content)
    assert "kernel_mod.o" in units["compilation_units"]
    assert "fixdep" in units["hostprog_units"]
    assert "genksyms" in units["hostprog_units"]
    assert "bpf_helper" in units["hostprog_units"]
    assert "check_arch" in units["hostprog_units"]

    # Host programs must NOT be categorized as target compilation units
    assert "fixdep" not in units["compilation_units"]
    assert "genksyms" not in units["compilation_units"]
    assert "bpf_helper" not in units["compilation_units"]


def test_coreboot_dialect_stages():
    content = """
bootblock-y += bootblock_entry.o
romstage-y += memory_init.o
ramstage-$(CONFIG_PCI) += pci_scan.o
smm-y += smm_handler.o
"""
    units = analyze_content(content)
    assert "bootblock_entry.o" in units["dialect_units"]
    assert "memory_init.o" in units["dialect_units"]
    assert "pci_scan.o" in units["dialect_units"]
    assert "smm_handler.o" in units["dialect_units"]


def test_barebox_pbl_dialect():
    content = """
obj-y += main_driver.o
pbl-y += entry_pbl.o
obj-pbl-y += common_clock.o
"""
    units = analyze_content(content)
    assert "main_driver.o" in units["compilation_units"]
    assert "entry_pbl.o" in units["dialect_units"]
    assert "common_clock.o" in units["dialect_units"]


def test_clean_files_and_extra_targets():
    content = """
obj-y += main.o
clean-files += temp.bin generated.c
extra-y += vmlinux.lds
targets += image.elf
"""
    units = analyze_content(content)
    assert "main.o" in units["compilation_units"]
    assert "temp.bin" in units["clean_files"]
    assert "generated.c" in units["clean_files"]
    assert "vmlinux.lds" in units["extra_targets"]
    assert "image.elf" in units["extra_targets"]
