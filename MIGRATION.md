# skbuild Lean 4 Migration Plan

## 1. Purpose

This document is the authoritative plan for migrating skbuild from Python to
Lean 4. The migration targets the current `dev` branch. The retired
`main`/`master` branches are not migration inputs.

skbuild is a variability-aware Kbuild analyzer. It parses Linux/BusyBox
Kbuild Makefiles, symbolically evaluates assignments and conditionals, and
derives the configuration conditions under which object files and
subdirectories participate in a build.

The target is a Lean-native analyzer with an explicit supported language,
reproducible output, strong diagnostics, and machine-checked correctness for
the transformations that affect presence conditions.

This is a semantic reimplementation, not a mechanical syntax translation.

## 2. Scope decision

### 2.1 In scope

- A Lean parser for the subset of GNU Make used by supported Kbuild files.
- A source-located abstract syntax tree (AST).
- Make variable flavors and assignment operators needed by Kbuild.
- Symbolic expansion of configuration-dependent names and values.
- Boolean, tristate, and explicitly configured finite-domain options.
- Conditional symbolic execution.
- Presence-condition construction and simplification.
- Satisfiability checking and unreachable-path pruning.
- Sound splitting and merging of symbolic execution paths.
- Kbuild target extraction (`obj-*`, `lib-*`, and configured extensions).
- Recursive discovery of Kbuild/Makefile directories.
- Included Makefile processing.
- File-presence reports grouped by target type.
- Comparison with concrete `.config` files and build output directories.
- Detection of source files unaccounted for by analyzed Kbuild files.
- Persistent, versioned analysis results.
- A command-line interface suitable for local use and CI.
- Differential tests against the Python implementation during migration.
- Proofs for the semantic and optimization invariants identified below.

### 2.2 Not in scope for the first complete release

- Reimplementing GNU Make as a build executor.
- Running recipe commands.
- Parallel Make job scheduling.
- Timestamp-based target rebuilding.
- GNU Make's built-in implicit-rule database.
- Complete shell semantics.
- Perfect compatibility with every historical GNU Make extension.
- Formalizing host filesystem or operating-system behavior.

Rules and recipes will be parsed sufficiently to preserve source structure and
diagnose unsupported dependencies. They will not be executed.

### 2.3 Definition of "entirely Lean"

The production CLI, parser, symbolic evaluator, solver, traversal, and report
generation must be Lean code. Python and `pymake3` may be used by migration
and differential tests, but must not be runtime dependencies of the final
executable.

## 3. Current system baseline

The `dev` implementation contains these conceptual stages:

1. `pymake3` parses source into its Python AST.
2. Dependency execution discovers assignments relevant to target variables.
3. Irrelevant statements are reduced before symbolic execution.
4. Symbolic execution forks paths at configuration-dependent expressions.
5. Z3 rejects infeasible paths and simplifies merged path conditions.
6. Target values identify object files and subdirectories.
7. Results can be persisted and compared with concrete builds.

Important Python modules and their migration destinations:

| Python area | Responsibility | Lean destination |
| --- | --- | --- |
| `src/pymake3` | Parsing and GNU Make AST | `Skbuild.Syntax`, `Skbuild.Parser` |
| `src/settings.py` | Analysis domains and filters | `Skbuild.Config` |
| `src/expansion.py` | Make expression expansion | `Skbuild.Expansion` |
| `src/ds.py` | Variables, paths, dependency DB | `Skbuild.State`, `Skbuild.Dependency` |
| `src/symexe.py` | Reduction and symbolic execution | `Skbuild.Semantics` |
| `src/kbuild.py` | Per-file orchestration | `Skbuild.Kbuild` |
| `src/alg.py` | Recursive run/cache orchestration | `Skbuild.Traverse`, `Skbuild.Cache` |
| `src/analysis.py` | File extraction and validation | `Skbuild.Analysis` |
| `src/helpers/zsolver.py` | Z3 interface | `Skbuild.Logic`, `Skbuild.Sat` |
| `src/skbuild.py` | CLI | `Main` |

The Python implementation is a reference, not an unquestioned specification.
Where its behavior differs from GNU Make or loses information, the intended
Kbuild semantics must be specified explicitly and covered by tests.

## 4. pymake strategy

### 4.1 Upstream status

