import pathlib
import tempfile
import pytest
import z3

import settings
from tools.lint_dead_targets import lint_dead_targets


def test_orphaned_unexpanded_targets():
    content = """
obj-y += active.o
obj-$(CONFIG_REMOVED_FEATURE) += orphan_driver.o
lib-$(CONFIG_DEPRECATED) += orphan_lib.o
"""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmppath = pathlib.Path(tmpdir)
        mk_file = tmppath / "Makefile"
        mk_file.write_text(content)

        report = lint_dead_targets(mk_file, recursive=False)
        orphans = [item["target"] for item in report["orphaned_targets"]]

        assert "orphan_driver.o" in orphans
        assert "orphan_lib.o" in orphans
        assert "active.o" not in orphans


def test_unsatisfiable_targets():
    content = """
obj-y += valid.o

ifeq ($(CONFIG_FEATURE),y)
ifeq ($(CONFIG_FEATURE),)
obj-y += impossible.o
endif
endif
"""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmppath = pathlib.Path(tmpdir)
        mk_file = tmppath / "Makefile"
        mk_file.write_text(content)

        report = lint_dead_targets(mk_file, recursive=False)
        unsat_targets = [item["target"] for item in report["unsatisfiable_targets"]]

        # impossible.o has condition CONFIG_FEATURE == y and CONFIG_FEATURE == undef => UNSAT
        assert "impossible.o" in unsat_targets
        assert "valid.o" not in unsat_targets


def test_barebox_pmu_defect_reproduction():
    # Model the defect found in Barebox firmware/Makefile
    content = """
firmware-$(CONFIG_FIRMWARE_PMU) += pmu_fw.o
obj-y += $(firmware-y)
"""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmppath = pathlib.Path(tmpdir)
        mk_file = tmppath / "Makefile"
        mk_file.write_text(content)

        report = lint_dead_targets(mk_file, recursive=False)
        orphans = [item["target"] for item in report["orphaned_targets"]]
        # When CONFIG_FIRMWARE_PMU is unexpanded, firmware-y is empty and firmware- is set
        assert "pmu_fw.o" in orphans
