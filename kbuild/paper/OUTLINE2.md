# Proposed kfold paper outline

**Working thesis:** kfold turns configuration-dependent Kbuild rules into object conditions that a developer can use to explain a missing build target and generate a configuration to compile-test changed code.
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
| Implementation | 1 |
| Evaluation | 6.5 |
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

- **Problem:** A `.config` and a build log show what one Linux build compiled, but they do not directly tell a developer how to compile an omitted file. 
TVN: should be more specific: it's about Kconfig,  what is it (subset of Make but specific for building and managing Linux kernel build. Motivation:  important because Linux has 13K something configs ...  increase flexibility etc)
- **Why it matters:** A patch can pass a compile test even when none of its changed code enters that build.
  A developer needs to know which build rule excluded the object and which valid configuration would include it.
TVN: would be good to have some real world incident or something with citations showing importance of configuration interactions. 

- **Running example:** Under the tested x86 defconfig, `fs/ext2/xattr.o` is absent because the relevant ext2 and xattr options are off.
  Enabling the object requires both Kbuild's selection condition and a Kconfig-valid assignment for `CONFIG_EXT2_FS` and `CONFIG_EXT2_FS_XATTR`.

- **Technical obstacle:** Kbuild can compute assignment destinations from option values, overwrite a list only under some conditions, defer expansions, and reach the same directory by more than one path.
  Reading nearby `CONFIG_` names or running Make once does not recover the condition for every object.
  
TVN: need to have a related and SOTA paragraph briefly describing work like KMax and bring up their limitations. Which kfold aim to address.

- **Idea:** kfold guards each word in a Make variable with the configurations that include it, merges both arms of a conditional into one state, and propagates guards through the directory graph.
  It then uses the resulting object conditions to explain a build verdict or solve for a configuration that selects changed files.
- **Evidence preview:** In the saved physical comparisons, kfold's predicted set equals the observed set for four Linux configurations with 489 to 25,949 objects.
  The project also records 28 checked `why` verdicts, 16 `config-for` file sets, three crafted patch inputs, and six successful object compilations.
- **Contributions:** Present the object-condition analysis, its use in explanation and configuration generation, and an evaluation that checks both the formulas and the resulting developer actions.

## 2. Overview: from an absent object to a checked configuration


**Input and output:** Given a source tree, project settings, and optionally a `.config` or patch, kfold computes an object-to-condition map and returns an explanation or a proposed configuration fragment.
TVN: I assume you will give some code snippet, e.g., that build fs/ext2/xattr.c or something. Basically a concrete motivating example showing Kbuild stuff and what kfold does to it. 

- **Concrete trace:** Follow `fs/ext2/xattr.c` to `fs/ext2/xattr.o`, show the Makefile and parent-directory guards that select it, and evaluate those guards under defconfig.
  The `why` command should identify the failing options rather than merely report that the object is absent.
- **Configuration step:** `config-for` combines the object's Kbuild condition with Kconfig constraints, then seeks a small change from a base configuration.
  The project check for `xattr.o` requires both `CONFIG_EXT2_FS` and `CONFIG_EXT2_FS_XATTR` in the emitted fragment.
- **Verification step:** Applying the fragment through `make olddefconfig` tests whether Kconfig preserves it, and compiling the object tests whether the proposed configuration reaches real build behavior.
  This separates a satisfying formula from a configuration known to compile.
- **Pipeline figure:** Show Makefile parsing, guarded execution, directory and object extraction, the cached condition map, Kconfig solving, and build verification as distinct stages.

## 3. Technique

TVN: there should be an overview algorithm and a paragraph saying something like Fig or Alg. describes the Kfold ... And then give a quick overview on what it does , e.g., the input is, output is,  in the beginnig kfold does x (line y),  next it does ...  . Basically a couple of apragraphs describing it.  

And then in the subsection talks about important components, and include algorithm there if needed. Also include small examples too.

- **Model and result:** Define an object's Kbuild condition as a formula over the option values under which the supported analysis selects its path.
  Keep Kconfig feasibility separate until the developer query combines the two.
- **Guarded variables:** A variable maps each word to a guard, so one state can retain words selected by different configurations.
  An append adds a guarded word, while a conditional overwrite removes an old word only where the overwrite applies.
- **Conditional execution:** kfold executes each branch on a copy and merges the changed variables back into one state.
  Reuse a small overwrite example to show the intermediate guards and why an untouched word keeps its previous guard.
