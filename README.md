# skbuild

skbuild is a variability-aware Kbuild analyzer being migrated to Lean 4. It
parses Makefile/Kbuild input, symbolically follows configuration-dependent
assignments and conditionals, recursively visits selected subdirectories, and
reports the condition under which each object participates in the build.

The `dev` branch is canonical. The ordinary analyzer CLI is native Lean and
does not invoke Python, `pymake3`, Z3, Make, recipes, or shell commands. The
explicit `skbuild analyze` acquisition workflow invokes the checked-in Python
orchestration helper, then runs the same native Lean analyzer; the archived
Python implementation remains a migration oracle while parity work continues.

## Build and test

Install `elan`; the repository's `lean-toolchain` pins the required Lean
version. No third-party Lake dependencies are required.

```sh
make build
make test
```

`make test` builds both executables, runs Lean unit tests, compares native and
bridge behavior against golden results, validates JSON reports, exercises
includes and traversal, and parses all 2,158 checked-in Makefile/Kbuild corpus
files with the native parser.

## Examples

Acquire and analyze a local tree or archive in one reproducible workspace:

```sh
.lake/build/bin/skbuild analyze ./linux.tar.xz --tristate --output=results/linux
.lake/build/bin/skbuild analyze linux:latest --tristate --output=results/latest
```

The command requires `--output=DIR`; it writes the acquired source workspace,
acquisition/run manifests, and JSON report there. Use the legacy forms below
when the source is already prepared locally and no acquisition stage is needed.
`linux:latest` resolves the current stable release from kernel.org metadata and
records the pinned version and URL in the acquisition manifest.

Completed run directories can be reused and queried:

```sh
.lake/build/bin/skbuild resume results/linux
.lake/build/bin/skbuild query results/linux --file=drivers/usb/core/usb.o
.lake/build/bin/skbuild query results/linux --option=CONFIG_USB
```

`resume` reuses the recorded source and analyzer command. Query results are
currently loaded from the JSON report; streaming/indexed storage is planned for
large complete Linux runs.

Analyze one Kbuild file or a directory whose entry point is `Kbuild` (preferred)
or `Makefile`:

```sh
.lake/build/bin/skbuild tests/paper_example/Makefile
.lake/build/bin/skbuild Tests/Fixtures/tree
```

Example output:

```text
1.o     built-in  (CONFIG_1=y || (CONFIG_1=n && CONFIG_A=y))
3.o     built-in  (CONFIG_A=y || (CONFIG_A=n && CONFIG_B=y))
scan.o  built-in  true
```

Emit deterministic structured output, enable tristate domains, or select the
objects for a concrete configuration:

```sh
.lake/build/bin/skbuild --json Tests/Fixtures/tree
.lake/build/bin/skbuild --tristate path/to/linux
.lake/build/bin/skbuild --config=path/to/.config path/to/linux
.lake/build/bin/skbuild --no-recursive path/to/linux/drivers/Makefile
```

The checked-in BusyBox snapshot includes a project configuration for its
`core-y`/`libs-y` top-level layout and can be analyzed recursively:

```sh
.lake/build/bin/skbuild --tristate --json tests/busybox/Makfiles_only/busybox_orig
```

Its top-level Makefile uses host-dependent `shell` and `error` calls, so the
report intentionally remains incomplete while still reporting the objects in
its configured Kbuild subtrees.

The checked-in Linux snapshot likewise has a project configuration covering
its top-level Kbuild subtrees:

```sh
.lake/build/bin/skbuild --tristate --json tests/linux/linux_orig
```

It reports more than 40,000 conditional object records. The historical source
snapshot omits some generated/includes paths, and a few files use unsupported
side-effecting Make operations, so its report is also intentionally incomplete.

JSON reports retain the `complete` field for compatibility and also include a
`coverage` object. Its `selected_scope`, `input_coverage`,
`unsupported_semantics`, `kconfig_validity`, `build_validation`, and
`qualification` fields make the limits of an incomplete result explicit;
`qualification: "unknown"` must not be interpreted as evidence that an object
is dead.

For reproducible measurements, record a run rather than copying console output:

```sh
tools/record_baseline.py --output-dir results/baselines/tree Tests/Fixtures/tree
```

The artifact contains the pinned revision, dirty diff, command, machine and
Lean toolchain, input digest, timing/RSS, result counts, raw JSON, and stderr.

Source acquisition can be prepared independently of analysis:

```sh
tools/acquire_source.py https://cdn.kernel.org/pub/linux/kernel/v6.x/linux-6.12.tar.xz \
  --output-dir results/workspaces/linux
```

The acquisition workspace records input and extracted-tree digests, preserves
the archive when applicable, rejects archive traversal/special-file hazards,
and publishes the source directory only after successful extraction. Failed
HTTP downloads retain a URL-keyed partial in the persistent cache and resume
with a ranged request on a later run. Publisher checksum verification is
available with `--sha256` or `--checksum-url`, and the manifest records its
result. Cryptographic signature verification remains pending.

The explicit orchestration bridge combines both stages and writes a report plus
separate acquisition/run manifests:

```sh
tools/skbuild_analyze.py ./linux.tar.xz --tristate --output results/linux
```

It selects the extracted directory containing the archive's Kbuild entry point
and invokes the native Lean analyzer there. The standalone Lean binary remains
Python-free; this bridge is the current external orchestration interface. Use
`--project=linux` or `--project=busybox` to override conservative metadata
detection when the source tree does not identify itself.

Compare configured predictions with a build directory and find source files
not accounted for by the predicted objects:

```sh
.lake/build/bin/skbuild \
  --config=path/to/.config \
  --build-dir=path/to/build \
  --src-dir=path/to/source \
  path/to/source
```

Parse without evaluating. Multiple files are accepted so a corpus starts one
Lean process:

```sh
.lake/build/bin/skbuild --parse-only path/to/Kbuild path/to/Makefile
```

Analyze many files non-recursively against source-root snapshots captured once
per root. JSON mode emits one status object per input, including diagnostic
counts, codes, and source-located details:

```sh
find path/to/source -type f \( -name Makefile -o -name Kbuild \) -print0 \
  | xargs -0 .lake/build/bin/skbuild --tristate --batch-check --json
```

Reuse a versioned native result cache. Cache entries are invalidated when the
analyzed Makefile/Kbuild/`.mk` inputs, symbolic settings, or captured
filesystem path set changes:

```sh
.lake/build/bin/skbuild --cache=.skbuild/report.json path/to/source
```

Diagnostics go to stderr and are also embedded in `--json` output. Any
diagnostic with `makes_incomplete: true` means the result must be treated as a
conservative migration result, not as a completeness claim.

## Configuration

An optional `skbuild.ini` beside the input configures symbolic domains and
target prefixes. Boolean `CONFIG_*` values default to `y`/not-set; use
`--tristate` for `y`/`m`/not-set. Custom finite domains can be declared in the
`[COPTIONS]` section.

```ini
[COMMON]
use_tristate = yes
target_vars = obj- lib- host-

[COPTIONS]
BITS = 32 64 None
```

## Migration status

[MIGRATION.md](MIGRATION.md) is the authoritative, milestone-based migration
plan. [SUPPORTED.md](SUPPORTED.md) distinguishes parsed, fully evaluated,
partial, and intentionally disabled GNU Make/Kbuild constructs. In particular,
recipes are preserved but never executed, and `shell` is disabled.

`tools/pymake_ast.py` and `src/pymake3` are test/reference components only.
Their upstream provenance is recorded in `src/pymake3/UPSTREAM.md`.
