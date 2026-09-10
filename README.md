# skbuild

skbuild is a variability-aware Kbuild analyzer being migrated to Lean 4. It
parses Makefile/Kbuild input, symbolically follows configuration-dependent
assignments and conditionals, recursively visits selected subdirectories, and
reports the condition under which each object participates in the build.

The `dev` branch is canonical. The production CLI is native Lean: it does not
invoke Python, `pymake3`, Z3, Make, recipes, or shell commands. The archived
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
