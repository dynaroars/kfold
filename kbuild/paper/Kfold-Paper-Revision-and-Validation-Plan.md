# kfold Paper Revision and Validation Plan

## Mission

Revise the current kfold manuscript into a credible empirical software-engineering/tool paper suitable for FSE or ICSE.

The paper must make fewer, defensible claims. Its core contribution should be an implementation and empirical study of a variability-aware Kbuild analyzer, not a new formal semantics. Correctness evidence, comparison with prior work, valid configuration handling, and reproducibility take priority over adding applications or polishing prose.

## Non-negotiable instructions

1. **Discard the formalism as a claimed contribution.** Remove the operational-semantics figure, inference rules, guarded algebra presented as a formal calculus, and any claim of a formal, rigorous, sound, or exact semantics.
2. Keep only enough technical background to explain the implementation intuitively. A short design section may describe guarded values, branch merging, overwrite handling, and directory traversal using examples and pseudocode.
3. Do not use the words **exact**, **sound**, **complete**, **guaranteed**, **provably correct**, **strictly bounded**, **eliminates path explosion**, or **minimal** unless a specific theorem or experiment truly supports the statement. Prefer concrete and scoped language.
4. Never describe a Make-local condition as a valid Kconfig configuration unless Kconfig constraints are incorporated and the resulting configuration is accepted by the real configurator/build.
5. Do not hide bad results using phrases such as “up to 99%.” Report the full range and explain every major failure category.
6. Do not invent results, citations, explanations, maintainer confirmations, issue links, hardware details, or artifact contents. Mark missing evidence as TODO and collect it.
7. Do not ask an LLM to fill numerical tables or bibliography entries from memory. Generate tables from saved raw data and verify citations against publisher or author pages.
8. Every number in the abstract and prose must be generated from, or checked against, the final tables.

## Recommended paper identity

Frame the work approximately as follows:

> kfold is a practical variability-aware analyzer for a commonly used subset of Kbuild-style Makefiles. It represents alternative words with guards and merges conditional effects eagerly, allowing it to extract approximate Kbuild-level object-selection conditions efficiently across several large systems. We evaluate scalability, construct support, agreement with concrete builds, and selected downstream uses.

This framing deliberately avoids claiming a complete GNU Make semantics or globally exact build conditions.

Potential title:

> **kfold: Scalable Variability-Aware Analysis of Kbuild Makefiles**

Avoid “Constant-State” unless the paper carefully defines the metric and shows that symbolic value/formula growth is not being hidden behind a single state object.

## Phase 0: Freeze the current paper and create an evidence ledger

- Preserve the current manuscript as an archived draft.
- Create a branch specifically for the revision.
- Create `evidence/claims.csv` with these columns:
  - claim ID;
  - manuscript location;
  - exact claim;
  - required evidence;
  - current evidence source;
  - status: verified, qualified, removed, or TODO;
  - responsible script/test;
  - final wording.
- Add every abstract, contribution, performance, correctness, bug, coverage, and application claim to the ledger.
- Create one machine-readable experiment manifest recording:
  - exact repository URL and commit for each subject;
  - exact architecture/board/defconfig;
  - host OS, CPU, RAM, Python, Z3, compiler, and Make versions;
  - command lines;
  - timeout and memory limits;
  - random seeds;
  - output paths and hashes.
- Do not rewrite the abstract until the experiments and tables are final.

### Exit criterion

Every quantitative claim in the current manuscript is present in the ledger and linked to either evidence or a removal task.

## Phase 1: Repair and appropriately position related work

Preserve double-blind anonymity. Do not call the 2020 ICSME work “our prior work,” do not describe kfold as a continuation of it, and do not discuss author or code lineage. Cite it neutrally as Nguyen and Nguyen's earlier symbolic-execution approach to Kbuild.

- Correct its bibliographic entry:
  - authors: ThanhVu Nguyen and KimHao Nguyen;
  - venue: ICSME 2020;
  - pages: 712-716;
  - exact published title and verified DOI/bibliographic metadata.
- Discuss it briefly in the ordinary related-work section together with Kmax, Undertaker/GOLEM, KBuildMiner, Makex, and SyMake.
- Keep the comparison technical and concise. Explain that the 2020 paper explored path-based symbolic execution and proposed merging/split-merge ideas, whereas this submission evaluates a guarded-value eager-merge implementation at substantially greater scale and across additional systems. Do not imply shared authorship.
- Do not add a dedicated “relationship to our prototype” subsection or a provenance discussion.
- Do not overemphasize the 2020 paper in the introduction or contribution list.
- Still ensure the novelty statement is factually defensible: guarded overwrites, branch merging, cross-system support, validation scope, and applications must be described in relation to the full body of prior work rather than claimed as unprecedented.
- Compare directly with Kmax where feasible. If an executable comparison is not feasible, compare capabilities and limitations using verified published evidence, and state that this is not an experimental comparison.
- Treat Cybolic as related work on eager-merge analysis in another build language. If it is an anonymous contemporaneous submission, follow the venue's double-blind citation policy and avoid identity-revealing wording.

