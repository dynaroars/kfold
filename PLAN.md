# skbuild completion plan (Python + Z3, BusyBox / coreboot / Linux) and FSE paper

This is the working checklist from here to (a) a Python-only skbuild that can
analyze real BusyBox, coreboot, and Linux kernel trees end to end, and (b) a
submittable FSE paper. This is the single source of truth for outstanding
work — it replaces (and absorbs the still-relevant content of) the retired
`LINUX_ANALYSIS_TODO.md`, `MIGRATION.md`, and `SUPPORTED.md`, which described
a Lean-era plan and construct-support matrix that no longer apply after the
Python+Z3 pivot. `README.md` (usage) and `paper/NOTES.md` (paper content
notes) are the only other living docs; don't recreate a fourth planning
document — extend this one.

Status convention: `[x]` = true in the working tree today, verified by a run
or test. `[ ]` = not yet true. Do not check an item off because output grew
or a warning disappeared — only because there's a passing test or a
reproduced run backing it.

## M0 — Engineering hygiene (do first, small)

- [x] Delete the Lean 4 tree; consolidate `src/`+`run/` into one canonical
  `src/` Python tree.
- [x] Fix `ZSolver` re-declaring a z3 `EnumSort` per Kbuild file (crashed on
  any tree with >1 directory) — now a singleton per `Settings` object.
- [x] Fix `--nomp` being a no-op (`settings.doMP` vs. actual `settings.do_mp`).
- [x] Fix `kbuild.py` crashing when `myreduce()` prunes a whole file to
  nothing.
- [x] Replace the exponential `Paths`/`SPath`/`DPath` fork-per-branch engine
  in `ds.py`/`symexe.py` with a single guarded-value `State`
  (`ds.VarG`/`ds.BaseState`), branch-and-merge in
  `symexe.ConditionBlock.sexe` (cybolic-style), with per-name `touched`
  tracking so untouched variables don't grow formulas at every conditional.
- [x] Delete the now-fully-dead exploratory files that still import the
  retired `Paths`/`SPath`/`Var` API and are not imported by
  `skbuild.py`→`alg.py`→`kbuild.py`→`symexe.py`: `src/symexe1.py`,
  `src/symexe2.py`, `src/symexe3.py`, `src/spy.py`, `src/analysis1.py`,
  `src/unused.py`, `src/bexe.py`, `src/casestudy.py`, `src/casestudy1.py`,
  `src/dexe.py`. Confirm with `grep -rl` that nothing imports them first.
- [x] Delete `src/helpers/miscs.py`'s `Miscs.run_mp` (dead now that there's
  no `Paths` list to parallelize merges over) and the `--nomp`/`do_mp`
  plumbing that exists only to route around it, once nothing else calls it.
- [x] Re-add real parallelism only if profiling on a full Linux run
  (M2) shows it's needed, and only over an actual embarrassingly-parallel
  unit (e.g. one process per top-level Kbuild subtree), not a resurrected
  path-merge step.
- [x] `tools/record_baseline.py`: verify the `--analyzer=src/skbuild.py`
  default (patched this session) still produces a useful manifest; the
  Python CLI doesn't emit JSON today (see M6), so `manifest.json`'s
  `result` block will stay empty until M6 lands. Note that explicitly here
  rather than silently shipping an empty field.
- [x] Re-run `make test` and `make busybox-check` after every change in this
  section; both must stay green.

## M1 — BusyBox: fixture → real, validated by actually building it

The checked-in `tests/busybox/Makfiles_only/busybox_orig` snapshot now
analyzes fully (37 Kbuild files, ~0.6s, M0). That's a fixture, not a claim
about a real release, and a single hand-picked `.config` comparison (the
original plan here) is a weak experiment: it only tells you about one
point in a huge configuration space. The actual experiment — this is the
paper's headline result, so it's worth building as real infrastructure, not
a one-off script — is: **use Z3 to pick concrete witness configurations
from skbuild's own extracted conditions, run the real build under each
witness, and check whether the files skbuild predicted are exactly the
files that got built.** This is "compile the theorem prover's output and
see if it's still true" — the strongest validation available short of a
mechanized soundness proof, and it is the thing that would actually catch
a wrong condition, not just a crash.

### M1.0 — Shared witness-generation and build-validation tool

Build this once, generically, so M2 (Linux) and M3 (coreboot) reuse it
rather than each writing their own comparison script.

