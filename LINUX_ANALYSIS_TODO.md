# Linux build analysis: implementation and research TODO

This is the forward implementation plan for skbuild. Linux is the primary
target; BusyBox is a smaller regression and comparison target. This is the
canonical implementation checklist, replacing the retired migration TODO.
Controlled dynamic execution is an intended feature.
The production analyzer remains Lean; external Make, shell, compiler, downloader,
and extraction tools may be invoked through explicit orchestration interfaces.

Status convention: `[x]` means implemented in the working tree, not necessarily
committed or validated on a current complete Linux release. `[ ]` means remaining.
Commands and layouts below are proposed interfaces unless stated otherwise.

Current implementation evidence (2026-09-13): the first checkpoint is committed
as `071f8fa`. Direct top-level `$(eval TEXT)` statements, including statements
inside analyzed conditionals, now expand and execute generated assignments in
order in the recursive IO evaluator. This is intentionally only a subset of
the P3 contract: nested eval, generated rule semantics, guarded termination,
command execution, and effect provenance remain unsupported and must not be
treated as complete.

The typed report context is committed as `2912242`. The baseline recorder in
`tools/record_baseline.py` is now covered by the e2e suite and writes a manifest,
raw report, stderr, and dirty patch for each run. A complete pinned Linux
release baseline has not yet been archived; the existing Linux/BusyBox fixture
measurements remain preliminary.

The CLI now accepts `--strict`: it still emits an incomplete JSON report, but
returns status 1 when any diagnostic makes the analysis incomplete. Full
distinction among command failure, resource exhaustion, and interruption is
still pending.

## 1. Product goal and definition of done

A user supplies a Linux source archive URL and runs one command. skbuild resolves
the input, downloads and extracts it, selects a documented analysis environment,
prepares required generated inputs, derives guarded build membership, and writes
queryable results and an explanation of coverage and limitations.

```sh
# Proposed: explicit release archive, symbolic configuration analysis for x86
skbuild analyze https://cdn.kernel.org/pub/linux/kernel/v6.x/linux-6.12.tar.xz \
  --arch=x86 --output=results/linux

# Proposed: resolve the latest stable release when the command runs
skbuild analyze linux:latest --arch=x86 --output=results/latest

# Proposed: concrete configuration and independent build validation
skbuild analyze ./linux --arch=x86 --config=./kernel.config \
  --validate-build --output=results/concrete

# Proposed: resume and query without reloading one enormous JSON report
skbuild resume results/linux
skbuild query results/linux --file=drivers/usb/core/usb.o
skbuild query results/linux --option=CONFIG_USB
```

The explicit release above is an interface example, not a claim about the latest
release. `linux:latest` must resolve live release metadata and pin its result.

- [ ] Deliver URL and local-directory inputs through the same pipeline.
- [ ] Make the default one architecture and one recorded toolchain environment;
  use x86 initially, state that choice visibly, and accept explicit overrides.
- [ ] Keep configuration symbols symbolic unless the user requests a concrete
  `.config`; architecture/toolchain choices define the analysis scope.
- [ ] Return object presence conditions, target kinds, contributing Makefile
  locations, diagnostics, execution assumptions, and coverage information.
- [ ] Support cancellation and restart without discarding completed work.
- [ ] Validate against at least one complete pinned Linux release and BusyBox
  release; exercise current latest Linux separately as a moving compatibility test.
- [ ] Define a qualified release criterion: supported scope has validated
  predictions, every unresolved effect is represented, and incomplete runs cannot
  be mistaken for evidence of dead code.

## 2. Current baseline and corrections to earlier claims

- [x] Native parser, symbolic assignment/conditional evaluation, finite-domain
  solver, target extraction, include handling, and recursive traversal exist.
- [x] JSON/text output, concrete config filtering, coverage comparisons, and a
  whole-result cache exist.
- [x] Configured target prefixes and explicit `top_dirs` are used by traversal.
- [x] BusyBox fixture configuration enumerates 35 subdirectories plus its root.
- [x] Linux fixture configuration enumerates selected top-level subtrees.
- [x] Working-tree regression tests exercise both snapshot reports.
- [ ] Archive a reproducible baseline with revision plus dirty diff, command,
  machine, toolchain, inputs, wall time, memory, and counts.