### Exit criterion

Related work is cited accurately and neutrally, anonymity is preserved, and the paper's incremental advances are understandable without presenting kfold as a continuation of any named authors' system.

## Phase 2: Replace the formalism with a clear design section

Delete or radically simplify the current Sections 3 and 4.

### Remove

- “Formal Operational Semantics” from the contribution list.
- The inference-rule figure and claims of small-step semantics.
- The guarded-map algebra presented as a formal result.
- Complexity assertions such as `O(N * B)` unless derived and evaluated.
- Claims that one state implies constant memory or eliminates all combinatorial growth.
- “First-order Boolean/bit-vector logic” unless bit-vectors are genuinely implemented and evaluated.

### Retain as implementation design

Explain the following in ordinary technical prose:

1. **Guarded words.** A variable is represented by word alternatives paired with conditions.
2. **Assignment flavors.** Explain how immediate and deferred assignments are implemented.
3. **Conditional merge.** Show how values produced in each branch are re-guarded and combined.
4. **Guarded overwrite.** Use one small concrete example to show why an overwrite must preserve the previous value outside the assignment guard.
5. **Dynamic variable names.** Explain how alternatives for names such as `obj-$(CONFIG_X)` are expanded.
6. **Directory traversal.** Explain how a parent directory condition is combined with local target conditions.
7. **Composite objects and target families.** Explain the explicitly supported conventions.
8. **Approximations and unsupported behavior.** State these beside the design, not only in threats to validity.

### Required semantic audit

Before describing behavior, inspect the implementation and add tests for:

- preservation of word order;
- duplicate words;
- whitespace and empty expansions;
- branch-dependent variable flavors;
- `:=`, `::=`, `=`, `?=`, and `+=` for both defined and undefined variables;
- deferred recursive expansion after later variable updates;
- nested expansions and computed variable names;
- `ifeq`, `ifneq`, `ifdef`, and `ifndef` with empty/undefined values;
- `filter`, `filter-out`, `subst`, `patsubst`, `addprefix`, `addsuffix`, `call`, and `foreach`;
- includes and optional includes;
- target names appearing through multiple paths;
- directories reached under multiple conditions;
- cyclic include/directory cases;
- Boolean versus tristate values, including unset/empty behavior;
- `obj-y` versus `obj-m` outputs.

If the current map representation loses order or duplicates, either change it to an ordered guarded sequence or explicitly restrict the supported operations and report the approximation.

### Fix recursive traversal

Audit the `visitedDirs` logic. When a previously visited directory receives a broader incoming condition, the new condition must propagate to its targets and descendants. Implement a monotone worklist/fixed-point procedure or demonstrate that the analyzed directory graph has a unique-parent property. Add a regression test with a shared subdirectory reached under two independent guards.

### Exit criterion

The design section describes what the code actually does, all examples are executable regression tests, and no formal correctness claim remains.

## Phase 3: Decide the Kconfig strategy

There are two acceptable routes. Prefer Route A.

### Route A: Integrate Kconfig constraints

- Reuse a mature Kconfig constraint extractor where licensing and compatibility permit, such as Kconfiglib, Kclause, or project-native tooling.
- Form each actionable condition as:

  `Kconfig constraints AND architecture/board constraints AND kfold condition`.

- Generate configurations through the subject's real configuration workflow, for example `olddefconfig`, and then read back the normalized `.config`.
- Re-evaluate the target condition after normalization. Reject or repair a witness if normalization changes required values.
- Distinguish built-in `y`, module `m`, disabled/unset, string, integer, hexadecimal, choices, `select`, `imply`, and dependencies.
- Validate every generated witness by running the actual build or a documented target-discovery command.
- Record invalid, normalized-away, build-failing, timed-out, and successful configurations separately.

### Route B: Keep the analysis Kbuild-local

If full Kconfig integration cannot be completed reliably:

- Call the outputs **Kbuild-local object-selection conditions**.
- Remove CI-matrix generation, valid-configuration synthesis, and minimal-reproduction claims from the main contributions.
- Do not say a satisfying model will compile a target.
- Retain only analyses that remain valid under this scope, such as syntactic condition extraction, performance, and carefully qualified Make-local comparisons.

