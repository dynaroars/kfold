# kfold (skbuild) Master Plan & Milestone Roadmap

This document is the authoritative plan and task tracker for **kfold** (variability-aware Kbuild analyzer) and its submission to **ICSE/FSE**.

---

## Complete Milestone History (M0 — M8)

### M0 — Make it correct (Core Engine Migration)
Goal: bring the core symbolic execution of a single `Makefile` up to a clean, well-tested baseline with single-state eager merge before scaling to whole trees.

- [x] **M0.1 — Python tree consolidation & hygiene:**
  - Migrated parser codebase to `pymake3` / Python 3.14 AST compatibility.
  - Eliminated legacy Python 2 idioms and obsolete sub-packages.
  - Pinned singletons for Z3 AST solver (`helpers/zsolver.py`).
- [x] **M0.2 — Elimination of Path-Forking (`SPath` / `DPath`):**
  - Replaced exponential path copying with single-state guarded-value representation (`ds.VarG`, `ds.BaseState`).
  - Implemented eager condition merging in `symexe.ConditionBlock.sexe` by evaluating branch conditions, collecting branch deltas, and re-gating mutated variables under the branch condition disjunction.
- [x] **M0.3 — Flavor & Assignment Timing Semantics:**
  - Implemented immediate (`:=`) vs deferred (`=`) assignment semantics.
  - Handled multi-word variable expansions and batch assignments via `set_var_dict`.
  - Added recursive string expansion with sound pattern matching (`Filter`, `Filterout`, `Patsubst`, `Addprefix`, `Addsuffix`).

---

### M1 — BusyBox Real-Tree End-to-End
Goal: whole-tree extraction and real-build agreement on BusyBox 1.36.1.

- [x] **M1.1 — Whole-Tree Traversal & Settings Handling:**
  - Integrated recursive directory traversal driven by `obj-y` / `obj-m` subdirectories.
  - Modeled BusyBox Kbuild patterns and configuration symbol prefixes (`CONFIG_`).
- [x] **M1.2 — Z3 Witness Generation & Real-Build Validation:**
  - Implemented greedy set-cover configuration generator (`src/analysis.py` / `tools/validate_linux_configs.py`) to synthesize minimal test configurations covering all extracted targets.
  - Ran live compilation validation on BusyBox (603/609 objects matching, 99.0% precision).
  - Categorized root Makefile discrepancy: 6 top-level glue objects (`applets/applets.o`, `arch/...`) governed by direct rule recipes rather than standard `obj-y` accumulation.

---

### M2 — coreboot Real-Tree End-to-End
Goal: whole-tree extraction and build validation on coreboot 4.22.01.

- [x] **M2.1 — Multi-Stage Target Handling:**
  - Generalized `Settings` and target file collection to track coreboot execution stages: `bootblock-y`, `romstage-y`, `postcar-y`, `verstage-y`, `ramstage-y`, and `smm-y`.
  - Extracted 246 target objects across 29 `Makefile.inc` files in 1.45 seconds.
- [x] **M2.2 — Live QEMU / Coreboot Validation:**
  - Executed compiler builds on coreboot x86 QEMU target (`results/sandbox_build_validations.json`): 188 TP, 4 FP, 0 FN (97.9% precision, 100% recall).
  - Identified FP cause: payload stub targets conditionally overridden by top-level board architecture defaults.

---

### M3 — Linux Kernel Real-Tree End-to-End
Goal: scale kfold to the upstream Linux kernel source tree.

- [x] **M3.1 — Full Tree Parsing & Symbolic Execution:**
  - Parsed 1,565 Makefiles across `arch/x86`, `drivers/`, `fs/`, `net/`, `kernel/`, `sound/`, `mm/`, `lib/`, `crypto/`, `security/`, and `block/`.
  - Analyzed 11,291 target objects across 10,979 Kconfig variables in 32.8 seconds.
- [x] **M3.2 — Parser Robustness & Fallback Handling:**
  - Fixed parser getloc NoneType exceptions on unterminated macro functions.
  - Added fallback between `[DEFAULT]` and `[COMMON]` ini sections in `src/settings.py`.
  - Implemented eager merge bounding to prevent combinatorial explosion on deeply nested conditional blocks.

---

### M4 — Engine Hardening, Instrumentation & Construct Census
Goal: instrument the evaluation pipeline and measure real construct usage across benchmarks.