Previously observed fixture results were 588 BusyBox object/target records and
41,209 Linux records. BusyBox took approximately 0.1 seconds in one warm local
measurement. These are preliminary observations, not benchmark guarantees.
Both reports were incomplete. The Linux snapshot lacks a root Makefile and many
referenced inputs; its configured subtree enumeration is not a faithful execution
of a complete Linux root build. It also does not establish coverage of all
architectures. Counting output records is not correctness validation.

Existing conditions use symbol domains, not full Kconfig validity constraints.
Reported completeness currently does not establish formal soundness, complete
Linux support, or validity for every architecture/toolchain. Documentation and
the paper must distinguish those claims.

## 3. Execution order and work package contracts

Suggested dependency sequence:

1. P0: baseline, semantic/report contracts, reproducible examples.
2. P1: input acquisition and run workspace; P2: shared data structures and schemas.
3. P3: effectful evaluation; P4: Linux root/recursive invocation modeling.
4. P5: Kconfig integration and scope semantics; P6: durable storage and queries.
5. P7: concrete build validation and diagnostic-driven compatibility work.
6. P8: performance qualification, applications, CLI polish, paper evaluation.

P1 and P2 can proceed independently after P0. P3 and P4 must agree on the
environment/effect interface before parallel implementation. P5 can prototype a
constraint importer using the P0 condition API. P6 depends on P2 identities and
P0 report semantics. P7 should start collecting oracle data early.

For every work package:

- [ ] Assign an owner and list exact files/modules before starting.
- [ ] Record dependencies, interface signatures, acceptance tests, and artifacts.
- [ ] Preserve unrelated working-tree changes; do not equate existing edits with
  committed baseline behavior.
- [ ] Agree on shared types before separate agents modify consumers.
- [ ] Avoid simultaneous ownership of `Main.lean`, common state types, and schemas.
- [ ] Include a minimal example, expected result, regression, and paper note for
  every new semantic feature.
- [ ] Run focused tests, then `make check` at integration points.
- [ ] Update status with evidence and remaining gaps; never mark a phase complete
  merely because fixture output grows or diagnostics disappear.

## P0. Define semantics, scope, and evidence

- [ ] Define selection condition versus successful compilation versus final link
  inclusion. An object selected by Kbuild need not compile successfully.
- [ ] Separate source files, compilation units, composite objects, archives,
  generated files, host tools, modules, and final artifacts in the result schema.
- [ ] Distinguish a filesystem path from a symbolic execution path in APIs and docs.
- [ ] Specify Boolean/tristate domains, built-in/module propagation, composite
  member selection, library membership, and duplicate contribution semantics.
- [ ] Specify how external-module mode and architecture-specific builds enter scope.
- [ ] Replace one overloaded completeness claim with explicit fields for selected
  scope, input coverage, unsupported semantics, Kconfig validity, and validation.
- [ ] Define result qualification: exact within modeled scope, overapproximation,
  underapproximation, or unknown. Do not label every incomplete output conservative
  without establishing which direction its errors can take.
- [ ] Define exit codes for success, incomplete analysis, invalid input, command
  failure, resource exhaustion, and interruption; add a CI strictness option.
- [ ] Create `Tests/Examples/` and `paper/examples/` artifact conventions (see below).

Acceptance: tiny examples specify path guards, terminated paths, missing inputs,
and result qualifications with machine-checked expected outputs.

## P1. Acquire sources and create reproducible run workspaces

Proposed components: `Skbuild/Acquire`, `Skbuild/Run`, `Skbuild/Manifest`, CLI
orchestration. Keep network/archive implementation replaceable behind interfaces.

- [ ] Accept local trees, local archives, explicit HTTPS archives, and `linux:latest`.
- [ ] Resolve latest stable from an authoritative release feed; record resolved
  version, URL, retrieval time, and release metadata. Never re-resolve on resume.
- [ ] Download incrementally with bounded retries, cancellation, redirect policy,
  and partial-download recovery.
- [ ] Compute a cryptographic content digest; verify published checksums/signatures
  when available and record exactly what was verified.