### Exit criterion

The paper either generates valid project configurations end to end or removes every claim that requires them.

## Phase 4: Rebuild ground-truth validation from scratch

The existing Table 7 cannot be retained without a complete redesign.

### Define the observation unit

For each subject and concrete configuration, record:

- predicted object set;
- observed compiled object set;
- intersection;
- false positives;
- false negatives;
- excluded generated, host-tool, architecture, stage, and duplicate-path objects;
- exact normalization rules mapping source paths to build paths.

Report both micro- and macro-averaged precision, recall, and F1. Do not mix unique objects, object/configuration pairs, and stage objects in the same row.

### Test suites

For each system, include:

- the standard `defconfig` or documented board configuration;
- several random valid configurations;
- targeted positive witnesses for rare targets;
- targeted negative configurations;
- architecture/stage-specific configurations where relevant.

Use exact versions and commits. Replace “Linux 6.x” with one or more reproducible releases/commits. Linux must be included in concrete validation because it is the flagship subject.

### Discrepancy triage

Create a CSV/JSON record for every false positive and false negative with:

- subject, configuration, predicted formula, and object;
- classification;
- evidence;
- whether the issue is in kfold, configuration normalization, build harness, path mapping, generated code, host utilities, unsupported Make semantics, or another cause;
- test or fix commit if applicable.

Manually audit a statistically meaningful sample of each category, plus all categories with large counts. Do not assert “zero symbolic logic errors” unless an independent oracle supports that conclusion.

### Required interpretation

If U-Boot remains near 24.4% precision and 0.6% recall, do not present it as successful support. Either fix the analyzer/harness or present U-Boot as a negative result defining the current tool boundary. Apply the same standard to Barebox's 7.6% recall and coreboot's roughly 47% recall.

### Exit criterion

All validation counts are reproducible from raw per-configuration files, and the prose openly reflects both strong and weak subjects.

## Phase 5: Replace the state-explosion experiment with meaningful comparisons

The fork-per-branch baseline may remain only as a motivating microbenchmark. It cannot be the primary baseline.

- Compare with:
  - Kmax on overlapping subjects/versions;
  - the published results of Nguyen and Nguyen's 2020 approach where a fair executable comparison is possible without compromising anonymity;
  - an ablated kfold implementation without eager guarded merging;
  - optionally alternative guarded representations if available.
- Include adversarial synthetic families for:
  - sequential independent branches;
  - deeply nested branches;
  - many guarded alternatives in one variable;
  - cross-products between symbolic variable names and values;
  - large formula growth;
  - repeated merges and overwrites;
  - shared-directory fixed points.
- Measure:
  - wall time;
  - peak RSS;
  - number of guarded alternatives;
  - total and maximum formula AST size;
  - number and duration of solver queries;
  - cloning/merge time;
  - simplification time.
- Run multiple repetitions after warm-up and report hardware, median, and dispersion.
- Replace “constant state” with the directly measured property: for example, one merged environment at statement boundaries while guarded alternatives and formulas may grow.

### Exit criterion

The evaluation shows where the representation helps, where symbolic values still grow, and how it compares to relevant prior analyzers.

## Phase 6: Redesign construct-support reporting

Do not report token/construct counts as semantic correctness percentages.

- Rename the census to **observed construct frequency and implemented handling**.
- Separate:
  - fully modeled and tested;
  - modeled with approximation;
  - ignored after verified irrelevance to object selection;
  - unsupported but potentially relevant;
  - unsupported and observed to affect results.
- Document how each construct is detected and counted.
- For every ignored rule, recipe, shell command, `eval`, or substitution reference, determine whether it can influence object selection in that context.
- Add mutation/differential tests against GNU Make for supported constructs:
  - generate or curate small Makefiles;
  - enumerate manageable concrete configurations;
  - compare kfold's predicted values with GNU Make output;
  - publish every fixture and mismatch.
- Report semantic agreement on the conformance suite separately from corpus frequency.
- Remove “99.9% effective coverage” unless there is a clear denominator and correctness oracle.

### Exit criterion

Readers can distinguish frequently encountered syntax from correctly reproduced semantics.

## Phase 7: Reduce and validate the applications

Seven applications make the paper look broad but unconvincing. Retain at most two or three well-validated applications in the main paper. Move secondary exploratory analyses to an appendix or artifact.

### Recommended primary applications

1. **Configuration generation for a target**, only if Kconfig integration and real-build validation succeed.
2. **Build-change analysis across releases**, with generated witnesses validated on both versions.
3. **Confirmed build-maintenance defects**, only when supported by a reproducer and preferably an upstream report/response.

