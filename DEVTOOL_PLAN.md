# kfold for Linux developers — plan

Goal: turn kfold from paper tooling into a CLI a kernel developer would use
weekly. Every command answers one developer question, runs on a cached
analysis of the tree, and is checked against real Kconfig/make behavior.

Ground rules for all phases
- The working tree has many uncommitted user changes: do not commit, stash,
  reset, or edit files outside the ones listed for your phase.
- New code lives in `src/cli/`; each subcommand is one module in
  `src/cli/commands/` exposing `register(subparsers)` (auto-discovered, so
  parallel phases never edit a shared file).
- Reuse `src/objects.py` (`object_conditions`, `predicted_objects`,
  `config_values`) and `tools/kconfig_solver.py` (`KconfigSMT`) rather than
  re-implementing.
- Test tree: `results/workspaces/linux` (v6.6). Tests go in `tests/test_cli_*.py`.

## Phase 1 — Foundation (sequential)
- [x] 1.1 `pyproject.toml` with a `kfold` console entry point; `pip install -e .` works
- [x] 1.2 `src/cli/main.py`: argparse dispatcher that auto-discovers `src/cli/commands/*.py`
- [x] 1.3 `src/cli/cache.py`: analyze a tree once, persist conditions / kinds / origins
      (Z3 serialized as SMT-LIB), keyed by tree digest + kfold version; load in <1 s
- [x] 1.4 `kfold analyze <tree>` and `kfold query <obj> [--config .config] [--json]`
- [x] 1.5 Tests on `tests/paper_example` + a Linux smoke test
- **Checkpoint 1:** `kfold analyze results/workspaces/linux` builds the cache;
  `kfold query fs/ext2/xattr.o` answers from cache in <1 s; conditions loaded
  from cache are Z3-equivalent to fresh ones; all tests pass.

## Phase 2 — Developer commands (parallel, disjoint files)
### 2A `kfold why <obj> --config .config` — "why isn't my file built?"
- [x] Chain of guards (directory reachability + obj-/lib- line) with Makefile:line
- [x] Mark each conjunct ✓/✗ under the config; name the failing symbols
- [x] For failing symbols, explain via Kconfig (`depends on`, `select`, choice) why they are off
      and what else must change to turn them on
- **Checkpoint 2A:** on ≥10 objects across tinyconfig/defconfig, the built/not-built
  verdict matches the real archived build, and the suggested symbol changes, after
  `make olddefconfig`, actually enable the object.

### 2B `kfold config-for <patch|files...>` — "how do I compile-test this?"
- [x] Accept a `git diff`/patch file or paths; map `.c`/`.S` → objects (incl. composite members)
- [x] Solve Φ_Kbuild ∧ Φ_Kconfig with a small / defconfig-close assignment; emit a `.config` fragment
- [x] Verify: `make olddefconfig` keeps the needed symbols; report any object that can't be enabled and why
- **Checkpoint 2B:** for ≥10 historical patches from the v6.6 tree's git log (or synthetic
  multi-file sets), the generated config survives olddefconfig and kfold predicts every
  touched object is built; spot-check ≥3 with a real `make <path>.o`.

### 2C `kfold lint [--diff PATCH]` — checkpatch for Makefiles/Kconfig
- [ ] Zombie symbols: `CONFIG_X` in Makefiles with no Kconfig definition
- [ ] Orphan sources: `.c` files referenced by no Makefile
- [ ] Dead objects: Φ_Kbuild ∧ Φ_Kconfig unsatisfiable
- [ ] `--diff`: before/after condition change for each object a patch touches
- **Checkpoint 2C:** whole-tree run on v6.6 writes `evidence/lint_v6.6.json`; each finding
  class has ≥5 manually verified true positives, false positives are listed with the cause.

### 2D `kfold blindspots [--configs ...]` — untested code by maintainer
- [x] Parse `MAINTAINERS` F:/X: patterns; group objects per subsystem
- [x] Objects never built by allmodconfig / allyesconfig / defconfig (on x86)
- **Checkpoint 2D:** report on v6.6 in `evidence/blindspots_v6.6.json`; top findings
  verified against `make allmodconfig` output (or an archived build).

## Phase 3 — Reach (sequential, later)
- [ ] 3.1 Multi-arch: arm64 and riscv analysis (ARCH-dependent conditions, `arch/$(SRCARCH)`)
- [ ] 3.2 Editor: generate compile_commands entries / suggest configs for unindexed files
- **Checkpoint 3:** arm64 predictions validated against one real arm64 build.

## Phase 4 — Upstream validation (user action)
- [ ] 4.1 Turn verified 2C/2D findings into patches (drafted by agents, reviewed by user)
- [ ] 4.2 User sends to linux-kbuild / subsystem lists (not done by agents)

## Status log
- 2026-09-25 Checkpoint 1 PASSED: Linux cache 29,245 objects (93 s build), query 0.32 s, all conditions Z3-equivalent to fresh run, 56/56 tests pass. Use `PYTHONPATH=src python3 -m cli` or `pip install -e .`; API documented in src/cli/commands/__init__.py, common.py, cache.py.
- 2026-09-25 Checkpoint 2D PASSED: 3,242/29,245 objects (11.1%) are blind spots under x86_64 allmod/allyes/defconfig across 493 MAINTAINERS entries; 50/50 sampled verdicts agree with archived builds. Follow-ups: allyesconfig lives only in /tmp/kfold-blind (not durable); X86_32-only and ARM-only (via Kconfig `if ARCH_*` menus) objects land in 'other' instead of 'arch' — needs KconfigSMT per blocking symbol; multi-symbol conditions (732) unexplained.
- 2026-09-25 Checkpoint 2A PASSED: 28/28 built/not-built verdicts match archived defconfig/tinyconfig_i386 builds; for 6 not-built defconfig objects the suggested changes survive olddefconfig unchanged and enable the object (2 compiled for real). Fixed after review: parent-Makefile line lookup matched comments and `hfs` in `hfsplus/`, and the location label named the child Makefile. Follow-ups: `KconfigSMT.get_constraints` treats only =y as active (why works around it locally); add public `Analysis.truth(expr, config)`; kconfiglib load once failed transiently under load ('assembler is not supported').
- 2026-09-25 Checkpoint 2B PASSED: 16 file sets over 15 subsystems + 3 patch files; all generated configs survive olddefconfig with 0 lost symbols and kfold predicts every touched object built; 6/6 real compiles succeed; mutually exclusive objects (entry_32/entry_64) are reported with the conflict. ~2 s per call (kconfiglib parse). --verify scratch copy lives in ~/.cache/kfold-configfor (1.5 GB). Follow-ups: Kconfig cone ignores `select` fan-in for speed; three commands each work around KconfigSMT's y-only/bool-m issues — fix once in tools/kconfig_solver.py and share a per-symbol clause index (from lint) / cone builder (from config-for).
- 2026-09-25 Shared Kconfig solver fixed (d61cc5d): tristate pair encoding in tools/kconfig_solver.py; all 6 real x86 configs satisfy it. why/config-for switched to it; why suggestions now list only hand-set symbols (8/8 survive olddefconfig and build); config-for --verify reuses one copy. lint switch pending with 2C.