Mozilla's `pymake` repository is archived and unmaintained. Its final upstream
revision is:

- Repository: <https://github.com/mozilla/pymake>
- Revision: `034ae9ea5b726e03647d049147c5dbf688e94aaf`
- Revision date: 2014-07-08
- License: MIT

`src/pymake3` is the final upstream implementation ported to Python 3 and
reformatted. It is therefore newer for this project's purposes than replacing
it with the upstream Python 2 files. Exact provenance is recorded in
`src/pymake3/UPSTREAM.md`.

The unrelated PyPI/conda project also named `pymake` (`mfpymake`) must never be
used as an update source.

### 4.2 Temporary role

During migration, `pymake3` has exactly two supported roles:

1. Parse fixtures and corpus Makefiles to produce reference ASTs.
2. Serve as a differential-behavior oracle where current behavior is intended.

It must not acquire new production features. Parser fixes needed to generate
reference data must be isolated and documented.

### 4.3 JSON AST bridge

Before writing the Lean parser, add a small Python tool that serializes the
normalized `pymake3` AST as versioned JSON. The bridge must:

- Include schema version and parser provenance.
- Preserve file, line, and column spans.
- Preserve word order, whitespace where semantically relevant, and operator.
- Represent expressions structurally rather than through `repr` strings.
- Reject unknown AST nodes instead of silently omitting them.
- Emit deterministic key and collection ordering.
- Have snapshot tests.

Proposed command:

```text
python3 tools/pymake_ast.py --schema 1 path/to/Kbuild > ast.json
```

The initial Lean symbolic evaluator may consume this JSON. This bridge is
removed from the production path once the Lean parser passes corpus parity.

### 4.4 Retirement criteria

`pymake3` can leave the production tree when:

- The Lean parser handles every construct in the supported-language matrix.
- Normalized AST differential tests pass for all unit fixtures.
- The Lean parser processes the selected Linux and BusyBox corpora.
- Unsupported syntax produces source-located diagnostics.
- End-to-end presence conditions agree on all accepted golden cases.

After retirement it may remain under `reference/` for regression archaeology,
or be removed while retaining its upstream revision and tests in Git history.

## 5. Target Lean architecture

The initial project layout should be:

```text
lakefile.toml
lean-toolchain
Skbuild.lean
Skbuild/
  Source.lean
  Diagnostic.lean
  Syntax.lean
  Parser/
    Lexer.lean
    Expansion.lean
    Directive.lean
    Makefile.lean
  Config.lean
  Logic/
    Formula.lean
    Normalize.lean
    Cnf.lean
    Sat.lean
  State.lean
  Expansion.lean
  Dependency.lean
  Semantics.lean
  Kbuild.lean
  Traverse.lean
  Cache.lean
  Analysis.lean
  Report.lean
  Cli.lean
Main.lean
Tests/
  Unit/
  Golden/
  Differential/
  Corpus/
tools/
  pymake_ast.py
reference/
```

Pin the toolchain in `lean-toolchain`. The initial development environment has
Lean `4.32.2`; upgrades must be explicit and verified in CI.

### 5.1 Purity boundary

Keep semantic computation pure:

- AST and source spans.
- Expressions and variable environments.
- Formula construction and evaluation.
- Dependency reduction.
- Symbolic path transitions.
- Target extraction.

Restrict effects to explicit adapters:

- Reading Makefiles and includes.
- Directory traversal.
- `wildcard` filesystem queries.
- Cache reads/writes.
- CLI input/output.

Filesystem-sensitive evaluation receives a captured environment or interface,
so tests do not depend on ambient directory state.

## 6. Semantic model

### 6.1 Source model

Every syntax node carries a source span:

```lean
structure SourcePos where
  offset : Nat
  line   : Nat
  column : Nat

structure SourceSpan where
  file  : System.FilePath
  start : SourcePos
  stop  : SourcePos
```

Diagnostics must include a stable code, severity, span, explanation, and
whether the problem makes analysis incomplete.

### 6.2 Configuration domains

Do not hard-code all symbols to one Z3 enum. Model finite domains explicitly:

```lean
inductive KconfigValue
  | no
  | module
  | yes

structure Domain where
  values : Array String
  nonempty : values.size > 0
```

Required domains:

- Boolean: `n`, `y`.
- Tristate: `n`, `m`, `y`.
- User-declared finite strings such as `BITS = 32 | 64`.