### CI matrix

- Fix the algorithm. The current pseudocode selects an arbitrary uncovered target and obtains one satisfying model; it does not maximize marginal coverage and is not greedy set cover.
- Either implement a real optimization/greedy candidate-selection procedure or call it iterative witness generation.
- Never call the result minimal unless optimality is proven.
- Build every proposed configuration and report:
  - configuration validity;
  - build success;
  - predicted object coverage;
  - observed object coverage;
  - total build time/cost.
- Compare against meaningful baselines: defconfigs, randconfig samples, existing CI configurations, and a random or coverage-guided sampler under the same budget.
- Do not equate object inclusion with testing effectiveness.

### Minimal reproducing configurations

- Rename to **small enabling configurations** unless global minimality is established over the full constrained configuration space.
- Include Kconfig constraints and normalized configurations.
- Show that the generated configuration actually builds the target.
- Report the objective precisely: number of enabled Boolean/tristate options, weighted cost, or difference from a base configuration.

### Defect and orphan claims

- Reproduce every claimed defect with the actual build system.
- Check whether allegedly orphaned symbols are generated, command-line-defined, build-stage markers, architecture variables, or compatibility aliases.
- In particular, investigate `CONFIG_SPL_BUILD` and `CONFIG_TPL_BUILD` before labeling them U-Boot zombies.
- For the Barebox `.gen.o` case, show the original source lines verbatim, the expansion trace, build behavior, affected version range, and a minimal reproducer.
- Search upstream history for fixes or explanations.
- Submit an issue or patch when appropriate and report status neutrally: submitted, confirmed, fixed, rejected, or unanswered.
- Without confirmation, use “candidate anomaly,” not “real bug.”

### Differential evolution

- Align renamed/added/removed symbols and target paths across versions.
- Validate a sample of widened, restricted, and divergent conditions using both real versions.
- Report false-witness rates after each project's configuration normalization.

### Move out of the main paper unless strongly validated

- feature-interaction statistics;
- pairwise co-compilation clustering;
- Kconfig/Kbuild symbol-count linting by itself.

### Exit criterion

Each primary application contains a baseline, end-to-end validation, failure analysis, and concrete usefulness evidence.

## Phase 8: Repair all numbers, tables, and references

### Numerical consistency

Generate LaTeX table fragments and summary macros directly from canonical result files. Add a CI script that fails when manuscript numbers disagree with the data.

Resolve at least these current inconsistencies:

- 18,175 versus 18,130 total objects;
- 246 versus 222 coreboot objects;
- 12,882 versus 11,299 Linux objects;
- two BusyBox CI configurations versus five positive validation configurations;
- ambiguous counts and denominators in Table 7.

Every table caption must define:

- unit of observation;
- filters/exclusions;
- configuration count;
- whether objects are unique or repeated across configurations;
- whether values are static predictions or observed builds.

### Reference audit

For every bibliography entry:

- open the publisher or author page;
- verify title, authors, venue, year, pages, and DOI;
- verify that the cited source supports the surrounding sentence;
- remove decorative citations that do not support the claim.

Immediately fix:

- the 2020 Kbuild symbolic-execution citation;
- the Dynaplex citation, whose current title is unrelated to the actual paper;
- the characterization of Kmax's evaluation and semantics;
- references used to justify quantitative claims such as defconfig coverage.

### Exit criterion

An automated consistency check passes, and a human has verified every bibliography entry and citation context.

## Phase 9: Rewrite the paper in the correct order

Rewrite only after the evidence is stable.

### Suggested structure

1. Introduction
2. Background and motivating example
3. kfold design and implementation
4. Scope, assumptions, and supported constructs
5. Evaluation methodology
6. RQ1: semantic/concrete-build agreement
7. RQ2: scalability and comparison with prior approaches
8. RQ3: two or three validated applications
9. Discussion and limitations
10. Related work, including prior symbolic and static Kbuild analyses
11. Conclusion

### Contributions should be limited to approximately three

1. A practical guarded-value implementation for analyzing a specified Kbuild subset.
2. A reproducible empirical evaluation of its semantic agreement, concrete-build agreement, and scalability across named systems.
3. A small number of validated downstream uses.

Do not list corpus size, construct census, implementation language, formal semantics, and seven applications as separate contributions.

### Writing rules

