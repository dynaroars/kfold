# Canonical kfold evaluation

Every number in the paper comes from one run of this pipeline. Nothing else
under `results/` or `evidence/` is used (older material is in
`results/legacy/` and `evidence/legacy/`, untracked).

## Subjects

Pinned in `subjects.py`: Linux 7.2.8, BusyBox 1.38.0, Barebox 2026.09.0,
U-Boot 2026.07, coreboot 26.06, each a release tarball verified against the
upstream SHA-256 where the project publishes one (Linux, BusyBox, coreboot)
and otherwise recorded as downloaded (Barebox, U-Boot). Configurations:

| Subject  | Configurations |
|----------|----------------|
| Linux    | i386 `tinyconfig`, x86-64 `defconfig`, Debian (`/boot/config-7.2.6+deb14-amd64` + `olddefconfig`), x86-64 `allmodconfig`; `allyesconfig` generated but not built (blind-spot query only) |
| BusyBox  | `defconfig` |
| Barebox  | `sandbox_defconfig` |
| U-Boot   | `sandbox_defconfig` |
| coreboot | QEMU i440fx |

kfold's settings for each subject are in `settings/<subject>.ini`, each entry
annotated with the Makefile lines it is derived from.

## Steps

```
experiments/run_all.sh          # everything below, in order
```

1. `fetch.py` downloads and verifies the releases into `work/src/` (read-only)
   and prepares the analyzed trees in `work/prepared/`: a copy of the release,
   after the subject's own build-file generator (BusyBox: `make
   gen_build_files`, since BusyBox ships `Kbuild.src` templates), with the
   tracked settings installed as `skbuild.ini`. Writes `results/manifest.json`.
2. `build.py` builds every configuration in its own copy under `work/build/`
   with `make -k` and writes `.config` files to `evidence/configs/`, object
   inventories (every `.o` except `*.mod.o`) and failure lists to
   `evidence/inventories/`, and build records to `results/builds.json`.
3. `check_kconfig.py` checks kfold's Kconfig model (kconfiglib plus
   `src/kconfig_compat.py`) against the `.config` values scripts/kconfig
   wrote. -> `results/kconfig_check.json`
4. `evaluate.py --variants full,no_includes,no_rules,no_link_semantics` runs
   kfold on each prepared tree and compares predictions with the inventories,
   for the full tool and each ablation. -> `results/agreement/`
5. `timing.py` times the whole-tree analysis three times per subject on an
   idle machine (load < 1). -> `results/timing.json`
6. `kmax.py` runs Kmax (kmaxall 4.10, as shipped) on Linux and BusyBox and
   scores it the same way. -> `results/kmax/`
7. `tools/bench_scaling.py` runs the generated-Makefile scaling benchmark.
   -> `results/bench_scaling.json`
8. `devtasks.py why|config-for|compile|blindspots` runs the developer tasks
   on Linux. `config-for` uses the 437 commits of the v7.2.7..v7.2.8 stable
   update (fetched into `work/stable-7.2.8` with a shallow `git fetch` of tag
   v7.2.8), keeping the 402 that touch a `.c` or `.S` file.
   -> `results/devtasks/`. The verified configurations are saved to
   `evidence/devtasks/config_for/` (committed as `config_for.tar.xz`;
   extract it there before re-running `compile` alone).
9. `paper_numbers.py` writes `paper/numbers.tex` (one macro per number used in the
   paper) and the table bodies in `paper/tables/`.

## Toolchain and deviations from stock builds

GCC 16.2.0 (Debian), GNU Make 4.4.1, rustc 1.95.0, bindgen 0.72.1, Python
3.14.7, Z3 5.1.0, coreboot's own i386 cross toolchain (`make crossgcc-i386`,
GCC 15.2.0) for coreboot. Recorded per build in `results/builds.json`; the
machine and tool versions of the analysis runs are in `results/environment.json`
(`environment.py`).

* Linux Debian: `SYSTEM_TRUSTED_KEYS` and `SYSTEM_REVOCATION_KEYS` emptied
  (Debian's certificates are not in the tree). Four Debian-patch-only options
  (`LOCK_DOWN_IN_EFI_SECURE_BOOT`, `SECURITY_PERF_EVENTS_RESTRICT`,
  `X86_X32_DISABLED`, `INTEL_IOMMU_DEFAULT_ON_INTGPU_OFF`) do not exist
  upstream and are dropped by `olddefconfig`.
* Linux allmodconfig: `WERROR`, `DRM_WERROR`, `DRM_AMDGPU_WERROR` disabled so
  new compiler warnings do not abort files.
* coreboot: `CONFIG_PAYLOAD_NONE=y` (SeaBIOS would be cloned mid-build).
* U-Boot: `NO_PYTHON=1` (the SWIG-generated pylibfdt wrapper uses Python 2
  APIs absent in Python 3.14); the final `binman` image step therefore fails
  after every object has compiled.
* BusyBox: `networking/tc.c` does not compile against current kernel headers
  (the CBQ API was removed); reported as a build failure, not configured away.

Objects that `make` tried and failed to compile, or would still build after
an earlier failure (checked with `make -n`), are reported separately from
kfold's false positives.
