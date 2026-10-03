# Proposed kfold paper outline

**Working thesis:** kfold turns configuration-dependent Kbuild rules into build conditions that a developer can use to explain a missing build target and generate a configuration to compile-test changed code.
**Basis:** Project source, tests, experiment outputs, evidence files, and `DEVTOOL_PLAN.md`.
**Venue and page budget:** FSE, 20 pages for the main paper.
References and appendices do not count toward this budget.
**Working title:** *kfold: Explaining and Enabling Configuration-Dependent Linux Builds*.

| Part | Pages |
| --- | ---: |
| Title, abstract, and front matter | 0.5 |
| Introduction | 1.5 |
| Overview | 2.5 |
| Technique | 4.5 |
| Evaluation, including implementation and setup | 7.5 |
| Discussion and limitations | 1.5 |
| Related work | 1.5 |
| Conclusion | 0.5 |
| **Main paper total** | **20** |

## Central story

A developer who changes a Linux source file may run a successful build that never compiles that file.
Determining why requires following Kbuild assignments and directory selection, then checking whether Kconfig permits the needed options.
kfold computes a build condition for each object by executing Makefiles over guarded words and merging conditional effects.
The same conditions support explanations, configuration generation, and coverage queries, with Kconfig and real builds used to check the proposed configurations.

## 1. Introduction

