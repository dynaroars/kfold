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
- [ ] 1.1 `pyproject.toml` with a `kfold` console entry point; `pip install -e .` works
- [ ] 1.2 `src/cli/main.py`: argparse dispatcher that auto-discovers `src/cli/commands/*.py`
- [ ] 1.3 `src/cli/cache.py`: analyze a tree once, persist conditions / kinds / origins
      (Z3 serialized as SMT-LIB), keyed by tree digest + kfold version; load in <1 s
- [ ] 1.4 `kfold analyze <tree>` and `kfold query <obj> [--config .config] [--json]`
- [ ] 1.5 Tests on `tests/paper_example` + a Linux smoke test
- **Checkpoint 1:** `kfold analyze results/workspaces/linux` builds the cache;
  `kfold query fs/ext2/xattr.o` answers from cache in <1 s; conditions loaded
  from cache are Z3-equivalent to fresh ones; all tests pass.

## Phase 2 — Developer commands (parallel, disjoint files)
### 2A `kfold why <obj> --config .config` — "why isn't my file built?"
- [ ] Chain of guards (directory reachability + obj-/lib- line) with Makefile:line
- [ ] Mark each conjunct ✓/✗ under the config; name the failing symbols
- [ ] For failing symbols, explain via Kconfig (`depends on`, `select`, choice) why they are off
      and what else must change to turn them on
- **Checkpoint 2A:** on ≥10 objects across tinyconfig/defconfig, the built/not-built
  verdict matches the real archived build, and the suggested symbol changes, after
  `make olddefconfig`, actually enable the object.

### 2B `kfold config-for <patch|files...>` — "how do I compile-test this?"
- [ ] Accept a `git diff`/patch file or paths; map `.c`/`.S` → objects (incl. composite members)
- [ ] Solve Φ_Kbuild ∧ Φ_Kconfig with a small / defconfig-close assignment; emit a `.config` fragment
- [ ] Verify: `make olddefconfig` keeps the needed symbols; report any object that can't be enabled and why
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
- [ ] Parse `MAINTAINERS` F:/X: patterns; group objects per subsystem
- [ ] Objects never built by allmodconfig / allyesconfig / defconfig (on x86)
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
