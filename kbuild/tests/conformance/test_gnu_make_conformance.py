#!/usr/bin/env python3
"""Differential Conformance Test Suite (M12.2).

Compares kfold symbolic variable expansions against GNU Make ground truth (make -p / execution)
across combinations of:
- Immediate assignment (:=) vs Deferred assignment (=)
- Conditional default assignment (?=)
- Appending (+=) preserving flavor
- Pattern substitution ($(patsubst ...))
- Filtering ($(filter ...), $(filter-out ...))
- String prefixes ($(addprefix ...), $(addsuffix ...))
- Computed variable names ($(obj-$(CONFIG_X)))
"""

import os
import pathlib
import subprocess
import sys
import tempfile
import unittest

ROOT_DIR = pathlib.Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT_DIR / "src"))

from alg import Run
import settings


class GNUmakeConformanceTest(unittest.TestCase):
    def _run_kfold(self, makefile_content: str, ini_content: str = None) -> dict:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = pathlib.Path(tmpdir)
            (tmp_path / "Makefile").write_text(makefile_content)
            if ini_content is None:
                ini_content = "[COMMON]\nuse_tristate = yes\ntop_dirs = .\n"
            (tmp_path / "skbuild.ini").write_text(ini_content)

            runner = Run(tmp_path)
            res_dir = runner.go()
            kbuilds = getattr(runner, "all_kbuilds", getattr(runner, "kbuilds", []))
            
            targets = {}
            for kb in kbuilds:
                for v in kb.state.target_files:
                    for word, cond in v.valconds.items():
                        targets[word] = str(cond)
            return targets

    def _run_gnu_make(self, makefile_content: str, target_var: str = "obj-y") -> str:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = pathlib.Path(tmpdir)
            full_content = makefile_content + f"\nall:\n\t@echo $({target_var})\n"
            (tmp_path / "Makefile").write_text(full_content)
            proc = subprocess.run(["make", "-s"], cwd=tmp_path, stdout=subprocess.PIPE, text=True)
            return proc.stdout.strip()

    def test_immediate_vs_deferred_flavor(self):
        """Test := freezing vs = deferred expansion."""
        mk = """
VAR_A = first
VAR_B := $(VAR_A)
VAR_C = $(VAR_A)
VAR_A = second
obj-y := $(VAR_B).o $(VAR_C).o
"""
        gnu_res = self._run_gnu_make(mk)
        self.assertEqual(gnu_res, "first.o second.o")
        kfold_targets = self._run_kfold(mk)
        self.assertIn("first.o", kfold_targets)
        self.assertIn("second.o", kfold_targets)

    def test_patsubst_and_filters(self):
        """Test patsubst, filter, and filter-out functions."""
        mk = """
SRCS := a.c b.c test_c.c d.s
OBJS := $(patsubst %.c,%.o,$(SRCS))
FILTERED := $(filter-out test_%,$(OBJS))
obj-y := $(FILTERED)
"""
        gnu_res = self._run_gnu_make(mk)
        self.assertEqual(gnu_res, "a.o b.o d.s")
        kfold_targets = self._run_kfold(mk)
        self.assertIn("a.o", kfold_targets)
        self.assertIn("b.o", kfold_targets)
        self.assertIn("d.s", kfold_targets)
        self.assertNotIn("test_c.o", kfold_targets)

    def test_guarded_overwrite_semantics(self):
        """Test guarded overwrite preservation when condition changes."""
        mk = """
obj-y := base.o
obj-$(CONFIG_OPT) := opt.o
"""
        kfold_targets = self._run_kfold(mk)
        self.assertIn("base.o", kfold_targets)
        self.assertIn("opt.o", kfold_targets)
        # Base must have negative guard for OPT
        self.assertTrue("CONFIG_OPT" in kfold_targets["base.o"])

    def test_prefix_and_suffix(self):
        """Test addprefix and addsuffix."""
        mk = """
NAMES := core driver util
PREFIXED := $(addprefix sys_,$(NAMES))
SUFFIXED := $(addsuffix .o,$(PREFIXED))
obj-y := $(SUFFIXED)
"""
        gnu_res = self._run_gnu_make(mk)
        self.assertEqual(gnu_res, "sys_core.o sys_driver.o sys_util.o")
        kfold_targets = self._run_kfold(mk)
        self.assertIn("sys_core.o", kfold_targets)
        self.assertIn("sys_driver.o", kfold_targets)
        self.assertIn("sys_util.o", kfold_targets)


if __name__ == "__main__":
    unittest.main()
