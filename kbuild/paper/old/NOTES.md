# skbuild paper notes

## Updated outline revision (2026-09-24)

The current `skbuild.tex` follows the updated
`~/git/mydocs/priv/outline.md`. Its first technical section is an Overview
with the pipeline and a worked Makefile trace. The Technique section opens
with the selection model and a numbered end-to-end algorithm covering guarded
state execution, conditional directory traversal, and formula aggregation.
The prose refers to its actual line numbers and gives intermediate guards for
both the assignment and shared-directory examples. The introduction previews
the physical-path results, and the abstract uses the exact overlap range.

The principal evidence remains the September 24 JSON and manifest named in
the claim record below. This revision adds no new experiment or build claim.
The algorithm summarizes the runner plus its extraction interface: the runner
persists restricted Makefile instances, and the interface aggregates paths.
The manuscript now states that file-read errors may result in empty parsed
content. The source has been mirrored to `paper.tex` with its matching
bibliography. Both PDFs render to 20 pages under
`acmsmall,screen,review`.

## Long manuscript handoff (2026-09-24)

`skbuild.tex` is the 20-page manuscript; `skbuild.bib` and
`skbuild.pdf` match it. `paper.tex` is a second copy of the long draft.
The manuscript follows `~/git/mydocs/priv/outline.md`.

The expanded paper adds the concrete guard and directory examples, a pipeline
figure, implementation and semantic-boundary details, a reproducible evaluation
protocol, separate physical and local GNU Make comparisons, discrepancy case
analysis, related work, and a two-part appendix. It uses the September 24 rerun
JSON files and manifest listed below. No new build result is introduced by the
expansion. The most consequential implementation qualifications are that
symbolic `include` execution is absent, `$(shell ...)` executes a host command,
`+=` expands immediately even for recursive variables, and the guarded word
map loses order and duplicates.

Author review should focus on the target-unit interpretation of the large
Linux/coreboot outside-universe sets, the incomplete U-Boot/coreboot builds,
the unvalidated Kconfig witness work, and whether the venue's page convention
counts the appendix and bibliography. The rendered document is 20 pages under
the current `acmsmall,screen,review` class.

## Rerun and manuscript handoff (2026-09-24)

The manuscript follows `~/git/mydocs/priv/outline.md`. The current claim record
is below. The remaining notes after this section are historical brainstorming;
they do not describe the Python implementation or current results reliably.

| Manuscript claim | Evidence | Scope |
| --- | --- | --- |
| Linux physical-object comparison across four profiles | `results/linux_four_profile_revalidation_20260924.json` | 13,841 extracted target paths. Tinyconfig is i386; defconfig is x86-64. Both physical archives were exactly reproduced by clean GCC 12 builds. Debian and allmodconfig objects remain archived data, without a fresh build this turn. The table separates observed paths outside the extracted set. |
| Non-Linux physical-object comparison | `results/archived_build_revalidation_20260924.json` | The corrected validator substitutes all formula variables. The previous 18.3% and 1.1% Barebox and U-Boot recalls were caused largely by incomplete substitution. Fresh Barebox output exactly reproduced 406 archive objects. Fresh U-Boot compilation reproduced 1,123 archived objects and 81 more before packaging failed. Coreboot's archived ROM build is partial. |
| Linux local GNU Make comparison | `results/linux_four_profile_revalidation_20260924.json` | Per-file expansion is not a whole-build oracle; tinyconfig recall is 30.7% because files in unreachable directories are evaluated locally. |
| Five-corpus traversal, census, and timing | `results/all_corpora_results.json`, `results/linux_tristate_revalidation_20260924.json`, `evidence/manifest.json` | Linux commit and two Makefile edits recorded. 71,292 syntactic construct occurrences; classifications are not semantic validation. No controlled cross-tool speed claim. |

Remaining work before a strong whole-build claim: classify the 313--14,436
Linux physical paths outside the extracted set by artifact type; integrate
top-level U-Boot `libs-y` selection (the 12 within-set USB misses); triage
U-Boot's other 231 outside-set paths and the 430 coreboot outside-set paths;
rebuild Debian/allmodconfig and complete U-Boot/coreboot final artifacts; and
validate Kconfig-aware witnesses through real configurators and builds.
The Barebox firmware anomaly remains unverified and is not a paper claim.


## One-sentence summary