- **Context:** Linux uses [Kconfig](https://docs.kernel.org/kbuild/kconfig-language.html) to define configuration options and their dependencies, while [Kbuild Makefiles](https://docs.kernel.org/kbuild/makefiles.html) use the chosen values to select directories and objects.
  Kconfig is a separate configuration language, and Kbuild uses Make to assemble the build.
  The project's [Linux v6.6 validation data](../results/linux_gnu_make_validation.json) records 13,891 configuration symbols, illustrating the flexibility and scale of the selection problem.
- **Problem:** A `.config` and a build log show what one assignment compiled, but they do not directly tell a developer why another source file was omitted or how to compile it.
- **Why it matters:** A patch can pass a compile test even when none of its changed code enters that build.
  A developer needs to know which build condition excluded the object and which Kconfig-valid setting would include it.
- **Published motivation:** A [study of Linux 4.4.1](https://arxiv.org/pdf/2110.05828#page=5) documents an `ATH5K_PCI` setting that users could change only when its parent `ATH5K` driver was disabled, leaving that setting unable to affect the compiled driver.
  Use this as a historical example of configuration interaction, not as a finding by kfold.

- **Running example:** In the illustrative adaptation of Linux 6.6 [`fs/ext4/Makefile`](../results/workspaces/linux/fs/ext4/Makefile), `ext4.o` enters `obj-y` when `CONFIG_EXT4_FS=y` but disappears when a constructed later `CONFIG_EXT4_KUNIT_TESTS=y` assignment overwrites that list.
  Its local selection requires `CONFIG_EXT4_FS=y` and `CONFIG_EXT4_KUNIT_TESTS` unset, which a scan of nearby option names would miss.

- **Technical obstacle:** Kbuild can compute assignment destinations from option values, overwrite a list only under some conditions, defer expansions, and reach the same directory by more than one path.
  Reading nearby `CONFIG_` names or running Make once does not recover the condition for every object.
- **Closest prior work and gap:** [Kmax](https://www.paulgazzillo.com/papers/esecfse17.pdf) already infers Kbuild configurations, including computed variable names, by tagging complete string definitions with conditions.
  Its append operation combines alternative definitions by a cross product, so this paper tests whether guarding independent words separately reduces that cost and supports physical-object explanations and developer queries.

- **Idea:** kfold guards each word in a Make variable with the configurations that include it, merges both arms of a conditional into one state, and propagates guards through the directory graph.
  It then uses the resulting build conditions to explain a build verdict or solve for a configuration that selects changed files.
- **Evidence preview:** In the saved physical comparisons, kfold's predicted set equals the observed set for four Linux configurations with 489 to 25,949 objects.
  The project also records 28 checked `why` verdicts, 16 `config-for` file sets, three crafted patch inputs, and six successful object compilations.
- **Contributions:** Present the analysis of build conditions, its use in explanation and configuration generation, and an evaluation that checks both the formulas and the resulting developer actions.

## 2. Overview: from Kbuild assignments to build conditions

A **build condition** is the formula under which kfold's Kbuild analysis selects an object path.

- **Input and output:** Given a source tree, project settings, and optionally a `.config` or patch, kfold computes a map from objects to build conditions and returns an explanation or a proposed configuration fragment.
- **Pipeline figure:** Begin Section 2 with a compact left-to-right flow from Kbuild inputs through guarded execution to build conditions and the `why` and `config-for` queries.
- **Motivating code figure:** Given a source tree containing the adapted Makefile in Figure 2, kfold computes the built-in and module conditions in Table 1 for targets and members selected from its directory.
  Typeset the Linux 6.6 [`fs/ext4/Makefile`](../results/workspaces/linux/fs/ext4/Makefile) adaptation with syntax highlighting, and identify the constructed overwrite and branch in the caption.

  ```make
  # Adapted from Linux 6.6 fs/ext4/Makefile
  obj-$(CONFIG_EXT4_FS) += ext4.o
  obj-$(CONFIG_EXT4_KUNIT_TESTS) := ext4-inode-test.o
  ifeq ($(CONFIG_FS_VERITY),y)
    EXTRA := verity
  else
    EXTRA := crypto
  endif
  obj-y += $(EXTRA).o
  ext4-inode-test-y += inode-test.o
  ```

  `CONFIG_EXT4_FS` and `CONFIG_EXT4_KUNIT_TESTS` are tristate (`y`, `m`, or disabled `n`), while `CONFIG_FS_VERITY` is Boolean (`y` or `n`).
  In generated Makefiles, disabled `n` expands to an empty value, and Kconfig also has string, integer, and hexadecimal symbols outside this example.
- **Concrete trace:** kfold adds `ext4.o` to `obj-y` under `E_y` and to `obj-m` under `E_m`.
  The later assignment replaces `obj-y` under `T_y` and `obj-m` under `T_m`, giving `ext4.o` local conditions `E_y ∧ ¬T_y` for built-in selection and `E_m ∧ ¬T_m` for module selection.
  kfold then merges the branch values, gives `verity.o` and `crypto.o` complementary built-in guards under `V = CONFIG_FS_VERITY=y`, and propagates the parent selection to `inode-test.o`.
  For a nested Makefile, conjoin built-in conditions with its built-in reachability guard `B` and module conditions with its directory reachability guard `D`.
  Then show the overall build condition for `ext4.o`: `(B ∧ E_y ∧ ¬T_y) ∨ (D ∧ E_m ∧ ¬T_m)`.
  The disjunction means either built-in or module selection suffices, and kfold also disjoins separate assignments or directory paths that select the same object.
- **Configuration step:** After the extraction trace, explain how kfold’s `why` command evaluates a build condition against a `.config` and how its `config-for` command combines that condition with Kconfig constraints to propose a small configuration change.
  Use the project's checked Linux tasks for this step, since the adapted Makefile is not a verbatim Linux build rule.
- **Verification step:** Applying the fragment through `make olddefconfig` tests whether Kconfig preserves it, and compiling the object tests whether the proposed configuration reaches real build behavior.
  This separates a satisfying formula from a configuration known to compile.

## 3. Technique

- **Algorithm 1, guarded Kbuild analysis:** Given a source tree and project settings, return a map from physical object paths to build conditions and Makefile origins.

  ```text
  1  work ← entry Makefiles with their directory guards
  2  reached ← empty map
  3  while work is nonempty:
  4      take (makefile, guard) from work
  5      delta ← guard ∧ ¬reached[makefile]
  6      if delta is satisfiable:
  7          state ← execute parsed makefile over guarded words under delta
  8          reached[makefile] ← reached[makefile] ∨ delta
  9          add selected child Makefiles and their guards to work
  10 objects ← extract targets, composite members, and rule prerequisites
  11 return build conditions and origins
  ```

  Algorithm 1 takes configured entry Makefiles and returns conditions for the physical objects that kfold finds.
  Lines 1–2 initialize the worklist and covered guards, while lines 3–9 symbolically execute each newly reachable part of a Makefile and propagate guarded directory selections.
  Lines 10–11 combine selected targets with composite members and rule prerequisites, then return each object's build condition and origin.
  The following subsections explain guarded assignments, branch merging, expansion, and object extraction with small intermediate examples.
- **Model and result:** Define the build condition for an object as a formula over the option values under which the supported analysis selects its path.
  Keep Kconfig feasibility separate until the developer query combines the two.
- **Guarded variables:** A variable maps each word to a guard, so one state can retain words selected by different configurations.
  An append adds a guarded word, while a conditional overwrite removes an old word only where the overwrite applies.
  In the motivating Makefile, the guard on `ext4.o` starts with `CONFIG_EXT4_FS=y` and is narrowed by the constructed conditional overwrite.
- **Conditional execution:** kfold executes each branch on a copy and merges the changed variables back into one state.
  Reuse a small overwrite example to show the intermediate guards and why an untouched word keeps its previous guard.
- **Expansion and Make semantics:** Explain computed variable names, immediate versus deferred assignment, and word-list expansion only where they change a build condition.
  State the supported construct boundary beside the operation it affects.
- **Directory and object propagation:** The traversal processes only the part of an incoming directory guard that earlier routes have not covered.
  Object extraction then adds composite members, built-in routes, and rule prerequisites so the conditions describe physical objects as well as target-list entries.
- **Kconfig-aware query:** For `config-for`, map changed `.c` and `.S` files to objects, conjoin their build conditions with the Kconfig constraints in the relevant dependency cone, and minimize changes to a base `.config`.
  Report mutually incompatible objects instead of claiming that one configuration builds all of them.
- **Query and cache:** Persist build conditions and origins so later `why` and `config-for` commands need not analyze the tree again.
  Explain what changes invalidate the cache and what source changes its current file-based invalidation can miss.

## 4. Evaluation

- **Opening and research questions:** State the four questions before presenting any results.
  RQ1 asks how well build conditions predict physical builds across configurations and projects.
  RQ2 asks whether guarded execution matches GNU Make semantics and scales better than path forking.
  RQ3 asks whether `why` and `config-for` produce useful explanations and configurations that survive Kconfig and compile requested objects.
  RQ4 asks how kfold compares with Kmax on shared inputs and which analysis features account for the difference.
- **Subjects and rationale:** Start with a compact table listing Linux v6.6, BusyBox, Barebox, U-Boot, and coreboot, their known revisions and tested configurations, and which RQs use each subject.
  Linux is the main developer-task case, while the other Make-based configurable projects test whether the analysis extends beyond it and where it fails.
- **Implementation and experimental setup:** Describe the Python engine, `pymake3` parser, Z3 guards, project settings, per-Makefile cache, `why`, and `config-for` only insofar as they affect reproduction or interpretation.
  Report the actual CPU, memory, OS, tool versions, commands, time and memory measurement methods, and run counts beside the experiments that use them.
  The saved [scaling results](../results/bench_scaling.json) do not establish a CPU model or RAM for every run, so recover those details from run records or mark them missing.
  Use GNU Make output and physical builds as reference behavior, a path-forking executor for the scaling stress test, and the saved Kmax run as a baseline only where input and target scope are comparable.
- **RQ1, condition agreement:** Evaluate each extracted formula under concrete configurations and compare predicted object paths with physical build inventories.
  Report precision and the fraction of all compiled paths covered, so objects outside the extracted set remain visible.
- **RQ1, main result and scope:** The saved results show zero false positives and no missing physical paths on four evaluated Linux profiles.
  Two Linux inventories were reproduced by fresh builds, while the other two remain archived, and this agreement is not a proof for unseen configurations.
  BusyBox, Barebox, U-Boot, and coreboot should appear as separate cases with their mismatches and incomplete builds rather than be folded into the Linux result.
- **RQ2, semantic and scaling checks:** Compare per-file target lists with GNU Make and test generated Makefiles where independent conditionals stress path forking.
  At sixteen indirect appends, the saved run records 524,289 states and 185 seconds for the forking version versus 0.62 seconds for kfold.
  Report the whole-tree Linux run of 2,022 Makefile instances in 34 seconds and 162 MB, while keeping single-run timings descriptive.
- **RQ3, developer task outcomes:** Test whether `why` gives the correct built verdict and useful failing guards, then whether `config-for` fragments survive `olddefconfig` and compile their requested objects.
  The project status log reports 28 of 28 checked `why` verdicts, and the `config-for` checkpoint records 16 file sets, three crafted patch files, and six of six successful object compilations.
  Explain that the patch files are crafted because the checked-out Linux workspace lacks a usable multi-commit history.
- **Secondary use and limitations:** The `blindspots` artifact reports 3,242 of 29,245 analyzed objects absent from three selected x86 configurations, grouped across 493 `MAINTAINERS` entries.
  Present this as a coverage query, not a claim that those objects are dead or unbuildable.
  The corrected whole-tree `lint` dead-object result is still pending, so it should not support a paper result yet.
- **RQ4, comparison and ablation:** Compare kfold with the saved Kmax run on common Makefiles and target scope where possible, then use the saved ablations to test how composite members, rule closure, and entry settings affect object coverage.
  State where the tools extract different target sets or where a recorded run lacks complete process metadata.

## 5. Discussion and limitations

- **What a condition supports:** A developer can use a condition to explain a current build or propose options for a changed file.
  Kconfig normalization and compilation remain necessary before treating a proposed fragment as a usable build configuration.
- **Where results may change:** Top-level entry settings are copied from build logic, some Make constructs and host-dependent shell calls remain outside the model, and the four Linux profiles cover only a small part of the configuration space.
- **Next evidence:** Expand verification to real historical patches and additional architectures, rerun the corrected lint analysis, and test cache invalidation when previously unseen Makefiles appear.

## 6. Related work

- **Kbuild analyses:** Compare kfold's guarded-word representation and object-level validation with prior static Kbuild analyses such as Kmax.
  Verify the prior tools' precise guarantees and supported input classes before writing the manuscript comparison.
- **Symbolic execution and variability:** Explain how branch merging differs from retaining a path state for every branch combination and where formula size can still grow.
- **Kconfig and testing tools:** Position Kconfig solvers and configuration sampling as complementary to build condition extraction.
  kfold's developer commands connect the build-side condition to configurator checks and compile tests.

## 7. Conclusion

- **Takeaway:** On the tested cases, reusable build conditions turn a missing-file verdict into an actionable query about why the file was omitted and how to compile it.
- **Current work:** Complete the corrected whole-tree `lint` sweep and test whether cache invalidation catches newly reachable Makefiles.
- **Future direction:** Evaluate real historical patches and more architectures to learn when proposed fragments survive Kconfig normalization and compile the changed files.

## Abstract and title

Write these after the paper's emphasis and result scope are settled.
The title above reflects both the condition analysis and the developer task, without making a universal exactness claim.

## Project evidence used

- Core analysis: `src/ds.py`, `src/symexe.py`, `src/alg.py`, `src/objects.py`.
- Developer commands and tests: `src/cli/commands/`, `tests/test_cli_*.py`, `DEVTOOL_PLAN.md`.
- Physical and semantic results: `results/physical_validation.json`, `results/linux_gnu_make_validation.json`, `results/bench_scaling.json`.
- Developer task records: `evidence/config_for_checkpoint_2b.json`, `evidence/blindspots_v6.6.json`, `evidence/lint_v6.6.json`.