- Replace adjectives with evidence.
- Remove phrases such as “landmark,” “dramatically expanded,” “massive coverage gains,” “fundamental open question,” “imperative,” and “powerful applications.”
- Use “we observed” rather than “we proved” for empirical findings.
- Use “supported subset” rather than “GNU Make semantics.”
- State negative results and boundaries where readers first need them.
- Avoid repeating the contribution list in every section.
- Keep the motivating scenarios short and do not claim industrial necessity without evidence.
- Ask a human author to review every paragraph for technical meaning; do not accept fluent text as evidence of correctness.

### Abstract template

Write the final abstract last, using this structure:

1. Problem and why existing concrete builds are insufficient.
2. What kfold implements, with a scoped description of the supported Kbuild subset.
3. Exact experimental subjects and comparison/validation protocol.
4. Full-range results, including limitations rather than only maxima.
5. One or two validated applications.

### Exit criterion

The abstract, contributions, results, limitations, and conclusion make mutually consistent claims.

## Phase 10: Build a credible artifact

The artifact should permit a reviewer to reproduce every primary table and inspect every mismatch.

Include:

- source code with license;
- exact dependency lock file/container;
- subject-fetch scripts pinned to commits;
- conformance fixtures;
- experiment scripts;
- raw analyzer output;
- generated configurations;
- configuration-normalization logs;
- complete build logs;
- per-object prediction/observation data;
- discrepancy classifications;
- scripts generating every table and figure;
- a quick smoke test and a full reproduction path;
- expected runtime and disk usage;
- documentation of unsupported constructs and known failures.

Run the artifact from a clean machine/container. A person who did not implement kfold should follow the instructions and record every ambiguity.

### Exit criterion

One command reproduces the small evaluation, and a documented sequence reproduces the full evaluation and manuscript tables from raw data.

## Phase 11: Final adversarial review

Before submission, perform three independent audits.

### Technical audit

- Check design description against code.
- Rerun semantic fixtures and build validation.
- Inspect high-impact mismatches manually.
- Ensure all generated configurations are valid under project tooling.

### Claim audit

Search the manuscript for:

- exact;
- sound;
- complete;
- prove/provably;
- guarantee;
- minimal;
- optimal;
- constant;
- eliminate;
- all/every/zero;
- up to.

For each occurrence, either attach evidence in the claim ledger or weaken/remove it.

### AI-sloppiness audit

- Verify every citation and proper name.
- Recalculate every percentage.
- Compare totals across the abstract, tables, and conclusion.
- Check that pseudocode matches the implementation.
- Remove generic promotional prose and repeated contribution summaries.
- Ensure every discrepancy category is discussed, especially the worst-performing system.
- Ask reviewers to flag passages that sound fluent but convey no testable technical content.

### Exit criterion

No unresolved high-severity item remains in the claim ledger, and two human readers can trace every headline claim to code, raw data, or a cited source.

## Prioritized execution order

Work in this order and do not begin prose polishing early:

1. Evidence ledger and experiment manifest.
2. Related-work positioning and baseline selection.
3. Semantic implementation audit and regression tests.
4. Kconfig strategy decision and implementation or scope reduction.
5. Ground-truth build-validation pipeline.
6. Relevant baselines and scalability experiments.
7. Application reduction and end-to-end validation.
8. Regenerate all data and tables.
9. Reference audit.
10. Rewrite design, evaluation, introduction, and related work.
11. Write conclusion and abstract last.
12. Package and independently reproduce the artifact.
13. Conduct the adversarial final review.

## Stop conditions

Stop and report to the authors instead of manufacturing a workaround when:

- raw data cannot reproduce a published table;
- repository versions or commands used for an experiment are unknown;
- the implementation behavior contradicts the manuscript;
- a claimed defect cannot be reproduced;
- an allegedly valid configuration is rewritten or rejected by Kconfig;
- Kmax or another prior approach cannot be compared fairly;
- a reference cannot be verified;
- the requested claim would require evidence that has not been collected.

## Minimum acceptable resubmission bar

The revised paper is ready for serious internal review only if all of the following hold:

- no formal-semantics contribution is claimed;
- the 2020 work is cited accurately and positioned neutrally without compromising anonymity;
- the tool's supported subset and approximations are clearly stated;
- actionable configurations incorporate Kconfig constraints or those applications are removed;
- Linux and the other main subjects have transparent concrete-build validation;
- poor results are either fixed or honestly presented as boundaries;
- the primary baselines include relevant prior tools, not only a naive path executor;
- retained applications are validated end to end;
- all defects are reproducible and carefully labeled;
- all tables come from archived raw data;
- all references are manually verified;
- the artifact can reproduce the main results from a clean environment.

The paper should become smaller in claims but much stronger in credibility. A focused paper with two validated applications and honest limitations is substantially more persuasive than a paper claiming exact semantics and seven applications without dependable evidence.