skbuild symbolically executes the Kbuild-relevant subset of GNU Make to infer
the configuration condition under which every object file and subdirectory can
participate in a Linux-style build.

## Problem and motivation

Large configurable systems such as the Linux kernel and BusyBox describe their
builds with Makefiles and Kbuild files.  A build under one `.config` answers a
narrow question: which files were selected for that one configuration?  It does
not directly answer how the build varies across the configuration space.

The build description contains that information, but it is difficult to recover
reliably.  Kbuild target names, variable values, includes, and directory
traversal are themselves conditional.  A useful analysis must therefore track
both the value produced by Make evaluation and the condition under which that
value was produced.

The central question is:

> For each object file, what configurations can cause it to participate in the
> build, and through which Kbuild path does it become reachable?

## Goal

The goal of skbuild is to construct a conservative *variability-aware build
map*.  Each reported object is paired with a presence condition over Kconfig
symbols and other finite-domain build options.

For example, given:

```make
obj-$(CONFIG_USB) += usb.o

ifeq ($(CONFIG_DEBUG),y)
obj-y += debug.o
endif
```

skbuild should report:

```text
usb.o    built-in  CONFIG_USB=y
debug.o  built-in  CONFIG_DEBUG=y
```

The condition is the important output.  It says more than whether a file is
present in a particular build: it characterizes the configurations that select
the file.

## Approach: symbolic execution of Kbuild Makefiles

skbuild does not run a build.  It parses and symbolically evaluates the part of
GNU Make/Kbuild that can affect the build graph.

- A symbolic state contains Make variables and a path condition.
- Assignments update variables under the current path condition.
- `ifeq`, `ifneq`, `ifdef`, and `ifndef` fork execution into guarded paths.
- Paths with unsatisfiable conditions are pruned using finite-domain reasoning.
- Equivalent symbolic states are merged by disjoining their path conditions.
- Kbuild target assignments such as `obj-y`, `obj-m`, `lib-y`, and configured
  project-specific prefixes are extracted as object and directory contributions.
- Directory contributions cause recursive analysis of the corresponding
  `Kbuild` or `Makefile`.
- Includes, variable expansion, common Make functions, and filesystem-sensitive
  operations such as `wildcard` are evaluated from a captured source-tree view.

The final report merges all paths that can select the same object.  In this
sense, skbuild is a symbolic executor specialized for build descriptions rather
than for ordinary program control flow.

## What skbuild reports

The primary report has one record per object/target-kind pair:

```text
<relative object path>  <built-in | module | library>  <presence condition>
```

JSON output additionally records the schema version, structured conditions,
source-located diagnostics, and whether the analysis is complete.

Useful modes include:

- Boolean or tristate Kconfig domains (`y`, `m`, and not set).
- Custom finite domains, for values such as word size or architecture choices.
- Concrete `.config` filtering to select the predicted objects for one
  configuration.
- Comparison of predicted objects with a build directory.
- Detection of source files not accounted for by the analyzed Kbuild graph.
- Persistent result caching and batch analysis for large source trees.

## Why conservative diagnostics matter

Some Make operations depend on the host environment or can generate new Make
syntax.  Examples include `$(shell ...)`, `$(eval ...)`, top-level side effects,
and build-stopping `$(error ...)` calls.  Executing them would make results
non-reproducible and could execute untrusted commands.

skbuild instead reports a diagnostic and marks the result incomplete when such
an operation may affect the observed build graph.  Thus, a result is either a
qualified conservative analysis or explicitly not a completeness claim; it is
never silently presented as a complete build graph after ignoring relevant Make
behavior.

## Potential analyses and applications

### Dead and unreachable files

- Identify objects whose presence condition is unsatisfiable under the selected
  configuration domains.
- Find source files that are never reached by the Kbuild graph.
- Find objects that appear in Kbuild files but cannot be selected by any valid
  Kconfig assignment.
- Separate genuinely unreachable files from files omitted because an analysis is
  incomplete or a source snapshot is partial.

### Configuration understanding

- Explain which configuration options control a particular file.
- Find every file affected by changing an option such as `CONFIG_USB`.
- Compare the build footprints of two configurations without compiling either.
- Discover options that have identical or overlapping build impact.
- Detect option combinations that select conflicting, duplicate, or surprising
  object sets.

### Build-system maintenance

