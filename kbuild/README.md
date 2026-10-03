# kfold

kfold is a variability-aware analyzer for Kbuild-style Makefiles. It
symbolically executes each Makefile once, keeping every Make variable as a
map from words to Z3 conditions over Kconfig options. Conditionals are
merged instead of forked. From that it computes the configuration condition
under which each object file of the tree is built. It never runs Make, the
compiler, or recipes (the only exception is `$(shell ...)` calls in
Makefiles).

Analyzed subjects: Linux, BusyBox, Barebox, U-Boot, and coreboot (see
`experiments/README.md` for the exact releases and configurations).

## Requirements

- Python 3.9 or later (the evaluation used 3.14) and `z3-solver`
  (`pip install -r requirements.txt`).
- For the evaluation pipeline only: the build dependencies of each subject
  (GCC, GNU Make, flex, bison, libelf, OpenSSL headers, rustc and bindgen for
  Linux's Rust configurations) and about 60 GB of disk (the builds take
  51 GB). The exact versions used are recorded in `results/environment.json`
  and, per build, `results/builds.json`.

## Using kfold

```sh
pip install -e .                    # installs the `kfold` command
cd path/to/linux                    # a tree with an skbuild.ini (see below)
kfold analyze                       # analyze once; cached in ~/.cache/kfold
kfold why drivers/net/foo.o --config .config   # why is it (not) built?
kfold query drivers/net/foo.o       # kind, origins, and condition
kfold config-for fix.patch          # a .config that compiles what a patch touches
kfold blindspots                    # code no standard configuration builds
kfold lint --diff fix.patch         # checkpatch-style Kbuild checks
```

Without installing: `PYTHONPATH=src python3 -m cli COMMAND ...`. Each
analyzed tree needs an `skbuild.ini` naming its top-level directories and
target lists. The settings used in the evaluation are in
`experiments/settings/<subject>.ini`, and every entry is annotated with the
Makefile lines it comes from.

## Repository layout

| Path | Contents |
|------|----------|
| `src/` | the analyzer (`alg.py` traversal, `symexe.py` symbolic execution, `objects.py` object conditions and rule closure, `kconfig_compat.py`), the CLI (`src/cli`), and a Python 3 port of Mozilla's pymake parser (`src/pymake3`, provenance in `UPSTREAM.md`) |
| `tools/` | helpers used by the CLI and the pipeline (`kfold_targets.py`, `kconfig_solver.py`, `bench_scaling.py`), older one-off analysis scripts, and `make_artifact.sh` |
| `experiments/` | the evaluation pipeline, which produces every result; see `experiments/README.md` |
| `results/` | its outputs: `agreement/`, `timing.json`, `kmax/`, `devtasks/`, `bench_scaling.json`, `kconfig_check.json`, `builds.json`, `manifest.json` (source hashes), `environment.json` |
| `evidence/` | the configurations built (`configs/`), the object inventories of each build (`inventories/`), and the verified `config-for` configurations (`devtasks/config_for.tar.xz`) |
| `tests/` | the pytest suite and its fixtures |

## Reproducing the evaluation

```sh
experiments/run_all.sh
```

It runs fetch, builds, the Kconfig model check, agreement and ablations,
timing, Kmax, scaling, and the developer tasks, in that order. The Linux
builds take hours and Kmax on Linux takes about 1.5 hours. Each step can be
run alone; `experiments/README.md` describes each step, the deviations from
stock builds, and how results are scored. The steps after the builds need
only `evidence/` and the prepared trees, so the analysis can be rerun
without rebuilding.

## Tests

```sh
KFOLD_CACHE=work/kfold-cache python3 -m pytest -q
```

Tests that need an analyzed Linux 7.2.8 tree are skipped unless its cache
exists (`kfold analyze work/prepared/linux-7.2.8` with the same
`KFOLD_CACHE`).

## Packaging the artifact

`tools/make_artifact.sh` writes `dist/kfold-artifact-<commit>.tar.xz` (the
committed tree without `paper/`) and its SHA-256.
