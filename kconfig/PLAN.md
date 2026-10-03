# Implementation Plan: Precise Tristate Kconfig Static Analysis Engine

**Project**: `kconfig` (under `kfold`)  
**Objective**: Build a high-performance, exact 3-valued static analysis engine for Linux Kconfig specifications that overcomes the blind spots and architectural defects of prior work (ESEC/FSE '21 `kclause`/`kismet`), rigorously validated against Linux 5.4.4 and Linux 7.2.8.

---

## Architecture Overview

```
                                  Kconfig Specifications
                                 (Linux 5.4.4 / 7.2.8)
                                           │
                                           ▼
                            ┌──────────────────────────────┐
                            │ Clean AST / Frontend Parser  │
                            │ (Typed AST, source locations)│
                            └──────────────┬───────────────┘
                                           │
                                           ▼
┌────────────────────────────────────────────────────────────────────────────────────────┐
│ Exact 3-Valued Tristate Logic Model                                                    │
│                                                                                        │
│ • State space: n = 0, m = 1, y = 2                                                     │
│ • Expression semantics:                                                                │
│     A && B = min(A, B)                                                                 │
│     A || B = max(A, B)                                                                 │
│     !A     = (if A == 1 then 1 else 2 - A)                                             │
│ • Value-sensitive select force:                                                        │
│     force(X, A, C) = min(value(X), value(C))                                           │
│ • Effective direct limit:                                                              │
│     direct_limit(A) = inherited_conditions && depends_on(A)                            │
│ • UDD Violation Predicate:                                                             │
│     UDD(X, A, C) <=> force(X, A, C) > direct_limit(A)                                  │
└──────────────────────────────────────────┬─────────────────────────────────────────────┘
                                           │
         ┌─────────────────────────────────┼─────────────────────────────────┐
         ▼                                 ▼                                 ▼
┌─────────────────┐               ┌─────────────────┐               ┌─────────────────┐
│ Backend 1:      │               │ Backend 2:      │               │ Backend 3:      │
│ Dual-Boolean    │               │ Bit-Vector      │               │ Integer / Diff  │
│ SAT (Exact)     │               │ QF_BV (Z3)      │               │ QF_IDL (Z3)     │
└────────┬────────┘               └────────┬────────┘               └────────┬────────┘
         └─────────────────────────────────┼─────────────────────────────────┘
                                           ▼
                     ┌───────────────────────────────────────────┐
                     │ 2-Tier Refutation Engine                  │
                     │ Tier 1: Local Refutation (X, A, C)        │
                     │ Tier 2: Global Reachability Model         │
                     └─────────────────────┬─────────────────────┘
                                           │
                                           ▼
                     ┌───────────────────────────────────────────┐
                     │ Witness & Differential Oracle             │
                     │ • Generate .config from SAT/SMT model     │
                     │ • Verify via scripts/kconfig/conf         │
                     │ • Cross-check with kfold Kbuild engine    │
                     └───────────────────────────────────────────┘
```

---

## Phase 0: Machine-Checked Formal Semantics in Lean 4

* [x] **Task 0.1: Formal Tristate Lattice Specification**
  * Formalize the 3-valued truth domain: $n < m < y$ with natural valuation $n=0, m=1, y=2$.
  * Define lattice operations in Lean 4: conjunction ($\min$), disjunction ($\max$), and negation ($!n = y, !m = m, !y = n$).
  * Artifact: [`lean/Kconfig.lean`](file:///home/tnguyen/git/projects/kfold/kconfig/lean/Kconfig.lean).
* [x] **Task 0.2: Machine-Checked Proof of Prior Incompleteness**
  * Formally define the Boolean abstraction mapping of prior work (Oh et al., ESEC/FSE '21) where $m, y \mapsto \mathtt{true}$.
  * Prove **Theorem 1 (`boolean_abstraction_misses_ym_udd`)**: There exists a valid Kconfig selection where an Unmet Direct Dependency exists in the real 3-valued semantics, but is completely missed by the Boolean abstraction ($y \to m$ defect).
* [x] **Task 0.3: Machine-Checked Proof of Sound Local Pruning**
  * Prove **Theorem 2 (`local_refutation_sound`)**: If local constraints prove selection force $\le$ direct limit, an Unmet Direct Dependency is impossible globally ($\text{force} \le \text{limit} \implies \neg \text{UDD}$).
* [x] **Task 0.4: Machine-Checked Proof of Dual-Boolean SAT Isomorphism**
  * Define `DualBool` with coordinates $(b_{\text{on}}, b_{\text{built\_in}})$ subject to invariant $b_{\text{built\_in}} \implies b_{\text{on}}$.
  * Prove **Theorem 3 (`dual_bool_isomorphism`)**: The Dual-Boolean representation is order-isomorphic to the 3-valued Tristate lattice via bijective roundtrip.
* [x] **Task 0.5: Automated Lean 4 Package & Build Configuration**
  * Configure `lakefile.lean` and Lean 4 toolchain (Lean v4.34.1).
  * Verify clean compilation with `lake build`.

---

## Phase 1: Test Harness & Groundtruth Baselines

* [ ] **Task 1.1: Multi-Architecture Corpus Setup**
  * Ensure clean Linux 5.4.4 and Linux 7.2.8 trees are registered as read-only test targets.
  * Target architectures: `x86_64`, `arm64`, `riscv`, `powerpc`.
* [ ] **Task 1.2: Baseline Test Suite**
  * Script automated execution of the legacy `kismet` pipeline using the safe `fork` start-method runner.
  * Collect all raw alarms, runtime metrics, and witness `.config` files on Linux 5.4.4 and 7.2.8 into `results/baselines/`.
* [ ] **Task 1.3: Known Case Regression Suite**
  * Establish test fixtures for:
    1. Known boolean UDD (`TOUCHSCREEN_ADC -> IIO_BUFFER_CB` on 5.4.4).
    2. Known patched safe case (`TOUCHSCREEN_ADC -> IIO_BUFFER_CB` on 7.2.8).
    3. Tristate $y \to m$ violation (selector is $y$, dependency is $m$).
    4. Tristate conditional select ($X=y, C=m \implies \text{force}=m$).
    5. Boolean target promotion ($m$ dependency/select promoted to $y$ for boolean symbols).
    6. `CONFIG_MODULES=n` configuration (disallowing $m$).

---

## Phase 2: Exact 3-Valued Logic Engine & Solver Backends

* [ ] **Task 2.1: Abstract Tristate Model Interface**
  * Implement `TristateIR` representing symbols, values ($n=0, m=1, y=2$), and operations ($\min, \max, \text{not}, \text{comparison}$).
* [ ] **Task 2.2: Backend A — Dual-Boolean SAT Encoding**
  * Encode each tristate variable as two booleans $(b_{\text{on}}, b_{\text{built\_in}})$:
    * Invariant: $b_{\text{built\_in}} \implies b_{\text{on}}$
    * $n = (0, 0)$, $m = (1, 0)$, $y = (1, 1)$
  * Implement componentwise operations:
    * $A \land B = (A_{\text{on}} \land B_{\text{on}}, \; A_{\text{built\_in}} \land B_{\text{built\_in}})$
    * $A \lor B = (A_{\text{on}} \lor B_{\text{on}}, \; A_{\text{built\_in}} \lor B_{\text{built\_in}})$
    * $\neg A = (\neg A_{\text{built\_in}}, \; \neg A_{\text{on}})$
* [ ] **Task 2.3: Backend B — Quantifier-Free Bit-Vectors (`QF_BV`)**
  * Encode options as `BitVec(2)` with unsigned domain constraint `sym <= 2`.
  * Implement unsigned lattice operations using `z3.If(z3.ULT(A, B), A, B)` and `z3.If(z3.UGT(A, B), A, B)`.
* [ ] **Task 2.4: Backend C — Difference Logic (`QF_IDL` / `QF_LIA`)**
  * Encode options as bounded integers $0 \le \text{sym} \le 2$.
  * Benchmark solver performance across all three backends on synthetic chains and real dependency subgraphs.

---

## Phase 3: Exact Value-Sensitive UDD Detection

* [ ] **Task 3.1: Value-Sensitive Select & Direct Limit Formulation**
  * Correctly implement:
    $$\text{force}(X, A, C) = \min(\text{value}(X), \text{value}(C))$$
  * Correctly compute $\text{direct\_limit}(A)$ taking into account inherited enclosing `if` and `menu` conditions.
* [ ] **Task 3.2: Local Refutation (Tier 1)**
  * Construct local bug query:
    $$\phi_{\text{local}} = \text{local\_constraints}(X, A, C) \land (\text{force}(X, A, C) > \text{direct\_limit}(A))$$
  * If $\phi_{\text{local}}$ is UNSAT, prove construct safe immediately.
* [ ] **Task 3.3: Global Model Without Invariant Poisoning (Tier 2)**
  * **Crucial Rule**: Do NOT assert $\text{value}(A) \le \text{direct\_limit}(A)$ globally!
  * Instead, model resulting values as computed by Kconfig:
    $$\text{value}(A) = \max(\text{user\_or\_default}(A), \; \text{total\_reverse\_force}(A))$$
  * Query whether a valid configuration can reach $\text{force}(X, A, C) > \text{direct\_limit}(A)$.

---

## Phase 4: Dynamic Witness Generation & Kernel Validation

* [ ] **Task 4.1: Witness `.config` Generator**
  * Project satisfying solver models into standard Linux `.config` files.
* [ ] **Task 4.2: Automated Kernel Oracle Verification**
  * Invoke `make KCONFIG_ALLCONFIG=witness.config olddefconfig` (or `scripts/kconfig/conf`).
  * Capture stderr and check for matching `WARNING: unmet direct dependencies detected`.
  * Classify alarms into verified true positives, suppressed warnings, or contradictory configs.

---

## Phase 5: Automated Fix Recommendation & Patch Synthesis

* [ ] **Task 5.1: Dependency Clause Repair Generator**
  * When a UDD on `CONFIG_A` triggered by `CONFIG_X select CONFIG_A` is verified:
    * Strategy A: Synthesize missing direct dependencies to `CONFIG_X`'s `select` condition (`select A if DEP_A`).
    * Strategy B: Propose upgrading `select A` to `imply A` if weak coupling is acceptable.
    * Strategy C: Identify missing cascading selects (e.g. adding `select IIO_BUFFER` when selecting `IIO_BUFFER_CB`).
* [ ] **Task 5.2: Kernel Patch Formatting and Verification**
  * Format generated repairs as unified git diff patches against the target Linux tree.
  * Re-run static analysis and `olddefconfig` to verify the patch eliminates the warning without introducing cycles or breaking other configurations.

---

## Phase 6: Cross-Layer Build Failure Verification (`kfold` Synergy)

* [ ] **Task 6.1: Kbuild Object Inclusion Check**
  * For each verified UDD on `CONFIG_A`:
    * Query the `kfold` Kbuild database to check if `obj-$(CONFIG_A) += ...` is reachable under the configuration.
* [ ] **Task 6.2: Preprocessor Reachability Check (`IS_REACHABLE`)**
  * Check source call sites for `IS_REACHABLE(CONFIG_A)` vs `IS_ENABLED(CONFIG_A)`.
  * Differentiate harmless UDDs (protected by stubs/`IS_REACHABLE`) from catastrophic linker errors (built-in callers calling uncompiled module functions).
* [ ] **Task 6.3: Consistency Linting (Orphans & Phantoms)**
  * Identify **Phantom Makefile Targets**: Makefile references `obj-$(CONFIG_XYZ) += ...` where `CONFIG_XYZ` is never defined in any Kconfig file.
  * Identify **Orphan Options**: Kconfig options that are defined and prompted but never referenced in any Makefile or C preprocessor guard.

---

## Phase 7: The Comprehensive Benchmark Suite (Beyond Prior Work)

This phase executes the 6 critical benchmark dimensions that the prior ESEC/FSE '21 paper omitted:

### Dimension 1: Cross-Project Ecosystem Benchmark
* [ ] **Task 7.1: Evaluate Across Diverse Kconfig Software**
  * Extend benchmark evaluation beyond Linux to the full embedded systems corpus already present in `kfold`:
    1. **BusyBox** (v1.38.0)
    2. **Barebox** (v2026.09.0)
    3. **U-Boot** (v2026.07)
    4. **Coreboot** (v26.06)
  * Verify whether Kconfig semantics and bug patterns generalize outside the Linux tree.

### Dimension 2: Tristate ($y \to m$) Linker-Failure Benchmark
* [ ] **Task 7.2: Mine and Validate $y \to m$ Conflicts**
  * Deploy exact 3-valued solvers to mine all instances where a built-in symbol ($y$) selects an option whose dependencies are restricted to modules ($m$).
  * For each alarm, synthesize witness `.config` and attempt full kernel build (`make vmlinux`) to detect unresolved external symbol linking errors.
  * Compare against baseline tools to quantify the exact false-negative rate caused by Boolean collapsing.

### Dimension 3: Longitudinal Evolution Benchmark
* [ ] **Task 7.3: Track Bugs Across Kernel Generations**
  * Benchmark across key kernel releases: Linux v4.19 (LTS), v5.4.4 (paper's baseline), and v7.2.8 (modern baseline).
  * Compute **Bug Lifespan Analysis**: measure how many kernel versions or years UDD bugs remain latent before being patched.
  * Track regressions and measure the impact of newer language constructs (such as `imply`).

### Dimension 4: Multi-Defect Bug Ontology Benchmark
* [ ] **Task 7.4: Broaden Bug Detection Beyond Reverse-Dependencies**
  * **Dead / Unreachable Options**: Query $\neg \text{SAT}(K_{\text{actual}} \land \text{val}(S) \ge m)$ to flag options that can never be enabled under any hardware configuration.
  * **Dead Choice Elements**: Flag mutually-exclusive choice elements whose enclosing menu conditions render them permanently unreachable.
  * **Circular / Recursive Dependencies**: Detect dependency cycles across `depends on`, `select`, and `imply` that abort Kconfig parser execution.

### Dimension 5: Cross-Layer Verification Benchmark (Kconfig $\times$ Kbuild)
* [ ] **Task 7.5: Connect Specification Validity to Build Execution**
  * Map every Kconfig alarm to its corresponding Makefile object compilation rules using `kfold`.
  * Quantify the proportion of Kconfig specification warnings that lead to:
    1. Fatal build/link breakage.
    2. Silent runtime misconfiguration (feature included but dependencies missing).
    3. Benign warnings (shielded by source-level defensive stubs).

### Dimension 6: Solver Backend Head-to-Head Benchmark
* [ ] **Task 7.6: Comparative Performance & Scalability Evaluation**
  * Compare solver backends across all benchmark subjects:
    * **Dual-Boolean SAT** with modern CDCL solvers (CaDiCaL, Kissat).
    * **Bit-Vector SMT (`QF_BV`)** with Z3 and Bitwuzla.
    * **Difference Logic (`QF_IDL`)** with graph cycle detection.
  * Report solve times, memory consumption, and SAT vs. SMT bit-blasting efficiency on 15,000+ variable industrial models.