- [ ] Key immutable source cache by digest; deduplicate concurrent downloads.
- [ ] Support the archive formats actually published for the selected projects.
- [ ] Validate extraction paths, links, file counts, and expanded size; reject
  archive entries escaping the extraction root. Test malicious and corrupt archives.
- [ ] Extract atomically into a dedicated source directory; preserve original files.
- [ ] Detect Linux/BusyBox from source metadata with an explicit override.
- [ ] Create separate source, generated/build, temporary, and report directories.
- [ ] Check required programs and versions; show actionable missing-dependency
  errors without silently installing system packages.
- [ ] Record source digest, analyzer version, settings, environment, architecture,
  toolchain versions, command policy, and configuration digest in a manifest.
- [ ] Implement stage progress and a structured failure record for each stage.
- [ ] Test network behavior using a local HTTP fixture server; reserve internet
  tests for an explicitly invoked integration lane.

Acceptance: a small archive URL completes end to end, corrupted input fails
clearly, and rerunning the pinned input reuses verified cached source bytes.

## P2. Efficient identities, environments, formulas, and work queues

Current pressure points include list-based environments, repeated string paths,
linear record merging, tree-shaped formulas, and whole-report JSON loading.
Measure each replacement against the baseline; preserve deterministic semantics.

| Data | Proposed representation | Required invariants / checks |
| --- | --- | --- |
| Names and paths | Intern tables mapping strings to stable run-local IDs | Persist dictionaries; do not expose allocation order as semantic identity |
| Filesystem paths | Root ID plus normalized relative components | Separate source/build roots; explicit case and symlink policy |
| ASTs | Immutable arena indexed by node/source IDs | Retain source spans and generated-text provenance |
| Environments | Persistent map from symbol ID to variable record | Structural sharing, scope, flavor, origin, and override precedence |
| Symbolic states | Environment ID, guard ID, invocation context ID | Merge only states whose future evaluation behavior is equivalent |
| Guards | Hash-consed formula DAG | Structural equality checked after hash matches; deterministic export |
| Targets | Map keyed by path ID, target kind, invocation context | Merge guards and retain provenance; never conflate architectures |
| Traversal | Queue plus indexed pending/visited maps | Key includes relevant inherited environment and build mode |
| File lookup | Snapshot index by directory and basename | Track dependencies for wildcard, realpath, and generated files |

- [ ] Implement ID types so source paths, variables, formulas, and states cannot
  accidentally be interchanged.
- [ ] Profile persistent map implementations in Lean before selecting one.
- [ ] Preserve recursive/immediate variable flavors and lazy expansion; replacing
  environments with maps must not turn ordered effects into unordered operations.
- [ ] Hash-cons expressions and formulas with bounded memoization policies.
- [ ] Cache expansion by expression, relevant environment, guard/context where
  needed, filesystem snapshot, and effect replay identity.
- [ ] Replace repeated scans in target/guard merging with indexed accumulation.
- [ ] Use a formula DAG and Tseitin CNF encoding to avoid distributive CNF blowup.
- [ ] Add incremental SAT queries and memoization for repeated feasibility checks.
- [ ] Evaluate BDDs only through benchmarks; document variable-order sensitivity
  and keep a fallback for cases that grow badly.
- [ ] Avoid exhaustive truth-table canonicalization on large symbol sets; render
  compact guards with optional human-readable simplification on demand.
- [ ] Add state, formula, expansion, time, and memory budgets; exhausting a budget
  must produce a resumable partial result with explicit coverage limits.
- [ ] Measure allocations, peak RSS, sharing ratios, solver calls, cache hit rates,
  and queue sizes on growing real subtrees and adversarial synthetic examples.

Acceptance: baseline examples retain equivalent conditions; scaling tests show
where costs grow, and no hash collision or state merge can silently alter meaning.

## P3. Hybrid symbolic evaluation and Make effects

Place effectful expansion/execution above the pure expression layer and parser.
Do not create an import cycle by importing the parser into `Expansion.lean`.
Design an explicit effect runner so live execution and recorded replay share the
same evaluator. Preserve native parser/analysis ownership; extend the Python
parser only if reference tests require it.

### Stateful expansion contract

- [ ] Define expansion results carrying values, guards, updated environments,
  diagnostics, effect provenance, and live/terminated/unknown path status.