Undefined Make variables must remain distinguishable from Kconfig `n` at the
semantic boundary even if both expand to the empty string in a given context.

### 6.3 Formula language

Use a typed finite-domain formula rather than exposing solver expressions:

```lean
inductive Formula
  | top
  | bottom
  | eq  (symbol value : String)
  | not (body : Formula)
  | and (left right : Formula)
  | or  (left right : Formula)
```

Smart constructors should perform cheap canonical simplifications. Structural
hashes must be deterministic across processes and Lean versions wherever they
are stored on disk.

### 6.4 Make values and variables

Make values are ordered text/word structures, not sets. The Lean state must
preserve:

- Text order.
- Duplicate words.
- Recursive versus simply expanded flavor.
- Assignment origin where relevant.
- Unexpanded source for recursive variables.

Required assignment behavior:

| Operator | Initial requirement |
| --- | --- |
| `=` | Store recursively expanded expression |
| `:=`, `::=` | Expand immediately and store value |
| `+=` | Respect the existing variable's flavor |
| `?=` | Assign only when undefined |
| `define` | Preserve recursive/simple flavor dictated by syntax |

Target-specific and override assignments are initially unsupported unless a
corpus audit shows they affect relevant Kbuild outputs. Unsupported relevant
constructs make the analysis explicitly incomplete.

### 6.5 Expression support matrix

Each function is tracked as `unsupported`, `partial`, or `complete`, with unit
and differential tests:

- Variable reference and computed variable name.
- Substitution reference (`$(x:.c=.o)` and pattern form).
- `subst`.
- `patsubst`.
- `strip`.
- `filter` and `filter-out`.
- `sort`.
- Word functions.
- Filename functions.
- `addprefix`, `addsuffix`, and `join`.
- `if`, `or`, and `and`.
- `foreach`.
- `call` with Kbuild idioms.
- `value`, `origin`, and `flavor` when relevant.
- `wildcard`, `realpath`, and `abspath` through the IO boundary.
- `eval` only if corpus evidence requires it.
- `shell` must never execute implicitly during analysis; use an explicit,
  disabled-by-default policy and mark dependent results incomplete.

### 6.6 Conditions

Support nested and chained conditionals:

- `ifeq` and `ifneq`, including GNU Make quoting variants.
- `ifdef` and `ifndef`.
- Plain `else`.
- `else ifeq` and the other conditional forms.
- Multiple branches represented without assuming exactly two AST groups.

For every condition, expansion produces guarded alternatives. Equality is the
disjunction of guards for alternatives producing the same concrete text.

### 6.7 Includes and traversal

- Resolve relative includes against the including file's directory.
- Expand include paths symbolically.
- Distinguish required `include` from optional `-include`.
- Detect include cycles.
- Carry the caller's path condition into the included file.
- Canonicalize paths before cache lookup.
- Prefer `Kbuild`; fall back to `Makefile`, matching current behavior.
- Detect recursive directory cycles and duplicate work.
- Treat dynamically generated includes as incomplete unless supplied as input.

## 7. Solver and proof strategy

### 7.1 Transitional solver

For early parity, a Z3 adapter may run as an external development tool. It must
not leak Z3 types into core structures. Inputs and outputs use the internal
`Formula` representation and a documented serialization format.

An external solver result is untrusted unless accompanied by a checkable
certificate. Therefore it is acceptable for migration comparison but not the
final high-assurance pruning mechanism.

### 7.2 Lean-native finite-domain SAT

The target solver pipeline is:

1. Intern symbolic names and values.
2. Encode each finite-domain symbol propositionally.
3. Add exactly-one constraints for each symbol.
4. Convert formulas to CNF, preferably using a Tseitin encoding.
5. Run a Lean-native DPLL/CDCL-style decision procedure.
6. Return a model for satisfiable formulas or a checkable proof/certificate for
   unsatisfiable formulas.

Start with a small correct solver. Optimize only after corpus benchmarks expose
a bottleneck.

### 7.3 Proof obligations

Priority proof targets:

1. Formula normalization preserves evaluation.
2. CNF encoding is equisatisfiable with the source formula.
3. The SAT result is sound; completeness follows when implemented.
4. A conditional split covers exactly the incoming models.
5. Pruning an unsatisfiable path preserves all feasible executions.
6. Merging equal states by disjoining conditions preserves represented models.
7. Target-value splitting preserves presence conditions.
8. Dependency reduction cannot remove a statement that influences an observed
   target, include, condition, or relevant expansion.
