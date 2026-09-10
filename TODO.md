# Lean Migration Continuation Checklist

This file is the handoff checklist for continuing the Python-to-Lean migration.
Read `MIGRATION.md` for the architectural plan and `SUPPORTED.md` for the
language matrix. Work only from the `dev` branch; it is the canonical branch.

## Safe checkpoint (2026-09-10)

- [x] Production CLI, parser, symbolic evaluator, finite-domain CNF/DPLL
  solver, recursive traversal, reports, configuration selection, coverage, and
  cache are native Lean 4.
- [x] The production executable does not invoke Python, `pymake3`, Z3, Make,
  recipes, or shell commands.
- [x] The native parser accepts all 2,158 checked-in Makefile/Kbuild files.
- [x] `make check` builds both executables, runs Lean unit and end-to-end tests,
  analyzes the full 2,158-file corpus in one process, and runs
  `git diff --check`.
- [x] Recursive tristate analysis of `tests/linux/linux_orig/drivers` completes
  in about six seconds on the development host and emits 30,086 conditional
  file-presence records.
- [x] Generated paths are lexically canonicalized before lookup.
- [x] Multi-line `define` blocks are native recursive variable definitions.
- [x] Conditional directives preserve recipe context, preventing nested recipe
  commands from being misclassified as top-level expressions.
- [x] `warning` and `info` expand their arguments and return an empty value;
  their output-only side effect is intentionally suppressed.
- [x] Batch JSON contains `diagnostic_codes` and source-located
  `diagnostic_details` for every input.

Latest relevance-aware full-corpus result:

- 2,158 inputs analyzed;
- 74 diagnostics across 27 files;
- 22 `SKB1003` unsupported-function diagnostics: eight `shell`, eight `error`,
  and six `eval`;
- 18 `SKB1004` genuinely top-level expansion/side-effect diagnostics;
- 34 `SKB2003` required includes absent from the historical fixture snapshots.

The 18 `SKB1004` sites are not generic recipe noise. They are top-level
`error`, `eval`, `foreach`/`if` wrappers, and `call allow-override` expressions
whose macros contain `eval`. Keep them incomplete until their side effects are
modeled or a precise proof shows they cannot affect observed build lists.

## Resume commands

```sh
git status --short
make check

find tests -type f \( -name Makefile -o -name Kbuild \) -print0 \
  | xargs -0 .lake/build/bin/skbuild --tristate --batch-check --json \
  > /tmp/skbuild-batch.jsonl

python3 -c 'import json,collections; rows=[json.loads(x) for x in open("/tmp/skbuild-batch.jsonl")]; c=collections.Counter(d["code"] for r in rows for d in r["diagnostic_details"]); print(len(rows), sum(bool(r["diagnostics"]) for r in rows), sum(c.values()), dict(c))'

.lake/build/bin/skbuild --tristate --json \
  tests/linux/linux_orig/drivers > /tmp/skbuild-drivers.json
```

Expected corpus summary at this checkpoint:

```text
2158 27 74 {'SKB1003': 22, 'SKB1004': 18, 'SKB2003': 34}
```

Expected drivers summary: 30,086 files and 41 diagnostics (13 missing includes,
28 referenced directories absent from the fixture). The CLI also prints those
diagnostics to stderr.

## Priority 1: top-level expansion and `eval`

- [ ] Specify the supported top-level expansion semantics before coding.
- [ ] Implement a state-transforming evaluator for top-level expressions; the
  current pure expression expander cannot represent assignments emitted by
  `eval`.
- [ ] Support the corpus-required `eval` subset: expand its argument, parse the
  resulting Make syntax, and execute generated assignments at the current
  sequence point.
- [ ] Preserve guards when `eval` occurs inside `if`, `foreach`, or a macro
  reached through `call`.
- [ ] Ensure generated statements participate in dependency tracking and
  guarded overwrite semantics.
- [ ] Add focused tests using the corpus patterns `config_filename` and
  `allow-override` before enabling the feature generally.
- [ ] Model top-level `error` as a guarded build-stopping path or retain
  `SKB1003`; never silently treat it as an empty harmless value.
- [ ] Keep `shell` disabled by default. If its result affects an observed
  target, retain an incomplete diagnostic; do not execute ambient commands.
- [ ] Re-run the full batch census and update this file, `MIGRATION.md`, and
  `SUPPORTED.md` after each diagnostic class is retired.

Important architecture constraint: importing `Skbuild.Parser` from
`Skbuild.Expansion` creates a module cycle. Put parsing/execution of generated
syntax in `Skbuild.Semantics` or a new orchestration module above both parser
and expansion.

## Priority 2: solver proofs and certificates

- [ ] Prove smart normalization preserves `Formula.eval` for `neg`, `conj`,
  `disj`, and canonical normalization. `eval_neg` and `eval_toNNF` already
  exist.