- Detect missing Kbuild entries for source files.
- Detect predicted objects missing from a concrete build directory.
- Detect built objects not predicted by the analyzed Kbuild graph.
- Find dangling subdirectory references and missing included Makefiles.
- Audit whether a Kbuild refactoring preserves the symbolic object map.

### Testing, evolution, and security

- Generate targeted configuration tests that exercise a file or directory.
- Prioritize configuration sampling using rare or complex presence conditions.
- Compare symbolic build maps between releases to identify build-graph changes.
- Review which configuration choices expose code in a subsystem.
- Provide a reproducible, no-recipe-execution view of a third-party build graph.

### Research questions

- How much of a real Kbuild corpus can be analyzed completely without executing
  shell commands?
- Which GNU Make constructs are most responsible for incomplete analyses?
- How many files are conditionally reachable, and how complex are their
  presence conditions?
- Can symbolic reports reveal stale Kbuild entries, dead files, or configuration
  inconsistencies that ordinary builds miss?
- How closely do predicted object sets agree with concrete builds across a
  representative configuration sample?

## Current implementation notes

- The production CLI, parser, symbolic evaluator, solver, traversal, cache, and
  reporting are native Lean 4.
- Recipes and rules are preserved or parsed as needed but are never executed.
- The checked-in BusyBox snapshot is configured for whole-snapshot traversal.
  A current tristate run reports 588 object records in roughly 0.1 seconds on
  the development machine, while remaining incomplete because its root Makefile
  uses unsupported host-dependent operations.
- The checked-in Linux snapshot is configured to start from its top-level
  Kbuild subtrees.  A current tristate run reports more than 40,000 conditional
  object records.  Its report is incomplete where the historical snapshot lacks
  generated paths or uses unsupported side-effecting Make behavior.
- The recursive evaluator supports a bounded subset of `$(eval TEXT)`, including
  direct and guarded statements plus eval nested in `if`, concatenation, and
  called macro bodies, by parsing and executing generated assignments at the
  current sequence point.  This subset is tested independently; generated rule
  semantics, depth/termination bounds, and command execution remain outside
  the supported scope.

These are implementation measurements, not yet paper-quality benchmark claims.
They should be reproduced on a documented machine and configuration before
being used in an evaluation.

## Candidate paper structure

1. **Introduction** — configurable build systems, the limits of one-config
   builds, and the presence-condition question.
2. **Background** — Kbuild, GNU Make evaluation, Kconfig Boolean/tristate
   options, and variability-aware analysis.
3. **Design** — symbolic states, guarded assignments, branching, merging,
   traversal, and diagnostics.
4. **Implementation** — Lean architecture, parser/evaluator support matrix,
   native solver, captured filesystem model, and cache.
5. **Evaluation** — unit/golden tests, Linux and BusyBox corpus coverage,
   performance, diagnostic census, and concrete-build agreement.
6. **Applications** — dead-file detection, build-graph diffing, configuration
   explanation, and coverage validation.
7. **Limitations and threats to validity** — unsupported Make effects, partial
   source snapshots, finite-domain assumptions, and configuration modeling.
8. **Related work** — variability analysis, symbolic execution, build-system
   analysis, and Linux configuration tooling.
9. **Conclusion** — a conservative, reproducible symbolic build map.

## Evaluation checklist

- [ ] Record exact Linux and BusyBox source revisions and snapshot provenance.
- [ ] State the hardware, Lean version, and command line for every timing.
- [ ] Measure wall-clock time, memory, number of parsed/analyzed files, object
  records, unique conditions, and diagnostics by code.
- [ ] Compare selected `.config` predictions with actual object files from
  clean builds.
- [ ] Manually investigate a sample of reported dead/unaccounted files.
- [ ] Compare release-to-release reports to find and validate real build-graph
  changes.
- [ ] Distinguish incompleteness caused by the analyzer from incompleteness
  caused by intentionally sparse historical snapshots.
- [ ] Include examples where symbolic conditions simplify non-obvious Make
  control flow into a useful explanation.

## Writing cautions

- Do not claim GNU Make compatibility; the intended scope is the
  Kbuild-relevant subset.
- Do not call an incomplete report a complete build graph.
- Do not describe the tool as a build executor: it never runs recipes, Make,
  shell commands, or compilers in production analysis.
- Treat dead-file findings as candidates until source/build validation rules out
  generated files, architecture-specific paths, and incomplete-analysis effects.