9. Cache serialization/deserialization preserves semantic data.

Properties that depend on filesystem snapshots should be tested against the
captured filesystem model rather than stated over ambient `IO`.

## 8. Result and cache formats

### 8.1 Analysis result status

Never silently present a partial result as complete:

```lean
inductive Completeness
  | complete
  | incomplete (reasons : Array Diagnostic)

structure AnalysisResult where
  files        : Array FilePresence
  completeness : Completeness
```

### 8.2 Stable report

Provide deterministic JSON plus a human-readable format. Each file record
should contain:

- Relative source/object path.
- Target category, such as built-in, module, or library.
- Presence condition in canonical form.
- Defining Makefile and source span.
- Completeness status and contributing diagnostics.

### 8.3 Versioned cache

Cache keys must include:

- Cache schema version.
- Analyzer version.
- Parser/language-profile version.
- Settings hash.
- Input content hash.
- Relevant included-file hashes.
- Precondition hash.

Never use runtime object hashes as persistent identifiers. Cache writes should
be atomic and interrupted runs recoverable.

## 9. Testing strategy

### 9.1 Unit tests

Cover lexer/parser fragments, formula evaluation, assignment flavors,
expansions, condition equality, state operations, and report serialization.

### 9.2 Golden tests

Convert every useful existing small fixture into:

```text
input Makefile/Kbuild
settings
expected normalized AST
expected presence report
expected diagnostics
```

The paper example is the first mandatory end-to-end test.

### 9.3 Differential tests

For supported constructs, compare:

- Normalized `pymake3` AST versus Lean AST.
- Python versus Lean expanded alternatives.
- Python/Z3 versus Lean presence conditions by semantic equivalence, not text.

When Python behavior is demonstrably wrong, add a documented divergence test
instead of reproducing the defect.

### 9.4 Property tests

Generate bounded expressions, environments, and formulas. Check:

- Parse/print/parse normalization.
- Split/merge model preservation.
- Normalization idempotence.
- SAT models satisfy the original formula.
- Cache round trips.

### 9.5 Corpus tests

Use staged corpora:

1. Existing hand-written tests.
2. Existing BusyBox fixtures.
3. Existing Linux fixtures.
4. A pinned BusyBox source release.
5. A pinned Linux source release.

Track per corpus:

- Parse success rate.
- Complete versus incomplete analysis count.
- Unsupported constructs by frequency.
- Object-file agreement with Python.
- Agreement with concrete configured builds.
- Runtime, peak memory, path count, and cache hit rate.

No corpus result is accepted solely because it matches Python; concrete builds
remain the strongest behavioral oracle.

## 10. Delivery milestones

### M0: Repository and behavioral baseline

- [ ] Keep `dev` as the sole branch locally and remotely.
- [x] Record final Mozilla `pymake` provenance and license.
- [ ] Document how to run the current Python analyzer reproducibly.
- [ ] Inventory existing fixtures and classify expected behavior.
- [ ] Establish a clean Python reference test command.
- [x] Record initial checked-in corpus metrics (see corpus qualification baseline below).

Exit: the reference behavior can be rerun and failures are documented.

### M1: Lean project skeleton and core data model

- [x] Add pinned `lean-toolchain` and Lake configuration.
- [x] Add build, test, whitespace validation, and CI commands (formatter pinning remains optional).
- [x] Implement spans, diagnostics, configuration domains, and formulas.
- [x] Implement deterministic JSON encoding for public artifacts.
- [ ] Add unit tests for all foundational structures.

Exit: `lake build` and the initial test suite pass from a clean checkout.

### M2: pymake JSON bridge

- [x] Define normalized AST schema v1.
- [x] Implement strict Python serializer.
- [x] Add snapshots for representative syntax.
- [x] Implement Lean JSON decoder with schema validation.
- [x] Reject unknown and malformed nodes with source context.

Exit: Lean can load every selected fixture AST without importing Python code.

### M3: Lean symbolic evaluation over bridged AST