- [x] **M4.1 — Construct-Coverage Census (RQ2):**
  - Classified every encountered construct into *Modeled*, *Correctly out of scope*, or *Deliberately unsupported* across 59,345 construct instances:
    - BusyBox 1.36.1: 2,172 modeled (99.5%), 11 out of scope (0.5%), 0 unsupported. Total: 2,183.
    - coreboot 4.22.01: 1,438 modeled (91.0%), 135 out of scope (8.5%), 8 unsupported (0.5%). Total: 1,581.
    - Linux kernel: 41,505 modeled (99.5%), 225 out of scope (0.5%), 2 unsupported (<0.01%). Total: 41,732.
- [x] **M4.2 — Performance Profiling (RQ3):**
  - Instrumented wall-clock time, peak RSS, `set_var` counts, and Z3 solver calls.
  - Validated that single-state eager merge keeps peak memory under 285 MB for Linux and under 80 MB for other corpora.
- [x] **M4.3 — Durable Output & Automation Pipeline:**
  - Implemented `--json` extraction in `src/skbuild.py` and direct programmatic queries via `src/analysis.py`.

---

### M5 — Multi-Corpus Evaluation & Downstream Explorations
Goal: extend kfold across 5 diverse C/Kbuild systems and prototype downstream engineering applications.

- [x] **M5.1 — Multi-Corpus Benchmark Scaling:**
  - Scaled analysis to 5 corpora: Linux kernel, coreboot, BusyBox, Das U-Boot, and Barebox.
  - Extracted 26,000+ total compilation targets across 3,500+ Makefiles.
- [x] **M5.2 — Downstream Application 1 (CI Configuration Synthesis):**
  - Formulated greedy set-cover selection over Z3 presence condition models: covered $\ge 98.2\%$ of objects in $\le 27$ test builds.
- [x] **M5.3 — Downstream Application 2 (Cross-Release Build Evolution):**
  - Implemented SMT-based XOR diffing ($\text{SAT}(\Phi_{\text{v1}} \oplus \Phi_{\text{v2}})$) to detect semantic condition drift between releases on BusyBox and U-Boot.
- [x] **M5.4 — Downstream Application 3 (Build Defect Detection):**
  - Identified and verified 6 dead/unreachable PMU firmware build targets in Barebox 2024.01.0 `firmware/Makefile` caused by misspelled config guards.
- [x] **M5.5 — Artifact Organization:**
  - Pruned exploratory clustering and raw interaction histograms from the primary paper text into structured evaluation artifacts.

---

### M6 — Fork-per-Branch vs. Eager-Merge Empirical Comparison (RQ0)
Goal: empirically demonstrate that eager merge is necessary to analyze real-world Kbuild files without path explosion.

- [x] **M6.1 — Baseline Implementation:**
  - Maintained fork-per-branch execution baseline mirroring classic multi-path symbolic execution.
- [x] **M6.2 — Scalability Benchmark:**
  - Benchmarked scaling across branch counts $N \in [1, 20]$:
    - At $N=5$: Forking 0.05s vs Eager Merge 0.005s ($10\times$ speedup).
    - At $N=10$: Forking 3.12s vs Eager Merge 0.007s ($445\times$ speedup).
    - At $N=15$: Forking 71.3s vs Eager Merge 0.010s ($7{,}130\times$ speedup).
    - At $N=20$: Forking exceeded timeout / memory limit (>1,000,000 paths) while Eager Merge finished in 0.014s.

---

### M7 — coreboot Whole-Tree Symbolic Execution & Stage Tracking
Goal: rigorous evaluation of coreboot build semantics.

- [x] **M7.1 — Stage-Aware Condition Resolution:**
  - Extracted and tracked stage-specific object conditions across boot phases.
- [x] **M7.2 — Differential Conformance:**
  - Tested coreboot variable assignment behaviors and pattern expansions against GNU Make oracle.

---

### M8 — Linux Whole-Tree Symbolic Execution & Full Evaluation
Goal: complete empirical evaluation on Linux and paper draft.

- [x] **M8.1 — Full Linux Extraction:**
  - Analyzed complete x86 Linux source tree; extracted 11,291 object targets across 10,979 symbols.
- [x] **M8.2 — Paper Draft Compilation:**
  - Prepared `paper/skbuild.tex` with comprehensive tables for RQ0–RQ5, related work, and threats to validity.

---

## Active Revision Plan (ICSE/FSE Target)

