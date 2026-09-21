# skbuild

skbuild is a variability-aware Kbuild analyzer. It parses Makefile/Kbuild
input, symbolically follows configuration-dependent assignments and
conditionals, recursively visits selected subdirectories, and uses Z3 to
report the condition under which each object participates in the build.

Execution keeps a single symbolic state per Kbuild file: each Make variable
holds a `word -> Z3 condition` map (`ds.VarG`/`ds.BaseState`), and a
conditional (`ifeq`/`ifdef`) clones that state per branch, runs each branch
against its clone, and merges the two clones back into one state gated by
each branch's own guard (`symexe.ConditionBlock.sexe` /
`_merge_branch_states`). This replaced an earlier design that forked a
separate `Path` object per branch and exploded combinatorially (a ~30-line
fixture already produced 32 forked paths); it mirrors the branch/merge
architecture used by the sibling `cybolic` (CMake) analyzer.

The implementation is pure Python (`src/`), using a Python 3 port of Mozilla's
`pymake` (`src/pymake3`, provenance in `src/pymake3/UPSTREAM.md`) for parsing
and Z3 (`src/helpers/zsolver.py`) for symbolic condition solving/simplification.
A prior Lean 4 rewrite was attempted and has been retired; Python+Z3 is the
canonical implementation going forward. See `PLAN.md` for the active work
plan toward analyzing real Linux/BusyBox/coreboot Kbuild trees.

## Requirements

- Python 3 with the `z3-solver` package importable as `z3` (`pip install
  z3-solver`, or a system package providing the `z3` Python bindings).

## Usage

```sh
PYTHONPATH=src python3 src/skbuild.py <path to Makefile or Kbuild dir> [options]
```

Key options (see `python3 src/skbuild.py --help`):

- `--nomp` — disable multiprocessing (recommended; see Known issues).
- `--rmtmp` — remove the temporary result directory after the run instead of
  printing its path.
- `--build_dir=PATH` / `--src_dir=PATH` — compare against a build output
  directory or check source coverage.
- `--log_level {0..4}` — verbosity.

Example:

```sh
PYTHONPATH=src python3 src/skbuild.py tests/paper_example/Makefile --nomp --rmtmp
```

## Configuration

An `skbuild.ini` beside the analyzed tree configures symbolic domains and
target prefixes (see `tests/busybox_skbuild.ini`, `tests/linux_skbuild.ini` for
examples), e.g.:

```ini
[COMMON]
use_tristate = no
top_dirs = drivers fs kernel
ignore_files = built-in.o
ignore_dirs = scripts
```

## Reproducible baselines

```sh
tools/record_baseline.py --output-dir results/baselines/tree tests/paper_example/Makefile -- --nomp --rmtmp
```

Records the pinned revision, dirty diff, command, machine, input digest,
timing/RSS, and raw stdout/stderr for a run.

Source acquisition (download/extract into a digest-verified workspace) is
independent of analysis:

```sh
tools/acquire_source.py https://cdn.kernel.org/pub/linux/kernel/v6.x/linux-6.12.tar.xz \
  --output-dir results/workspaces/linux
```

## Known issues

- `--nomp` is required today: the multiprocessing path in
  `src/helpers/miscs.py` (`Miscs.run_mp`) fails to pickle closures on current
  Python (`_pickle.PicklingError`). This is now dead code on the main
  execution path (there is no longer a `Paths` list to parallelize merges
  over) and should just be deleted rather than fixed.
- The checked-in Linux snapshot (`tests/linux/linux_orig`) fails partway
  through with a `pymake3` parser error
  (`TypeError: '>=' not supported between instances of 'NoneType' and 'int'`
  in `src/pymake3/parser.py`'s `getloc`, triggered by an "Unterminated
  function call") on at least one real kernel Makefile construct. This is a
  pre-existing `pymake3`/parser gap, not related to the symbolic-execution
  engine; `tests/linux_skbuild.ini`'s own comments already document several
  known-problematic subdirectories.
- `tests/linux_skbuild.ini` uses a `[DEFAULT]` section; `settings.py` reads
  `config['COMMON']`, so this file likely needs updating (or `settings.py`
  needs to accept `[DEFAULT]`) before a full Linux run is attempted.

## Tests

```sh
make test            # tests/paper_example smoke test
make busybox-check    # full checked-in BusyBox snapshot: 37 kbuilds, ~0.6s
```

There is no differential test suite against a GNU Make oracle yet; see
`PLAN.md`'s M4.
