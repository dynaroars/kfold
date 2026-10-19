# Summary of the Linux Developer Needs Survey

This summarizes `linux-developer-needs.md` and `problem_dossiers.json` in plain English: what kernel developers and downstream users actually struggle with around Kbuild/Kconfig, what tools already exist, and where `kfold` fits.

---

## 1. What Developers Need (Top 6 Problems)

### 1. Knowing if a patch is actually compiled during testing (`D1`)
* **The problem:** Kernel policy (`submit-checklist.rst`) requires patch authors to compile-test every changed file with its `CONFIG_*` options set to `=y`, `=m`, and `=n`. In practice, developers and maintainers (including Torvalds and subsystem CIs like netdev) rely on standard builds like `defconfig`, `allmodconfig`, or `allyesconfig`. Because of complex dependencies, `choice` blocks, and architecture guards, those standard configs silently skip many files. In our dataset, **289 of 402 stable commits** touch at least one `.o` file that `x86_64 defconfig` does not build.
* **What developers need:** A fast check showing whether their `.config` (or standard CI configs) actually compiles the `.o` files touched by a patch.

### 2. Checking if a CVE applies to a specific `.config` (`D9`)
* **The problem:** The Linux kernel CVE team assigns CVEs to almost every bug fix and leaves it to downstream users to figure out which CVEs affect their build. With the EU Cyber Resilience Act taking effect (Sept 2026 / Dec 2027), embedded vendors and distros (Siemens/CIP, Yocto, Debian, Chainguard) must triage thousands of kernel CVEs against their custom `.config` files.
* **What developers need:** If none of the source files modified by a CVE fix are compiled under a product's `.config`, the vendor can immediately mark the CVE as `vulnerable_code_not_present` (OpenVEX). Because a wrong "not built" answer hides a real vulnerability, **accuracy (zero false negatives)** is critical.

### 3. Generating a `.config` that compiles a specific file or patch (`D2`)
* **The problem:** When a developer modifies a driver or makes a tree-wide refactoring, enabling the right `CONFIG_*` options to compile the touched files is tedious. Manually editing `.config` often fails because `make olddefconfig` silently resets options whose parent dependencies are unmet, while building `allyesconfig` takes hours.
* **What developers need:** A tool (`kfold config-for`) that takes a file or patch and a baseline `.config`, changes as few options as possible, and produces a valid `.config` (surviving `make olddefconfig`) that compiles the target `.o` files.

### 4. Finding "blind spots"—files that standard configs never build (`D4`)
* **The problem:** Maintainers in Linux, U-Boot, and Barebox regularly discover drivers that no standard board config or `allmodconfig` ever compiles (for example, drivers missing `COMPILE_TEST`, locked behind mutually exclusive choices, or left out of Makefiles).
* **What developers need:** A whole-tree report (`kfold blindspots`) listing `.o` files that remain unbuilt across a set of standard configs, grouped by `MAINTAINERS` subsystem, along with the option blocking each file.

### 5. Explaining *why* an object file was not built (`D10`)
* **The problem:** When an expected `.o` or `.ko` file is missing from a build, grepping the local `Makefile` is often misleading. In our evaluation, 36%–78% of unbuilt objects are blocked not by their own `Makefile` line, but by a parent directory guard (`obj-$(CONFIG_FOO) += subdir/`) or composite-object rule higher up the tree.
* **What developers need:** A single command (`kfold why`) that evaluates the full chain of directory and Makefile conditions against their `.config` and pinpoints the exact `CONFIG_*` clauses that turned the file off.

### 6. Making sure fuzzers and tests actually compile the target code (`D11`)
* **The problem:** Dynamic tools like `syzbot` and KUnit only test code that gets compiled into the kernel. Today, `syzbot`'s patch-testing workflow uses a single base config and asks an LLM to guess which `CONFIG_*` options to enable for a patch—without verifying that the patched `.o` files get built. Similarly, KUnit's `all_tests.config` is maintained by hand and silently stops building tests when Kconfig dependencies change.
* **What developers need:** An automated check and minimal config repair on top of fuzzer/test base configs so patched or tested objects are guaranteed to be compiled.

---

## 2. Problems Where Kbuild Analysis Helps Little (Low Fit)