```
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                                 REVISION ROADMAP                                       │
│                                                                                        │
│  [M9: Evidence Ledger] ───> [M10: Linux Multi-Config Build Validation]                │
│                                     │                                                  │
│                                     ▼                                                  │
│  [M11: Baselines & Ablations] ───> [M12: Construct Census & Semantic Suite]           │
│                                     │                                                  │
│                                     ▼                                                  │
│  [M13: Application Pruning]   ───> [M14: Table Sync & LaTeX Pipeline]                 │
│                                     │                                                  │
│                                     ▼                                                  │
│  [M15: Live GCC Triangulation] ──> [M16: Kmax Empirical Head-to-Head]                  │
│                                     │                                                  │
│                                     ▼                                                  │
│  [M17: Advanced Kbuild Modeling & Kmax-Inspired Enhancements]                          │
└────────────────────────────────────────────────────────────────────────────────────────┘
```

---

### M9 — Evidence Ledger, Experiment Manifest & Double-Blind Alignment

- [x] **M9.1 — Claims & Evidence Ledger:**
  - Created `evidence/claims.csv` linking 15 empirical claims to exact data files and evaluation scripts.
- [x] **M9.2 — Machine-Readable Experiment Manifest:**
  - Created `evidence/manifest.json` recording environment versions (Python 3.14.7, Z3 4.13.3, GNU Make 4.4.1, GCC 16.2.0), commit SHAs, and output hashes.
- [x] **M9.3 — Related Work Anonymization & Neutral Positioning:**
  - Re-positioned Nguyen & Nguyen (ICSME 2020) as prior work neutrally without indicating author continuity.
  - Verified and corrected citation metadata in `paper/skbuild.bib`.

---

### M10 — Comprehensive Ground-Truth Build Validation (Flagship Experiment)

- [x] **M10.1 — Multi-Configuration Linux Build Prediction Harness:**
  - Implemented `tools/validate_linux_configs.py` supporting arbitrary `.config` files (Debian host, Tinyconfig, Defconfig, Fedora, Allmodconfig).
- [x] **M10.2 — Fast Valuation Evaluation:**
  - Implemented fast native AST compilation (`compile_expr`), evaluating 11,291 targets across 10,988 symbols in 29–57 ms per configuration.
- [x] **M10.3 — Direct GNU Make Differential Ground-Truth Validator:**
  - Implemented `tools/compare_kfold_with_gnu_make.py` running GNU Make in parallel across all 1,565 Makefiles:
    - **Debian Default:** 4,331 TP, 298 FP, 161 FN (93.6% precision, 96.4% recall, 95.9% accuracy).
    - **Fedora Modular Server:** 10,137 TP, 436 FP, 433 FN (95.9% precision, 95.9% recall, 92.3% accuracy).
    - **Maximal (allmodconfig):** 10,539 TP, 483 FP, 109 FN (95.6% precision, 99.0% recall, 94.8% accuracy).
    - **Upstream x86_64 Defconfig:** 1,624 TP, 93 FP, 609 FN (94.6% precision, 72.7% recall, 93.8% accuracy).
    - **Minimal Tinyconfig:** 216 TP, 79 FP, 348 FN (73.2% precision, 38.3% recall, 96.2% accuracy).
  - Saved raw metrics in `results/linux_ground_truth_validation.json`.
- [x] **M10.4 — Live Compiler Ground-Truth Builds (Sandbox Corpora):**
  - Live compiler builds executed on BusyBox (603/609 objects agreeing, 99.0%), coreboot QEMU x86 (97.9% precision), and Barebox sandbox (94.7% precision) in `results/sandbox_build_validations.json`.
- [x] **M10.5 — Cross-Corpus Uniform Validation Table:**
  - Integrated full multi-corpus and multi-config Linux ground-truth metrics into Table 4 of `paper/skbuild.tex`.

---

### M11 — Baselines, Ablations & Adversarial Scalability Benchmarks

- [x] **M11.1 — Direct Baseline Comparison against Prior Art:**
  - Quantified eager merge vs. fork-per-branch execution ($7{,}130\times$ speedup at $N=15$).
- [x] **M11.2 — Eager-Merge Variable Assignment Semantics:**
  - Extended `src/ds.py` and `src/symexe.py` with `set_var_dict` to support multi-word variable expansions and branch overwrites.
- [x] **M11.3 — Adversarial Synthetic Benchmarks:**
  - Benchmarked sequential branches ($N \in [1, 30]$), nested conditionals ($D \in [1, 20]$), and guarded overwrites ($K \in [1, 25]$) in `tests/adversarial/run_adversarial_benchmarks.py`.

---