- [ ] Specify left-to-right evaluation order and exactly where Make expands
  assignment names, values, includes, conditionals, and function arguments.
- [ ] Preserve lazy `if`, `and`, `or`, `call`, and scoped `foreach` behavior.
- [ ] Treat side effects as relevant during dependency reduction. Disable unsafe
  reduction around unknown generated statements until dependency tracking is sound.
- [ ] Propagate state changes from nested effects back to surrounding expansion.

### `eval` and generated syntax

- [ ] Match Make's two expansion stages: expand the argument, then parse/evaluate
  the resulting Make text; model dollar escaping and return the empty string.
- [ ] Execute generated statements at the current sequence point and guard.
- [ ] Support generated definitions, assignments, conditionals, and includes.
- [ ] Preserve source provenance from generated text back to the call site.
- [ ] Cover `eval` inside `if`, `foreach`, `call`, immediate assignments, and
  recursively expanded variables; test guarded overwrites and nested effects.
- [ ] Bound generated text size and recursive evaluation depth with diagnostics.
- [ ] Audit rule generation separately: parsing a generated rule does not imply
  that its prerequisites/recipe are modeled by target-list extraction.

### `shell`, errors, and execution context

- [ ] Introduce a command runner with cwd, explicit environment, stdin, stdout,
  stderr, exit status, duration, timeout, and descendant-process cancellation.
- [ ] Specify GNU Make stdout newline normalization and `.SHELLSTATUS` behavior.
- [ ] Preserve invocation counts: repeated recursive-variable expansion can rerun
  shell commands; simple assignments normally run once at assignment time.
- [ ] Expand symbolic command arguments under guards. Run finite concrete variants
  with isolated contexts; cap unbounded alternatives and report unresolved effects.
- [ ] Never reuse one concrete `.config`-dependent probe result across every
  symbolic configuration without a dependency argument or conditional partition.
- [ ] Isolate filesystem effects of mutually exclusive paths; do not let one
  branch's generated files contaminate another branch's analysis.
- [ ] Execute configured preparation/toolchain commands in a dedicated workspace.
  Provide documented execution policy, resource limits, and optional isolation.
- [ ] Record command dependencies, nondeterminism, and replay assumptions. Cache
  arbitrary shell output only when its input dependencies are established; an
  identical command string/environment alone is not a sufficient cache key.
- [ ] Handle guarded `error` by terminating selected paths; report termination
  separately from unsupported semantics and from compilation failure.
- [ ] Test warning/info argument effects even when message output is suppressed.
- [ ] Implement richer syntax such as target-specific variables or `!=` only with
  explicit semantics and corpus examples; keep unknown relevant forms diagnosed.

Acceptance: GNU Make oracle comparisons on tiny fixtures establish effect order,
double expansion, stdout conversion, branch isolation, and path termination.

## P4. Model a real Linux invocation

- [ ] Inspect complete release root Makefiles and document entry-point selection.
  Linux root `Kbuild` is not a replacement for root Makefile orchestration.
- [ ] Model invocation variables (`ARCH`, `SRCARCH`, `CROSS_COMPILE`, `LLVM`,
  `O`, `srctree`, `objtree`, `src`, `obj`, goals, external modules).
- [ ] Preserve variable origin and command-line/environment/Makefile precedence.
- [ ] Carry relevant inherited variables across recursive invocations and includes;
  a fresh environment per directory is insufficient for a general Linux build.
- [ ] Derive root directory guards from root logic and architecture includes.
  Explicit subtree inventories may be an analysis mode, but must be labeled as
  such and must not imply root reachability.
- [ ] Support root aggregators and their transformations into built-in archives
  and objects; do not infer all aggregate semantics from prefix spelling alone.
- [ ] Model module/built-in propagation through directories and composite objects.
- [ ] Account for `scripts/Makefile.*` helper logic, generated includes, and
  release-dependent Kbuild conventions using targeted compatibility tests.
- [ ] Add a preparation stage that obtains generated inputs in a separate build
  directory. Determine required Make goals for each qualified release/profile.
- [ ] Distinguish build-time generated files from files missing in the source tree.
- [ ] Define treatment of host tools and always-built/generated targets; include
  them as typed records or explicitly mark them outside the selected scope.