* **Dead Makefile guards (`D5`):** Typos in `obj-$(CONFIG_...)` or unsatisfiable Makefile conditions happen, but they are rare (~6 real cases found across 19 years of commits) and existing scripts (`checkkconfigsymbols`) already catch undefined symbols.
* **Distro config maintenance (`D8`) & Config diffs across releases (`D7`):** Most distro maintenance pain comes from Kconfig symbol changes and ABI stability, not Makefile logic.
* **Skipping CI builds (`D6`):** A CI system can skip building a `.config` when a patch touches zero compiled objects, but only if the patch touches no headers, Kconfig files, or Makefiles.
* **Stable/backport build failures (`D3`):** Stable `-rc` build breakages are almost always caused by missing prerequisite commits, header mismatches, or compiler differences—not Makefile object selection.

---

## 3. Existing Tools vs. `kfold`

Several tools already work in this space. **Do not claim `kfold` is the first tool to analyze Kbuild or repair configs.**

| Tool | What it does | Limitations where `kfold` improves |
| :--- | :--- | :--- |
| **Kmax / `klocalizer` / `krepair` / `koverage`** | Extracts Kbuild conditions, repairs `.config` for patches at the C line level (including `#ifdef`s), prints static Kbuild conditions (`--view-kbuild`) and unsat cores. | • Lower object-level accuracy on complex Makefiles (scores 88.6% precision / 61.2% recall on Debian in our run vs. `kfold`'s 100% in-universe agreement).<br>• Does not evaluate a condition against a given `.config` to report the specific failing clause.<br>• `krepair` changes many options (median 76 options in the ICSE'25 syzbot study vs. median 2 for `kfold config-for` on `defconfig`). |
| **`kernel-cve-triage` (Siemens/CIP)** | Uses Kmax formulas to check if files touched by a CVE are built in a `.config` and emits OpenVEX. | • Accuracy against real builds has not been systematically benchmarked.<br>• Returns a flat formula rather than pinpointing which option failed in the `.config`. |
| **`cvehound` / `PatchLens`** | Line/regex Kbuild parsers for CVE impact analysis. | • Misses directory-route guards, composite objects, and Makefile control flow. |
| **`sbom-cve-check` (Bootlin)** | Exact CVE file triage using DWARF debug info. | • Requires running a full debug-info kernel build first; cannot query unbuilt `.config` files statically. |

### Where `kfold` Does *Not* Compete
* **`#ifdef` blocks and header-only patches:** `kfold` operates at `.o` object granularity (about 2%–9% of kernel patches touch only headers, and ~11% target non-x86 architectures).
* **Pure Kconfig bugs:** Unmet `select`/`depends on` bugs in Kconfig files are already handled by `kismet` and `Kconfirm`.

---

## 4. Concrete Takeaways for the Paper

1. **How to position `kfold`:** Pitch `kfold` as a **fast, whole-tree, object-level build-condition analyzer whose accuracy is validated against real builds** across 5 Kbuild systems (Linux, BusyBox, Barebox, U-Boot, coreboot), outperforming Kmax on object-level precision and recall.
2. **What to include in RQ3 (Developer Tasks):**
   * **Task 1 — Fix/CVE Triage (`D9`, recommended addition):** Use `kfold` to check which of the 402 stable fix commits touch objects compiled under our 4 Linux `.config`s. Measure false "not-built" rate (target: 0%) and compare head-to-head with Kmax/`kernel-cve-triage` formulas against ground-truth build inventories.
   * **Task 2 — Config Synthesis (`config-for`, `D2` & `D11`):** Evaluate `kfold config-for` on the 402 commits using three baseline configs (`defconfig`, Debian, and `syzbot`'s base config). Report solve rate (384/402), number of options changed (median 2), and `olddefconfig` verification.
   * **Task 3 — Build Blind Spots (`blindspots`, `D4`):** Report unbuilt objects across standard x86 configs, separating arch-locked objects from drivers that are genuinely buildable on x86 but missed by standard configs.
   * **Task 4 — Build Explanations (`why`, `D10`):** Show that `kfold why` accurately identifies blocking options (including parent-directory guards) and that flipping those options causes the object to build.

---

## Files in this Directory

* [`linux-developer-needs.md`](linux-developer-needs.md) — Full detailed synthesis report with all citations, LKML links, and experiment designs.
* [`survey_summary.json`](survey_summary.json) — Structured JSON summary of rankings, RQ3 recommendations, and bibliography.
* [`problem_dossiers.json`](problem_dossiers.json) — Full per-problem dossier data (`D1`–`D11`).
* [`raw/`](raw/) — Raw scout and verification logs for each dossier.
