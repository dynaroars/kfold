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

- final.sh finished (Kmax, scaling, why, blindspots). /tmp/skbuild_* cleaned.
- tests: 127 pass with KFOLD_CACHE=work/kfold-cache; test_verify relaxed to
  accept "proved" as well as "identical" (disjunct order is unstable).
- paper_numbers.py: macros for blind-spot categories, Kmax memory/unexpanded
  and the kfold kind of Kmax's misses, why failure kinds, config-for
  breakdown, Kconfig check, scaling min/max; timing/subjects table fixes.
- paper/kfold.tex: evaluation rewritten on the macros (4 RQs as in the
  outline; GNU Make RQ dropped -- no canonical rerun of it); abstract,
  intro, implementation (new "Developer commands"), discussion, related
  work, conclusion, reproduction map updated; vDSO/mmp examples updated to
  7.2.8. Still 20 pages.

- Kconfig encoding (tools/kconfig_solver.py): an option can be on only
  through select/imply/visible prompt/active default; tristate <, <=, >, >=
  modeled; parse from a temp dir (the read-only prepared tree made every
  $(cc-option) probe fail). check_kconfig.py now also checks that each real
  .config satisfies the encoding: 0 violations on all five.
- devtasks compile deletes target objects first (an object the defconfig
  build already had was counted as not compiled).
- Final devtasks: config-for 384/402 selectable, 12 unmapped, 6 impossible
  (all need another architecture), 0 lost options; compile 40/40; why
  400/400. Tests: 130 pass.

- 2026-09-26 evening: $(eval) support (src/expansion.py do_fun_Eval,
  _eval_texts/_call_texts; src/symexe.py EmptyDirective executes the
  evaluated text in dexe and sexe). $(eval $(call F,...)) substitutes only
  F's parameters, as GNU call does (expanding a many-line body as one
  string blew coreboot up to 26 GB). Rule closure also starts from
  non-object always-/extra- targets (kernel/trace undefsyms_base.o).
  why: fixed Choice.prompts crash. Full kfold-side rerun (work/rerun4.sh,
  12 GB ulimit): Linux 0 FP / 0 in-set misses and every compiled object
  outside U is a host tool (overlap without host tools 100% on all four);
  coreboot 477 predicted, 0 FP.
- paper/OUTLINE.tex is the main file (user, 2026-09-26): now uses
  numbers.tex and the generated tables; evaluation ported from kfold.tex;
  overview config-for example is stable commit 82699d1b727b. "Exact"
  dropped from kfold.tex's title.

## To do next
1. Possible kfold work: host tools (scripts/, tools/) via the top-level
   Makefile's rules; coreboot mainboard entry settings.