### M12 — Construct Census & Semantic Conformance Suite

- [x] **M12.1 — Refactored Construct Frequency Census:**
  - Re-framed construct reporting to *Observed Construct Frequency and Implemented Handling* across 59,345 construct instances (57,211 modeled, 14 unsupported [<0.03%]).
- [x] **M12.2 — Differential Conformance Test Suite:**
  - Created `tests/conformance/test_gnu_make_conformance.py` testing immediate/deferred flavors, pattern substitutions, filtering, prefixes/suffixes, and guarded overwrites against GNU Make (100% passing).

---

### M13 — Application Pruning & End-to-End Validation

- [x] **M13.1 — Downstream Application Selection (3 validated uses):**
  - **App 1 — CI Witness Synthesis:** Greedy set-cover CI matrix synthesis covering $\ge 98.2\%$ of objects with $\le 27$ configurations.
  - **App 2 — Cross-Release Build Evolution:** SMT XOR equivalence analysis on BusyBox (1.35 $\to$ 1.36) and U-Boot (2023.01 $\to$ 2024.01).
  - **App 3 — Reproducible Build Defects:** Discovered and verified 6 unreachable PMU firmware targets in Barebox 2024.01.0 `firmware/Makefile`.
- [x] **M13.2 — Prune Secondary Explorations:**
  - Pruned exploratory clustering and raw interaction histograms from the primary paper text into artifact documentation.

---

### M14 — Automated Table Synchronization & Verification Pipeline

- [x] **M14.1 — LaTeX Table Auto-Generator:**
  - Implemented `tools/generate_paper_tables.py` auto-generating `tab_corpus.tex` and `tab_build_validation.tex` directly from raw JSON result files.
- [x] **M14.2 — Automated Claims Consistency Linter:**
  - Implemented `tools/check_claim_consistency.py` validating numbers in `evidence/claims.csv` against raw result JSONs and paper text.
- [x] **M14.3 — Claim-Audit Pass (Forbidden Term Scanning):**
  - Built automated scanner in `tools/check_claim_consistency.py` ensuring zero occurrences of forbidden overclaiming terms (*"sound and complete"*, *"guarantees exactness"*, *"eliminates all overhead"*).

---

### M15 — Paper Revision & Deep Empirical Discussion

- [x] **M15.1 — SOS Calculus Replacement:**
  - Replaced formal SOS operational semantics in `paper/skbuild.tex` with intuitive, high-level design prose focusing on guarded words, eager merging, flavor timing, and branch overwrite preservation.
- [x] **M15.2 — Expanded Empirical Discussion:**
  - Enriched Section 6 (Evaluation) with detailed discussion and clear **"Implications"** paragraphs for RQ0–RQ5 answering what each empirical result means for software engineering practice.
- [x] **M15.3 — Ground-Truth Linux Multi-Config Integration:**
  - Incorporated full differential ground-truth numbers against GNU Make into Table 2, Table 4, and empirical narrative.
- [x] **M15.4 — Clean PDF Compilation:**
  - Compiled clean, warning-free PDF with `pdflatex` (21 pages, 0 errors).
- [x] **M15.5 — Live Linux Physical GCC Build Triangulation:**
  - Cloned full Linux kernel v6.6 tree and performed live GCC compiler builds (`tinyconfig` and `defconfig`).
  - Executed 3-way triangulation between Physical Compiler Builds (.o disk artifacts), GNU Make target expansion, and kfold SMT valuations.
  - Demonstrated $\ge 98.1\%$ recall against physical binary compilation artifacts, with full metrics recorded in `results/linux_physical_build_validation.json`, Table 5 in paper, and Claim C16 in `evidence/claims.csv`.

---

### M16 — Kmax Empirical Comparison & Preprocessing Capabilities

- [x] **M16.1 — Official Kmax (v4.10) Installation & Environment Integration:**
  - Installed latest stable `kmax 4.10` from PyPI into user environment (`/home/tnguyen/.local/bin/kmax`).
  - Validated single-makefile and batch directory analysis with `kmax -u -B`.
- [x] **M16.2 — Automated Multi-Corpus Head-to-Head Comparison:**
  - Implemented `tools/compare_kfold_with_kmax.py` running parallel multi-threaded comparison across all 5 benchmark corpora (BusyBox, Barebox, Das U-Boot, coreboot, Linux).
  - Saved raw comparison data to `results/kfold_vs_kmax_comparison.json`.
  - Validated 100% target extraction agreement on standard Kbuild (609 identical targets on BusyBox 1.36.1).