- [ ] Implement architecture profiles for x86 first, then arm64; make toolchain
  availability and architecture-specific completeness visible.
- [ ] Keep BusyBox profile tests to catch Linux-specific assumptions.

Acceptance: run on an unmodified complete source release, preserve root guards,
and demonstrate both built-in and modular nested objects without hand-enumerating
every subsystem as unconditionally reachable.

## P5. Kconfig constraints and configuration-dependent preparation

- [ ] Define a constraint importer interface and evaluate supported Kconfig tools
  against the chosen Linux revisions; record dependency/version requirements.
- [ ] Encode dependencies, choices, tristate logic, select/imply, defaults, and
  architecture constraints for the qualified subset.
- [ ] Represent strings/integers and unresolved domains explicitly; do not silently
  turn all `CONFIG_*` names into Boolean/tristate symbols.
- [ ] Define Make condition `P(file)` and validity model `K`; query `K ∧ P(file)`.
- [ ] Distinguish satisfiable Make assignments from valid configurations that can
  actually be produced by Kconfig.
- [ ] Generate witness configurations, normalize through Kconfig, and recheck
  that normalization preserves the intended object condition.
- [ ] Partition preparation when generated content depends on configuration;
  record which partitions were analyzed and what remains unexplored.
- [ ] Provide explicit Make-only mode when constraints are unavailable, with
  qualified dead-file and witness results.

Acceptance: an example reachable in Make but impossible under Kconfig is rejected;
a valid witness survives normalization and selects the expected object.

## P6. Durable results, incremental analysis, and queries

Proposed run directory:

```text
results/linux/
  manifest.json          # immutable input identity and execution scope
  status.json            # stage, progress, interruption/failure state
  summary.json           # counts, qualification, timing, memory
  results.sqlite         # or documented equivalent indexed store
  objects.jsonl          # streaming interchange export
  diagnostics.jsonl
  commands.jsonl         # command provenance/replay references
  coverage.json
  checkpoints/
  artifacts/             # generated-input and optional oracle evidence
```

- [ ] Decide on SQLite binding versus append-only segments plus indexes using a
  concrete Lean prototype, portability requirements, and measured query costs.
- [ ] Version every persisted schema and reject or migrate incompatible caches.
- [ ] Store path, symbol, formula, environment/context, object, source-location,
  diagnostic, command, dependency, and provenance tables with explicit IDs.
- [ ] Index objects by path/kind/context, options by mentioning guard, diagnostics
  by code/location, and dependencies by reverse-consumer relation.
- [ ] Persist shared guard DAGs once; export human-readable conditions lazily.
- [ ] Stream records in bounded batches; avoid requiring a giant JSON array in RAM.
- [ ] Checkpoint queue, visited states, pending guards, completed inputs, dictionary
  IDs, effects, and solver reconstruction metadata at consistent transaction points.
- [ ] Recover after interruption using atomic writes/transactions and checksums;
  never load a half-written report as a successful cached analysis.
- [ ] Replace broad heuristic fingerprints with dependency-aware content digests:
  includes, arbitrary files read, wildcard directory membership, generated inputs,
  settings, toolchain, environment, effect outputs, and analyzer semantic version.
- [ ] Invalidate dependents transitively; account for newly created files that can
  change wildcard matches and previously missing includes.
- [ ] Test resumed versus uninterrupted results for semantic equivalence.
- [ ] Query file conditions, controlling options, witness configurations,
  affected files, diagnostics, and provenance without loading the full report.
- [ ] Diff two runs only after checking compatible architecture/configuration
  scope; use formula equivalence rather than string equality.
- [ ] Document retention and cache cleanup; never remove user source trees.

Acceptance: interrupt a large run, resume it, and obtain equivalent results;
editing an included file invalidates consumers while unrelated work is reused.

## P7. Examples as tests and paper material

Each example should have one source of truth under `Tests/Examples/<id>/`:
Make/Kbuild inputs, optional Kconfig/config, expected semantic assertions,
execution context, oracle procedure, and a short explanation. Produce paper
snippets and output extracts from these fixtures to prevent documentation drift.