- [x] Implement environments and Make variable flavors.
- [x] Implement core expansion alternatives and guards.
- [x] Implement assignments and conditionals.
- [x] Implement include semantics with source-root-relative paths, cycles, and a captured filesystem.
- [x] Implement symbolic paths, pruning, splitting, and merging.
- [x] Implement target and subdirectory extraction.
- [x] Match the paper example and the initial golden suite.

Exit: a Lean CLI produces correct presence reports while parsing through the
temporary bridge.

### M4: Lean-native parser

- [x] Implement physical/virtual line handling and continuations.
- [x] Implement comments and escaping.
- [x] Implement expansion parsing with nested delimiters.
- [x] Implement assignments, core directives, conditions, includes, and rules.
- [x] Preserve opaque recipes safely.
- [x] Parse every checked-in Makefile/Kbuild corpus file (2,158 files at the 2026-09-09 baseline).
- [ ] Differentially compare normalized ASTs.
- [x] Publish the supported-language matrix.

Exit: the Lean parser passes unit and selected corpus parity; Python is no
longer used by the production CLI.

### M5: Lean-native solver and proofs

- [x] Implement finite-domain encoding and CNF conversion.
- [x] Implement the initial native DPLL decision procedure.
- [ ] Prove normalization and encoding correctness.
- [ ] Prove split, prune, and merge invariants.
- [ ] Benchmark against Z3-backed reference results.

Exit: production analysis does not require Z3, and infeasible-path pruning is
covered by machine-checked soundness results.

### M6: Analysis parity and persistence

- [x] Implement conservative dependency-based statement reduction.
- [ ] Prove or conservatively validate reduction safety.
- [x] Implement recursive traversal and deduplication.
- [ ] Implement versioned cache and continuation after interruption (result cache is complete).
- [x] Implement `.config` and build-directory comparison.
- [x] Implement unaccounted-source reporting.

Exit: all intended `dev` analyzer capabilities have Lean equivalents.

### M7: Corpus qualification and cutover

- [ ] Run pinned Linux and BusyBox corpora.
- [ ] Classify every unsupported construct affecting completeness.
- [ ] Validate representative configurations against concrete builds.
- [ ] Establish performance budgets and regression thresholds.
- [ ] Remove Python, Z3, and `pymake3` from runtime packaging.
- [ ] Archive final differential evidence.

Exit: the Lean executable is the default and only production analyzer.

#### Corpus qualification baseline (2026-09-10)

- The Lean-native parser accepts all 2,158 checked-in Makefile/Kbuild fixtures.
- All 2,158 inputs also complete tristate, non-recursive analysis under a
  five-second per-file timeout with eight workers. The stricter driver-only
  gate remains two seconds per file.
- Native `--batch-check` analyzes all 2,158 inputs against reused source-root
  snapshots in 6.35 seconds on the 2026-09-10 development host. `make check`
  runs this batch as a regression gate (without a host-specific wall-clock
  assertion).
- Relevance-aware non-recursive execution reports 74 diagnostics across 27 of
  the 2,158 files. Of those, 34 are required includes absent from historical
  fixture snapshots; the remaining 40 describe semantic gaps. Batch JSON
  exposes the stable diagnostic code and source-located details
  for every finding so this remainder can be tracked by semantic category.
- The Linux `drivers/` fixture contains 1,221 Makefile/Kbuild inputs. Every
  input completes the tristate, non-recursive analyzer under a two-second
  per-file timeout when the gate is run with eight workers.
- Recursive tristate analysis of the complete checked-in Linux `drivers/`
  tree completes under a 60-second timeout and reports 30,086 conditional
  object-presence records.
- That recursive run currently emits 41 incomplete-analysis diagnostics:
  13 unresolved required includes and 28
  referenced directories absent from the historical fixture snapshot.
- Generated include, child-directory, and Make path-function results are
  lexically canonicalized before lookup, including repeated separators, `.`
  components, and `..` components.
- The recursive JSON is about 25 MB. Formula/report compaction and a stable
  peak-memory measurement remain required before setting the final budget.

These are implementation-progress gates, not parity evidence. Concrete-build
agreement, Python differential results, BusyBox qualification, exact runtime,
and peak memory remain open M7 work.

#### Static unsupported-construct census (2026-09-10)

Before dependency/relevance filtering, 56 of the 2,158 parsed inputs contain
diagnostics. The initial counts are:

- 95 `shell` calls in 41 files;
- seven `error` calls in five files;
- four `eval` calls in three files;
- 57 top-level expansion side-effect forms in 14 files;
- 110 total top-level/opaque `SKB1004` diagnostics, including those side
  effects, `define` bodies, and build/image commands.

Bare `export` and `unexport` declarations are now classified as harmless for
object-presence analysis and do not make a result incomplete. The remaining
items still require relevance classification: compiler-command and recipe-only
uses may be safely excluded, while any construct feeding a target or directory
must retain an incomplete diagnostic until native semantics exist.

After dependency/relevance filtering and recipe-context correction, the
executable corpus contains 22 unsupported function uses: eight `shell`, eight
`error`, and six `eval`, plus 18 genuinely top-level side-effect expressions.
GNU Make
`warning` and `info` are implemented as argument expansion followed by an
empty value; their output-only side effect is intentionally suppressed, so
they no longer make object-presence analysis incomplete.

Multi-line `define` blocks are parsed as recursive variable definitions, and
conditional directives preserve the surrounding recipe context. Together
these changes removed opaque-definition and nested-recipe false positives
while exposing the `eval` calls reached through relevant macros.

## 11. CI and quality gates

Every change after M1 should require:

- `lake build` succeeds.
- Unit and golden tests pass.
- No newly introduced `sorry` outside explicitly tracked proof scaffolding.
- Public JSON fixtures remain deterministic.
- Parser changes report differential impact.
- Solver/semantic changes run bounded property tests.
- Corpus smoke tests do not increase incomplete results unexpectedly.
- Performance does not exceed agreed regression thresholds.

CI must pin Lean and all dependencies. Network access must not be required for
ordinary tests after dependencies are cached.

## 12. Risk register

| Risk | Impact | Mitigation |
| --- | --- | --- |
| Treating Python bugs as specification | Incorrect Lean semantics | Validate against GNU Make and concrete builds |
| Attempting all GNU Make syntax at once | Migration stalls | Maintain an evidence-based Kbuild support matrix |
| Silent unsupported behavior | Unsound file conditions | Propagate explicit incomplete status |
| Path explosion | Excessive time/memory | Dependency reduction, canonical formulas, verified merging |
| Solver becomes proof bottleneck | Delayed delivery | Use transitional adapter, then replace behind typed interface |
| Filesystem-dependent nondeterminism | Flaky results | Capture filesystem queries and content hashes |
| Lost Make value ordering | Semantic errors | Use ordered text/word structures, never sets |
| Stale persisted data | Incorrect cache hits | Version and content-address every cache dependency |
| Parser parity mistaken for correctness | Shared bugs | Use GNU Make and concrete build comparisons |
| Unclear project-code licensing | Distribution risk | Resolve before publishing a derived release |

## 13. First vertical slice

The first implementation slice should deliberately be small and complete:

1. Create the Lean/Lake project.
2. Define spans, expressions, statements, finite domains, and formulas.
3. Serialize the paper example through the `pymake3` JSON bridge.
4. Decode it in Lean.
5. Implement `:=`, `+=`, variable references, `ifeq`, and `else`.
6. Implement a simple finite-domain satisfiability procedure.
7. Emit deterministic object-file presence JSON.
8. Verify these expected cases:

```text
fork.o      => true
probe_32.o  => CONFIG_A=y and CONFIG_B=y  (built-in)
probe_32.o  => CONFIG_A=y and CONFIG_B=m  (module)
probe_64.o  => CONFIG_A!=y and CONFIG_B=y (built-in)
probe_64.o  => CONFIG_A!=y and CONFIG_B=m (module)
```

This slice validates the architecture before parser breadth, caching, corpus
scale, or advanced proofs increase complexity.

## 14. Completion definition

The migration is complete when:

- A clean checkout builds with the pinned Lean toolchain.
- The production executable has no Python, `pymake3`, or Z3 runtime dependency.
- Supported Kbuild syntax is documented and source-located failures are clear.
- All retained golden tests pass.
- Selected Linux and BusyBox corpora meet the agreed completeness threshold.
- Representative concrete build comparisons pass.
- Presence-condition-affecting optimizations have machine-checked soundness.
- Reports and caches are deterministic and schema-versioned.
- Operational and contributor documentation is sufficient for a new developer
  to build, test, analyze a tree, and interpret incomplete results.