- [x] **M16.3 — Robust Text Preprocessing & Traversal Modes:**
  - Implemented multi-encoding clean reading (UTF-8 with Latin-1 fallback).
  - Handled comments preceding line-continuation backslashes (`\ # comment`) to prevent lexer aborts.
  - Added dual traversal modes in `src/alg.py` and `src/skbuild.py`: top-down hierarchical traversal and exhaustive recursive directory exploration (`--recursive` / `-r`).
- [x] **M16.4 — Paper Integration (Table 6 & Section 5 / RQ1):**
  - Added comparative Table 6 to `paper/skbuild.tex` detailing Makefiles analyzed, extracted targets, Kconfig symbols, and wall-clock times.
  - Added narrative explaining hierarchical condition propagation vs. unconstrained flat scraping, non-standard Kbuild dialect coverage (Barebox `pbl-y`, coreboot stages, U-Boot `SPL_TPL_`), and throughput speedup.
  - Verified 0 overclaiming violations with `tools/check_claim_consistency.py`.

---

### M17 — Advanced Kbuild Modeling & Kmax-Inspired Enhancements

Goal: adapt and implement key architectural ideas from Kmax to enhance `kfold`'s precision, dialect coverage, artifact classification, and linting capabilities—while replacing Kmax's brittle prototype heuristics (regex parsers, dynamic string synthesis, unencapsulated BDD state) with `kfold`'s native eager-merge symbolic execution.

- [x] **M17.1 — Native Composite Object Dependency Resolver (`foo-objs` / `foo-y` / `foo-m`):**
  - **Context & Design:** In Kbuild, targets in `obj-y`/`obj-m` can be composite module containers (`foo.o`) formed by linking constituent C compilation units defined in `foo-objs`, `foo-y`, or `foo-m`. Unlike Kmax (which dynamically synthesizes and re-parses makefile strings like `SPECIAL-composite-foo := $(foo-objs)` on the fly), `kfold` resolves composite bindings natively within `ds.SState` and `symexe.py`.
  - **Step 1:** Extend `ds.SState` and `symexe.py` to identify composite assignment variables (`<target>-objs`, `<target>-y`, `<target>-m`).
  - **Step 2:** Implement native fixed-point resolution: when target `<target>.o` is included under condition $\Phi_{\text{target}}$, propagate $\Phi_{\text{target}}$ down to each constituent unit:
    $$\Phi_{\text{constituent}} = \Phi_{\text{parent\_dir}} \wedge \Phi_{\text{target}} \wedge \Phi_{\text{subfeature}}$$
  - **Step 3:** Distinguish container objects (`foo.o`) from atomic compilation units (`foo_main.o`, `foo_hw.o`) to ensure exact 1-to-1 C source file mapping.
  - **Step 4:** Add test suite in `tests/test_composite_expansion.py` covering nested composites, multi-stage additions, and conditional sub-features across Linux `drivers/net/ethernet/` and Barebox (100% passing).

- [x] **M17.2 — Dialect-Aware Target Artifact Classification (`units_by_type`):**
  - **Context & Design:** Makefiles build both target device binaries and host-side build utilities. Conflating host utilities with target firmware inflates target counts and distorts presence condition analysis.
  - **Step 1:** Classify extracted symbols into rigorous semantic categories across build dialects:
    - `compilation_units`: cross-compiled object files (`.o`, `.a`) compiled for the target architecture (`obj-y`, `obj-m`).
    - `composite_units`: multi-object container modules linked from constituent compilation units.
    - `hostprog_units`: tools compiled for the *host* machine (`hostprogs-y`, `hostprogs-m`, `userprogs-y`), isolated from device firmware calculations.
    - `dialect_units`: stage- and mode-specific units (Barebox `pbl-y`/`obj-pbl-y`, coreboot `bootblock-y`/`romstage-y`/`ramstage-y`/`smm-y`, U-Boot `spl-y`/`tpl-y`).
    - `clean_files` / `extra_targets`: intermediate artifacts (`clean-files`, `targets`, `extra-y`, linker scripts).
    - `subdirs`: directories recursively traversed under inherited directory guards.
  - **Step 2:** Update `--json` CLI output and `src/analysis.py` to expose `units_by_type`.
  - **Step 3:** Add regression tests in `tests/test_artifact_classification.py` (100% passing).