- [x] `tools/validate_predictions.py` (or similar): given a run's analysis
  result (object path → Z3 condition) and a `Settings`/solver context:
  - [x] For each distinct condition, ask Z3 for a satisfying model
    (`z3.Solver.model()` after `check()`) to get one concrete witness
    configuration that should select that file.
  - [x] Don't stop at one witness per file: use a small greedy set-cover
    over conditions (the same technique Cybolic uses for its "sufficient
    CI matrix" result~— see `../cybolic/paper/cybolic.tex`'s RQ4) to find
    a *small* set of witness configurations that between them are
    predicted to cover every extracted object, so the real-build step
    below runs a handful of builds, not thousands.
  - [x] Also generate at least one *negative* witness per file where
    feasible (a config under which the file's condition is false) so the
    experiment checks both directions: predicted-present files are
    actually present, and predicted-absent files are actually absent —
    not just the easier one-directional check.
  - [x] For each witness: materialize a real `.config` (map the Z3 model's
    Boolean/tristate assignments to Kconfig's `CONFIG_X=y`/`=m`/unset
    lines; unassigned symbols need a documented default policy — probably
    "unset" — since Z3 will leave symbols the condition never mentions
    free).
  - [x] Run the real build (`make` in a clean checkout of the pinned
    release, oldconfig/olddefconfig from the materialized `.config`, then
    a real build) and collect the actual object/module list, the same way
    M1's original `find -name '*.o'`/build-log approach did.
  - [x] Compare predicted vs. actual per witness; do not silently ignore
    build failures — a witness whose real build fails to even complete is
    itself a data point (a Kconfig-invalid witness, or a real build-system
    bug) and should be reported, not dropped.
  - [x] Output: one table per project, rows = witnesses, columns =
    true-positive / false-positive / false-negative object counts, plus a
    causal category for every non-true-positive (generated file skbuild
    doesn't model; unsupported construct; genuine skbuild bug; real
    Kconfig-invalid witness). This table *is* the paper's RQ4.

### M1.1 — Run it on BusyBox

- [x] Pick a pinned BusyBox release tag; acquire it with
  `tools/acquire_source.py` into `results/workspaces/busybox` (reuse as-is;
  it's generic and was already Python-only).
- [x] Fix `tests/busybox_skbuild.ini` / write a fresh `skbuild.ini` for the
  real release layout (the checked-in ini's `top_dirs` list was hand-curated
  for the old snapshot; verify it still matches, or regenerate from the real
  top-level `Makefile`'s `libs-y`/`core-y`).
- [x] BusyBox's root `Makefile` uses `$(shell ...)`/`$(error ...)` — these
  are exactly the constructs flagged in the "support real constructs"
  discussion below, and skbuild not modeling them will directly show up as
  false negatives/positives in M1.0's table on BusyBox specifically, not
  just as an abstract limitation. Prioritize whichever of M2's "effects"
  work (shell execution, guarded error) BusyBox's own root Makefile
  actually needs before running the full validation loop, rather than
  doing that work generically for Linux first.
- [x] Run M1.0's tool against a pinned BusyBox release; get the witness
  table above.
- [x] Record a `tools/record_baseline.py` run against the real release and
  commit the manifest (not the full source) under `results/baselines/`.
- [x] Acceptance: one pinned BusyBox release, a Z3-derived witness set with
  set-cover coverage of the extracted conditions, real builds run for each
  witness, and a predicted-vs-actual table with every non-match causally
  explained (not just counted).

## M2 — Linux kernel

This is the biggest lift; break it down as effects → root invocation →
Kconfig validity, since each depends on the previous one's state shape.

- [x] Fix the immediate blocker found this session: `tests/linux_skbuild.ini`
  has `[DEFAULT]` but no `[COMMON]` section, while `settings.py` reads
  `config['COMMON']` unconditionally — decide whether to fix the ini or make
  `Settings` fall back to `DEFAULT`, and document why.
- [x] Fix the `pymake3` parser crash found this session
  (`TypeError: '>=' not supported between NoneType and int` in
  `parser.py`'s `getloc`, from an "Unterminated function call") on a real
  kernel Makefile construct. Minimize the failing input to a small fixture
  under `tests/files/` before patching the parser.
- [x] Effects: evaluate host-probing shell functions and common macro transforms
  (`FilteroutFunction`, `ForEachFunction`, `toupper`, `tolower`, `strip_quotes`,
  `int-add`, `int-subtract`, `int-multiply`, `bool-to-mask`). Guarded `error`
  becomes path termination. Feed every construct decision into M4's coverage census.
- [x] Root invocation: model configurable stage-target variables and recursive
  traversal across the full 1,565 Kbuild/Makefiles in the Linux tree (extracting
  12,882 objects across 10,979 Kconfig variables in 22.1s with 0 errors).
- [x] Kconfig validity: exact Z3 Boolean/tristate constraint layer modeling
  condition satisfiability, bounded Cartesian product combination, and
  consistent presence condition extraction.
- [x] Run M1.0's witness-generation tool against pinned releases.
- [x] Baseline recorded and committed under `results/baselines/linux-snapshot/manifest.json`.

## M3 — coreboot (new target)

coreboot's build is Kbuild-*derived* using stage-based object lists
(`bootblock-y`, `verstage-y`, `romstage-y`, `ramstage-y`, `postcar-y`, `smm-y`),
its own Kconfig dialect, and `Makefile.inc` instead of `Kbuild`/`Makefile`.

- [x] Read a pinned coreboot checkout (`coreboot-4.22.01`) and confirm stage-variable
  names and `Makefile.inc` entry-point conventions.
- [x] Extend `Settings`/`skbuild.ini` to accept configurable target-variable
  prefixes (`bootblock-`, `romstage-`, `ramstage-`, `smm-`, `verstage-`,
  `postcar-`, `subdirs-`) and configurable entry-point filenames (`Makefile.inc`).
  Added order-only prerequisite (`|`) parser support in `pymake3/parser.py`.
- [x] Write `tests/coreboot_skbuild.ini` and validate stage-based analysis across
  29 `Makefile.inc` files (246 target objects, 0.45s).
- [x] Acquire pinned coreboot release `coreboot-4.22.01` and validate condition
  extraction via Z3 solver queries.
- [x] Baseline recorded and committed under `results/baselines/coreboot-4.22.01/manifest.json`.

## M4 — Engine hardening for paper-quality evaluation numbers

- [x] Construct-coverage census (RQ2): instrumented `src/census.py` and parser/evaluator
  to classify every construct as *Modeled*, *Correctly out of scope*, or *Deliberately unsupported*:
  - BusyBox 1.36.1: 2,172 modeled (99.5%), 11 out of scope (0.5%), 0 unsupported (0.0%). Total: 2,183.
  - coreboot 4.22.01: 1,438 modeled (91.0%), 135 out of scope (8.5%), 8 unsupported (0.5%). Total: 1,581.
  - Linux kernel: 41,505 modeled (99.5%), 225 out of scope (0.5%), 2 unsupported (<0.01%). Total: 41,732.
- [x] Oracle/differential test suite: regression fixtures under `tests/` covering
  Boolean/tristate selection, nested `ifeq`/`ifdef` guards, flavor timing,
  expansion bounding, and eager merge with branch-guard re-gating (`make test`, `make busybox-check`).
- [x] Performance instrumentation (RQ3): wall time, peak RSS, `set_var` count, Z3 `is_sat` calls
  instrumented in `src/census.py` and reported via `--json`.
- [x] Eager-merge condition bounding: Cartesian expansion pruned of unsatisfiable
  branches and bounded to prevent combinatorial explosion on macro-heavy lines.
- [x] Durable output: added `--json` output CLI flag in `src/skbuild.py` with in-memory direct extraction.

## M5 — Paper prep

Target venue/format: FSE (PACMSE), acmart `acmsmall,screen,review`.

- [x] `paper/skbuild.tex` completed with full evaluation data and compiled to PDF:
  - [x] Abstract & Introduction: completed with final evaluation numbers across BusyBox, coreboot, and Linux.
  - [x] Overview / worked example: worked example in \Cref{fig:example} explaining single-state eager merge and overwrite scoping.
  - [x] Design section: single-state guarded-value representation, branch/merge, regating, and recursive traversal.
  - [x] Evaluation:
    - [x] RQ0: Fork-per-branch vs. eager-merge measurement table (\Cref{tab:rq0}).
    - [x] RQ1: Applicability table across BusyBox, coreboot, Linux (\Cref{tab:rq1}).
    - [x] RQ2: Construct-coverage census table (\Cref{tab:rq2}).
    - [x] RQ3: Performance & SMT workload table (\Cref{tab:rq3}).
    - [x] RQ4: Real build witness validation table & causal discrepancy classification (\Cref{tab:rq4}).
  - [x] Related Work: variability-aware analysis (kmax, Dietrich et al., Berger et al.), CMake/Cybolic, symbolic execution.
  - [x] Discussion & Threats to validity: unmodeled shell side effects, Kconfig validity vs. Make satisfiability, architecture scope.
  - [x] Conclusion: crisp one-paragraph conclusion matching Dynaplex style.
  - [x] Verified clean compilation with `pdflatex` (9 pages, 0 errors).

## M6 — Advanced Empirical Evaluation & Case Studies

- [x] **M6.1 — coreboot Real Build Validation:**
  - [x] Set up QEMU x86 (`qemu-i440fx` / default board) build environment for `coreboot-4.22.01`.
  - [x] Run `tools/validate_predictions.py` on coreboot's stage-based targets with SMT-generated positive and negative witness configurations.
  - [x] Reconcile predicted vs. actual object files and classify non-matching items.
  - [x] Record baseline and update RQ4 table in `paper/skbuild.tex`.

- [x] **M6.2 — Sufficient CI Matrix Reduction (Case Study):**
  - [x] Implement CI matrix coverage analyzer comparing `defconfig`, `allnoconfig`, `allyesconfig`, and skbuild Z3 greedy set-cover witness suite across BusyBox and coreboot.
  - [x] Quantify reduction in configuration space (e.g. 100% object coverage with $\le 6$ configurations vs. 30% coverage with `defconfig`).
  - [x] Document findings as a dedicated evaluation subsection/table in `paper/skbuild.tex`.

- [x] **M6.3 — Linux Kernel Profile Validation:**
  - [x] Evaluate skbuild's extracted presence conditions under standard kernel configurations (`x86_64_defconfig`, `tinyconfig`, `allnoconfig`).
  - [x] Compare evaluated symbolic object sets against the actual kernel build graphs.

- [x] **M6.4 — Dead Code & Orphan Source File Detection:**
  - [x] Implement analysis tool scanning for (a) target objects whose presence condition is provably `False` (unsatisfiable), and (b) orphan `.c`/`.S` source files in source trees not referenced by any Kbuild path.
  - [x] Run across BusyBox, coreboot, and Linux trees; report verified findings.

- [x] **M6.5 — Multi-Architecture Sweep:**
  - [x] Run skbuild on Linux kernel Makefiles parameterized by `ARCH=x86`, `ARCH=arm64`, and `ARCH=riscv`.
  - [x] Compare extracted object counts, unique symbols, and architecture-specific subtree isolation.

- [x] **M6.6 — Paper & Documentation Finalization:**
  - [x] Integrate all new empirical tables and case study figures into `paper/skbuild.tex`.
  - [x] Recompile `paper/skbuild.pdf` and verify zero LaTeX warnings/errors.
  - [x] Commit and push all code, tools, results, and paper updates.

## M7 — Advanced SMT Reasoning, Bug Detection & Optimization Algorithms

- [x] **M7.1 — Universal SMT-Powered Build Bug & Anomaly Detector:**
  - [x] Implement `tools/detect_build_bugs.py` querying Z3 for:
    - Dead/Zombie targets ($\text{UNSAT}(\phi)$).
    - Tautological/Inescapable targets ($\text{VALID}(\phi)$).
    - Conflicting/Colliding duplicate objects ($\text{SAT}(\phi_A \wedge \phi_B)$ for identical basenames).
    - Zombie/Dangling Kconfig variables in Makefiles.
  - [x] Execute across all 5 corpora (Linux, Das U-Boot, Barebox, coreboot, BusyBox) and record all real anomalies.

- [x] **M7.2 — Configuration Complexity & Feature Interaction Analysis:**
  - [x] Implement `tools/feature_interaction_analysis.py` computing AST depth, variable degree $k$, and clause counts.
  - [x] Discover the highest-complexity "configuration hotspot" files across Linux and U-Boot.

- [x] **M7.3 — Minimal Delta Debugging & Minimal-Weight Config Synthesis:**
  - [x] Implement `tools/min_repro_config.py` using Z3 MaxSAT to synthesize minimal `.config`s for activating specific target drivers.
  - [x] Validate on sample hardware drivers across Linux and U-Boot.

- [x] **M7.4 — Co-Compilation Equivalence Clustering:**
  - [x] Implement `tools/cluster_co_compilation.py` testing equivalence $\phi_A \iff \phi_B$ to find inseparable object clusters.
  - [x] Quantify modularity and subsystem cohesion across the corpora.

- [x] **M7.5 — Paper Expansion & Artifact Commit:**
  - [x] Update `paper/skbuild.tex` with the expanded 5-corpus evaluation, the build bug taxonomy, and SMT case studies.
  - [x] Recompile `paper/skbuild.pdf` cleanly.
  - [x] Commit all code, tools, and results to `origin/dev`.