- [ ] Define executable evaluation for `Literal`, `Clause`, and `CNF` and prove
  raw CNF conversion preserves evaluation.
- [ ] Prove finite-domain exactly-one constraints characterize configured
  domains, including atoms whose values are outside the domain.
- [ ] Prove `Formula.toCNF` is equisatisfiable with the source formula under the
  finite-domain model.
- [ ] Prove DPLL simplification preserves satisfiability under the selected
  literal split.
- [ ] Prove solver soundness; then prove completeness or emit/check a
  certificate.
- [ ] Add exhaustive property tests over small generated formulas as a
  regression supplement, not a replacement for proofs.
- [ ] Replace the current distributive CNF conversion with Tseitin encoding if
  benchmarks show formula blow-up; prove the new encoding equisatisfiable.

Do not add `sorry` except in explicitly tracked proof scaffolding. The current
tree should remain free of untracked proof holes.

## Priority 3: symbolic-execution invariants

- [ ] Prove a conditional split covers exactly the incoming models.
- [ ] Prove pruning an unsatisfiable guard preserves all feasible executions.
- [ ] Prove merging equal environments by disjoining guards preserves the
  represented model set.
- [ ] Prove contribution-word splitting, the explicit empty alternative, and
  contribution masks preserve target-value semantics.
- [ ] Prove guarded overwrite behavior for computed helper variables.
- [ ] Prove dependency reduction cannot remove assignments affecting targets,
  includes, conditions, computed names, or relevant functions.
- [ ] Add differential/exhaustive tests for each invariant while proofs are in
  progress.

## Priority 4: parser and GNU Make parity

- [ ] Differentially compare normalized native ASTs with
  `tools/pymake_ast.py` over focused fixtures, then the selected corpora.
- [ ] Extend `define` parsing for operator-modified forms (`define NAME :=`,
  etc.) if new corpus evidence requires them; the checked-in corpus uses plain
  recursive definitions.
- [ ] Audit target-specific assignments (`SKB1001`) and implement the subset
  that can affect Kbuild presence.
- [ ] Audit dynamically generated include names and optional includes.
- [ ] Decide whether a safe, injected command-result map should support
  selected `shell` calls without ever executing commands.
- [ ] Improve captured `realpath` semantics for symlinks or document lexical
  identity as the permanent scope boundary.
- [ ] Reject JSON inputs in `--batch-check` (already implemented) and retain
  JSON AST input only as a migration/reference path.

## Priority 5: cache, traversal, and reporting

- [ ] Add continuation/checkpoint support; the current schema-2 cache stores a
  complete result only.
- [ ] Prove or round-trip-test cache serialization for all semantic fields.
- [ ] Keep cache invalidation sensitive to Make input contents, settings, and
  captured filesystem path names.
- [ ] Measure stable peak memory and output size for recursive Linux drivers.
- [ ] Compact canonical formula/report output without changing evaluation.
- [ ] Validate recursive traversal on BusyBox and additional top-level Linux
  subtrees.
- [ ] Distinguish missing files caused by fixture truncation from dynamically
  generated required includes in qualification reports.

## Priority 6: parity evidence and cutover

- [ ] Produce normalized AST differential evidence against `pymake3`.
- [ ] Produce presence-condition differential evidence against the archived
  Python analyzer for representative fixtures.
- [ ] Validate predictions against representative real `.config` and build
  directories.
- [ ] Establish checked-in performance thresholds that are robust across CI
  hosts.
- [ ] Move or remove the Python implementation only after differential evidence
  is archived; until then it is reference/test code, not production code.
- [ ] Confirm packaging contains no runtime Python, `pymake3`, or Z3 dependency.
- [ ] Complete every M5-M7 exit criterion in `MIGRATION.md` before declaring
  the migration finished.

## Branch and pymake administration

- [x] Local `master` was deleted; local work is on `dev`.
- [x] The local `origin/master` remote-tracking ref was removed and
  `origin/HEAD` points to `dev`.
- [ ] Delete the remote GitHub `master` branch after changing the repository's
  default branch to `dev`. This remains externally blocked because the saved
  GitHub credentials are invalid and GitHub refuses deletion of the default
  branch.
- [x] `src/pymake3` is the Python 3 port of Mozilla pymake's final upstream
  revision `034ae9ea5b726e03647d049147c5dbf688e94aaf` (2014-07-08).
- [x] Provenance and license are recorded in `src/pymake3/UPSTREAM.md` and
  `src/pymake3/LICENSE`.
- [ ] Do not replace it with the unrelated PyPI/conda package named `pymake`.

## Working-tree precautions

The migration is currently an uncommitted working tree with many new files and
a few modifications to the archived Python reference. Treat all existing
changes as intentional. Do not reset, checkout, clean, or overwrite them.
Use `apply_patch` for edits, keep unrelated files untouched, and run
`make check` plus `git diff --check` before every handoff.
