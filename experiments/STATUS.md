# Redo status (2026-09-26)

Canonical rerun on Linux 7.2.8, BusyBox 1.38.0, Barebox 2026.09.0, U-Boot
2026.07, coreboot 26.06 (see README.md). Old results: results/legacy/,
evidence/legacy/ (untracked).

## Done
- All builds (results/builds.json, evidence/inventories/, evidence/configs/).
- Agreement + ablations, all subjects (results/agreement/). Linux: 0 FP, 0 FN
  on all four configs, overlap 97.0-99.5%.
- Timing on an idle machine (results/timing.json). Linux median 138.7 s
  (was 34 s on v6.6; the no_rules ablation takes 49 s, so the corrected rule
  closure in src/objects.py is the likely cost -- worth profiling).
- Kconfig model check (results/kconfig_check.json): 0 mismatches on
  tinyconfig/defconfig/debian/allyesconfig.

## In progress when the session ended
work/final.sh (nohup, log in work/final.log): Kmax on Linux ->
tools/bench_scaling.py -> devtasks why/compile/blindspots -> paper_numbers.py.
Check with: grep -v '^kmax -D' work/final.log | tail

## To do next
1. Re-run `experiments/devtasks.py config-for` then `devtasks.py compile`:
   the first config-for pass predates the widened-Kconfig-cone fix
   (21 commits falsely reported objects as impossible, e.g. drm/sched), so
   results/devtasks/config_for.json and the compile sample from final.sh are
   stale.
2. Re-run `experiments/check_kconfig.py` to confirm the imply and PYTHON3
   fixes: expected 1 residual allmodconfig mismatch (USB_ROLE_SWITCH: a
   select from a member of a bool choice whose dependency is m; kconfiglib
   evaluates the choice as y). Documented, not fixed.
3. Clean /tmp/skbuild_* created by final.sh's devtasks steps (the CLI
   analyze writes to /tmp unless SKBUILD_TMP is set; /tmp is RAM-backed).
4. `experiments/paper_numbers.py`, then rewrite the paper's evaluation to use
   paper/numbers.tex macros and paper/tables/*.tex (OUTLINE.tex first; also
   paper/kfold.tex). Update deviations and limitations from README.md
   ($(eval)-generated objects are the only non-host objects kfold misses on
   Linux; plus generated blobs and recipe-built objects).
5. Linux CLI tests: `KFOLD_CACHE=work/kfold-cache pytest tests` once the
   cache is current. tests/test_cli_cache.py::test_verify also fails on the
   committed code (disjunct order is unstable between analyses); decide
   whether to relax it.
6. Commit and push results/, evidence/ (inventories/configs only; no build
   trees), experiments/, tests/, src/ changes.