| ID | Challenge | Required test and paper lesson |
| --- | --- | --- |
| E01 | `obj-$(CONFIG_X)` | Boolean/tristate selection and target kind |
| E02 | Parent and child guards | Nested membership uses conjunction |
| E03 | `:=`, `=`, `+=`, `?=` | Flavor, timing, and overwrite effects |
| E04 | Computed names and composite members | Distinguish helper values and reachable objects |
| E05 | `define`, `call`, `foreach`, `eval` | Double expansion and generated assignments |
| E06 | Effects inside lazy branches | Unselected branches cannot mutate state/run commands |
| E07 | Shell architecture/toolchain probe | Environment-relative conditions and recorded provenance |
| E08 | Config-dependent shell/file generation | Partition contexts; detect cross-branch contamination |
| E09 | Guarded `error` | Termination removes only the affected execution paths |
| E10 | Include plus generated include | Preparation and dynamic dependency invalidation |
| E11 | Wildcards and file additions | Filesystem-sensitive cache invalidation |
| E12 | Kconfig dependency/choice | Make-reachable versus valid-config reachable |
| E13 | Root aggregate/architecture guard | Flat subtree inventory is not root reachability |
| E14 | Unreachable object and orphan source | Evidence required before calling a file dead |
| E15 | Repeated states and formulas | Sharing, incremental SAT, and bounded memory |
| E16 | Target-specific/inherited variables | Invocation context affects target membership |
| E17 | Interrupted analysis | Resume is equivalent to uninterrupted execution |

- [ ] For each example, enumerate all small-domain configurations and compare
  predicted selections against an appropriate GNU Make oracle.
- [ ] Add adversarial cases: cycles, repeated effects, missing includes, invalid
  generated syntax, huge expansions, aliasing, and resource limits.
- [ ] Ensure oracle tests use independent expected behavior rather than repeating
  the analyzer's target extraction algorithm.
- [ ] Attribute real-source reductions with release, original file, and license;
  prefer small original fixtures when equivalent teaching value is possible.
- [ ] Create `paper/examples/<id>.md` with problem, code, intended conditions,
  implementation idea, evidence, and remaining limitation.
- [ ] Add a script that checks/regenerates paper result snippets from test outputs.

## P8. Real-build evaluation and useful analyses

- [ ] Choose complete pinned Linux and BusyBox releases and archive source digests.
- [ ] Cover x86 and arm64 where toolchains are available; include minimal,
  representative default, module-heavy, and seeded random valid configurations.
- [ ] Acquire independent compilation/link evidence from clean builds: command
  records, dependency files, and archive/module membership, not only `.o` files
  left on disk. Exclude stale artifacts and classify generated/host objects.
- [ ] Compare actual selection to predictions under the same config and environment.
- [ ] Report false positives/negatives by semantic cause and completeness scope.
- [ ] Reproduce discrepancies as small E-series fixtures before changing semantics.
- [ ] Measure cold/warm download, extraction, preparation, analysis, solving,
  serialization, querying, and optional validation separately.
- [ ] Record repeated-run distributions, peak memory, analyzed file count, unique
  object count versus object/kind records, guard sizes, effects, and diagnostics.
- [ ] Benchmark optimizations independently: reduction, merging, interning,
  formula DAGs, solver changes, caching, and resume.
- [ ] Implement dead-file candidates only with a candidate inventory and scope
  proof: absent output alone cannot establish deadness because infeasible entries
  may have been pruned or relevant inputs may be unmodeled.
- [ ] Map objects to sources using modeled rules/provenance; `.o` to `.c` string
  substitution alone misses assembly, composites, and generated sources.
- [ ] Check deadness via unsatisfiability of `K ∧ P(file)` and report evidence;
  classify incomplete/unknown cases separately from proven unreachable cases.
- [ ] Add configuration impact, release/refactoring diff, witness generation,
  and build coverage queries, each with validated case studies.
- [ ] Treat security exposure as build inclusion evidence only; do not infer
  runtime reachability or vulnerability from presence conditions alone.

## P9. CLI delivery and release qualification