- **Expansion and Make semantics:** Explain computed variable names, immediate versus deferred assignment, and word-list expansion only where they change an object condition.
  State the supported construct boundary beside the operation it affects.
- **Directory and object propagation:** The traversal processes only the part of an incoming directory guard that earlier routes have not covered.
  Object extraction then adds composite members, built-in routes, and rule prerequisites so the conditions describe physical objects as well as target-list entries.
- **Kconfig-aware query:** For `config-for`, map changed `.c` and `.S` files to objects, conjoin their Kbuild conditions with the Kconfig constraints in the relevant dependency cone, and minimize changes to a base `.config`.
  Report mutually incompatible objects instead of claiming that one configuration builds all of them.
- **Query and cache:** Persist object conditions and origins so later `why` and `config-for` commands need not analyze the tree again.
  Explain what changes invalidate the cache and what source changes its current file-based invalidation can miss.

## 4. Implementation

TVN: unless this part is very large, otherwise integrated it directly to Evaluation.

- **Engine:** Describe the Python implementation, `pymake3` parser, Z3 guards, project settings, and per-Makefile analysis cache.
- **Developer commands:** Explain `why` as a trace of directory and target guards with an evaluated `.config`, and `config-for` as a source-to-object mapper plus a Kconfig-aware solver and verifier.
- **Other uses:** `blindspots` groups objects missed by selected standard configurations under `MAINTAINERS` entries.
  Treat `lint` as an exploratory use until the corrected dead-object sweep and manual checks are complete.

## 5. Evaluation

TVN: In the beginning, it should be something about the RQs,  benchmark and experimental setups, and baseline comparison if applicable (here probably simple, just kmax). 

RQs: We evaluate kfold using 4 RQs: ... 

Benchmark: some table showing the benchmark and justify why they are used.  Experimental setups: what metrics, times, etc.  Also machine details.   


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
- **Comparison and ablation:** Use the saved Kmax run and ablations to test which gains come from guarded words, composite members, rule closure, and entry settings.
  State where the compared tools use different extracted target sets or where a recorded run lacks complete process metadata.

## 6. Discussion and limitations

- **What a condition supports:** A developer can use a condition to explain a current build or propose options for a changed file.
  Kconfig normalization and compilation remain necessary before treating a proposed fragment as a usable build configuration.
- **Where results may change:** Top-level entry settings are copied from build logic, some Make constructs and host-dependent shell calls remain outside the model, and the four Linux profiles cover only a small part of the configuration space.
- **Next evidence:** Expand verification to real historical patches and additional architectures, rerun the corrected lint analysis, and test cache invalidation when previously unseen Makefiles appear.

## 7. Related work

- **Kbuild analyses:** Compare kfold's guarded-word representation and object-level validation with prior static Kbuild analyses such as Kmax.
  Verify the prior tools' precise guarantees and supported input classes before writing the manuscript comparison.
- **Symbolic execution and variability:** Explain how branch merging differs from retaining a path state for every branch combination and where formula size can still grow.
- **Kconfig and testing tools:** Position Kconfig solvers and configuration sampling as complementary to Kbuild condition extraction.
  kfold's developer commands connect the build-side condition to configurator checks and compile tests.

## 8. Conclusion

- **Established result:** The project demonstrates that guarded object conditions can support both build prediction at the measured Linux scale and concrete developer queries about missing or changed code.
- **Boundary and implication:** The physical comparisons, Kconfig normalization checks, and object compilations support this workflow on the tested cases, while broader claims require more configurations, patches, and architectures.

TVN: also something in current/future work. Conclusion should be conclusion and not just summary of the work.

## Abstract and title

Write these after the paper's emphasis and result scope are settled.
The title above reflects both the condition analysis and the developer task, without making a universal exactness claim.

## Project evidence used

- Core analysis: `src/ds.py`, `src/symexe.py`, `src/alg.py`, `src/objects.py`.
- Developer commands and tests: `src/cli/commands/`, `tests/test_cli_*.py`, `DEVTOOL_PLAN.md`.
- Physical and semantic results: `results/physical_validation.json`, `results/linux_gnu_make_validation.json`, `results/bench_scaling.json`.
- Developer task records: `evidence/config_for_checkpoint_2b.json`, `evidence/blindspots_v6.6.json`, `evidence/lint_v6.6.json`.