- [x] **M17.3 — Tristate Built-in vs. Loadable Module Semantics (`=y` vs. `=m`):**
  - **Context & Design:** Kmax over-approximates tristates by minting free `=m` variables for all symbols (even pure booleans). `kfold` models tristates soundly without generating spurious SAT models.
  - **Step 1:** Extend `helpers/zsolver.py` with tristate symbol representation: represent tristate `CONFIG_X` as two mutually exclusive boolean predicates $(\mathtt{CONFIG\_X{=}y}, \mathtt{CONFIG\_X{=}m})$ with constraint $\neg(\mathtt{CONFIG\_X{=}y} \wedge \mathtt{CONFIG\_X{=}m})$. Do not mint `=m` variables for known boolean-only symbols.
  - **Step 2:** Model global `CONFIG_MODULES`: when `CONFIG_MODULES=n`, constrain all `=m` bindings to evaluate strictly to $\text{False}$.
  - **Step 3:** Differentiate resident kernel core objects (`vmlinux` $\leftrightarrow \mathtt{obj\text{-}y}$) from dynamically loadable modules (`.ko` $\leftrightarrow \mathtt{obj\text{-}m}$) in extracted presence conditions.
  - **Step 4:** Add CLI option `--tristate` / `-T` to allow toggling between fast boolean abstraction and full tristate module mode.
  - **Step 5:** Add regression suite in `tests/test_tristate_semantics.py` (100% passing).

- [x] **M17.4 — Automated Dead & Unconfigurable Target Linting (`skbuild --check-dead`):**
  - **Context & Design:** Static analysis of Kbuild can automatically detect dead code resulting from deprecated Kconfig symbols or contradictory conditional guards.
  - **Step 1:** Implement static analyzer in `tools/lint_dead_targets.py` combining syntactic and SMT checks:
    - **Syntactic Orphan Targets:** targets assigned to empty/unexpanded prefixes (`obj-`, `lib-`, `pbl-`) caused by removed/renamed Kconfig variables (`obj-$(CONFIG_DEAD) += dead.o` expanding to `obj- += dead.o`, which Kbuild silently ignores).
    - **Semantic Unsatisfiable Targets:** targets whose combined presence condition simplifies to $\text{False}$ ($\text{UNSAT}$) under Z3.
    - **Conflicting Hierarchical Guards:** targets whose local conditions contradict an ancestor directory's traversal condition ($\Phi_{\text{dir}} \wedge \Phi_{\text{target}} \implies \text{UNSAT}$).
  - **Step 2:** Add CLI flag `--check-dead` / `--lint` to `src/skbuild.py`.
  - **Step 3:** Run linter across benchmark corpora and document newly discovered build defects in `results/unconfigurable_targets.json`.
  - **Step 4:** Add reproduction test cases in `tests/test_dead_target_detection.py` (100% passing).

- [x] **M17.5 — Robust Kconfig Constraint Integration via `kconfiglib` (End-to-End Buildability):**
  - **Context & Design:** Kmax's `kclause` relies on a brittle 1,350+ line custom regex parser that fails on modern Kconfig preprocessor syntax (`$(cc-option)`, `$(success)`). `kfold` uses standard AST extraction via `kconfiglib` to extract propositional clauses.
  - **Step 1:** Implement `tools/kconfig_solver.py` integrating `kconfiglib` to capture `select`, `depends on`, `default ... if ...`, and `choice` constraints as SMT formulas ($\Phi_{\text{Kconfig}}$).
  - **Step 2:** Conjoin Kconfig propositional clauses with `kfold` presence conditions during greedy set-cover test configuration synthesis:
    $$\text{Find } \mathcal{M} \models \Phi_{\text{Kconfig}} \wedge \Phi_{\text{target}}$$
  - **Step 3:** Add test suite in `tests/test_kconfig_integration.py` verifying dependency propagation, reverse dependency resolution, choice block mutual exclusion, and `.config` synthesis (100% passing).
  - **Step 4:** Validated buildable witness synthesis with physical `.config` generation.
  - **Demoted from paper (2026-09-21):** the Kconfig-to-SMT constraint extraction idea is not novel (Kclause and other Kconfig-to-SAT tools have done this for over a decade); the code, tests, and unit-level validation remain in the repo, but the `CONFIG_E1000` case study (former claim C20) and all comparative language crediting this as a distinguishing contribution have been removed from `paper/skbuild.tex` and `evidence/claims.csv`. None of the paper's evaluated applications (CI witness synthesis, differential evolution, dead-target linting) incorporate Kconfig constraints; their synthesized configurations remain Kbuild-local only.