- [ ] Implement `analyze`, `resume`, `query`, and `diff` commands with stable help.
- [ ] Route legacy CLI usage compatibly or provide clear migration guidance.
- [ ] Make stage progress readable on stderr and machine output stable on stdout.
- [ ] Emit results even for incomplete runs and list exact unresolved inputs/effects.
- [ ] Show selected architecture, environment, configuration scope, and resolved
  release early; print report directory and qualification at completion.
- [ ] Add dependency/version checks and actionable failures for offline hosts,
  missing compilers, invalid archives, unsupported releases, and exhausted storage.
- [ ] Pin full integration tests; keep latest-release compatibility tests separate
  so upstream changes do not make normal unit tests nondeterministic.
- [ ] Run a clean end-to-end URL demonstration from download through query.
- [ ] Record one interrupted/resumed demonstration and one concrete-build comparison.
- [ ] Update `README.md`, `SUPPORTED.md`, `MIGRATION.md`, this checklist, and paper notes
  to match implemented capabilities and qualified scope.

## Paper work and evidence ledger

- [ ] Revise `paper/NOTES.md` to make Linux the principal goal and dynamic effects
  an intended technique; distinguish implemented features from proposed applications.
- [ ] Explain conditions relative to architecture/toolchain and Kconfig validity.
- [ ] Avoid calling execution or diagnostics proof of soundness; specify assumptions.
- [ ] Use E02/E05/E08/E12/E13 as candidate running examples for traversal,
  generated syntax, dynamic effects, configuration validity, and root reachability.
- [ ] Add data-structure design and ablation measurements to the implementation section.
- [ ] Maintain an evidence ledger linking each numerical/paper claim to a run
  manifest, source revision, analyzer revision, command, and generated artifact.
- [ ] Research related work separately with primary-source citations before making
  novelty or comparative performance claims.
- [ ] Track proofs independently: formula transformations, CNF equisatisfiability,
  solver correctness, pruning/merging, reduction, and guarded effect semantics.
- [ ] State which guarantees are proved, exhaustively tested, empirically validated,
  assumed from external tools, or unresolved.

## Migration obligations retained from the retired checklist

- [ ] Prove normalization preserves formula evaluation, including conjunction,
  disjunction, negation, and canonicalization.
- [ ] Define executable literal/clause/CNF semantics and prove finite-domain
  exactly-one constraints, CNF equisatisfiability, and DPLL simplification correct.
- [ ] Prove solver soundness and completeness or implement checked certificates;
  use exhaustive small-formula tests as supplementary evidence.
- [ ] Prove branch coverage, feasible-path preservation, equivalent-state merging,
  contribution splitting/masks, and guarded computed-variable overwrites.
- [ ] Prove dependency reduction preserves target, include, conditional, computed
  name, and effect dependencies. Keep proof holes explicitly tracked.
- [ ] Add normalized AST differential tests against `tools/pymake_ast.py` and
  presence-condition comparisons with the archived Python analyzer.
- [ ] Cover operator-modified `define` forms and corpus `config_filename` and
  `allow-override` macros when extending generated-syntax semantics.
- [ ] Round-trip all persisted semantic fields, including guards and provenance.
- [ ] Archive differential evidence before moving/removing the Python reference;
  retain Mozilla provenance/license and do not substitute the unrelated PyPI pymake.
- [ ] Audit migration M5–M7 criteria in `MIGRATION.md` against the new hybrid
  scope before claiming migration completion; distinguish analyzer dependencies
  from explicitly invoked external preparation and validation tools.

## First implementation sprint

- [ ] P0: archive baseline and define report qualification/context types.
- [ ] E02/E05/E06/E09/E13: write minimal fixtures and independent oracle assertions.
- [ ] P3: implement stateful expansion, ordered `eval`, and guarded termination.
- [ ] P1: implement explicit archive URL acquisition and immutable workspace manifest.
- [ ] P4: analyze a complete pinned x86 Linux root with preserved invocation context.
- [ ] P3: add command execution/replay with explicit environment and dependency scope.
- [ ] P2/P6: prototype interned guard/path storage and streaming export; benchmark it.
- [ ] Integrate, rerun evidence, and update this checklist before expanding features.

Sprint exit: a reproducible complete-source run with actual root context,
tested generated-Make semantics, explicit execution assumptions, and a report
that identifies remaining gaps. This is an intermediate milestone, not the final
claim of complete Linux support.
