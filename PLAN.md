# skbuild completion plan (Python + Z3, BusyBox / coreboot / Linux) and FSE paper

This is the working checklist from here to (a) a Python-only skbuild that can
analyze real BusyBox, coreboot, and Linux kernel trees end to end, and (b) a
submittable FSE paper. This is the single source of truth for outstanding
work — it replaces (and absorbs the still-relevant content of) the retired
`LINUX_ANALYSIS_TODO.md`, `MIGRATION.md`, and `SUPPORTED.md`, which described
a Lean-era plan and construct-support matrix that no longer apply after the
Python+Z3 pivot. `README.md` (usage) and `paper/NOTES.md` (paper content
notes) are the only other living docs; don't recreate a fourth planning
document — extend this one.

Status convention: `[x]` = true in the working tree today, verified by a run
or test. `[ ]` = not yet true. Do not check an item off because output grew
or a warning disappeared — only because there's a passing test or a
reproduced run backing it.

## M0 — Engineering hygiene (do first, small)

- [x] Delete the Lean 4 tree; consolidate `src/`+`run/` into one canonical
  `src/` Python tree.
- [x] Fix `ZSolver` re-declaring a z3 `EnumSort` per Kbuild file (crashed on
  any tree with >1 directory) — now a singleton per `Settings` object.
- [x] Fix `--nomp` being a no-op (`settings.doMP` vs. actual `settings.do_mp`).
- [x] Fix `kbuild.py` crashing when `myreduce()` prunes a whole file to
  nothing.
- [x] Replace the exponential `Paths`/`SPath`/`DPath` fork-per-branch engine
  in `ds.py`/`symexe.py` with a single guarded-value `State`
  (`ds.VarG`/`ds.BaseState`), branch-and-merge in
  `symexe.ConditionBlock.sexe` (cybolic-style), with per-name `touched`
  tracking so untouched variables don't grow formulas at every conditional.
- [ ] Delete the now-fully-dead exploratory files that still import the
  retired `Paths`/`SPath`/`Var` API and are not imported by
  `skbuild.py`→`alg.py`→`kbuild.py`→`symexe.py`: `src/symexe1.py`,
  `src/symexe2.py`, `src/symexe3.py`, `src/spy.py`, `src/analysis1.py`,
  `src/unused.py`, `src/bexe.py`, `src/casestudy.py`, `src/casestudy1.py`,
  `src/dexe.py`. Confirm with `grep -rl` that nothing imports them first.
- [ ] Delete `src/helpers/miscs.py`'s `Miscs.run_mp` (dead now that there's
  no `Paths` list to parallelize merges over) and the `--nomp`/`do_mp`
  plumbing that exists only to route around it, once nothing else calls it.
- [ ] Re-add real parallelism only if profiling on a full Linux run
  (M2) shows it's needed, and only over an actual embarrassingly-parallel
  unit (e.g. one process per top-level Kbuild subtree), not a resurrected
  path-merge step.
- [ ] `tools/record_baseline.py`: verify the `--analyzer=src/skbuild.py`
  default (patched this session) still produces a useful manifest; the
  Python CLI doesn't emit JSON today (see M6), so `manifest.json`'s
  `result` block will stay empty until M6 lands. Note that explicitly here
  rather than silently shipping an empty field.
- [ ] Re-run `make test` and `make busybox-check` after every change in this
  section; both must stay green.

## M1 — BusyBox: fixture → real, validated by actually building it

The checked-in `tests/busybox/Makfiles_only/busybox_orig` snapshot now
analyzes fully (37 Kbuild files, ~0.6s, M0). That's a fixture, not a claim
about a real release, and a single hand-picked `.config` comparison (the
original plan here) is a weak experiment: it only tells you about one
point in a huge configuration space. The actual experiment — this is the
paper's headline result, so it's worth building as real infrastructure, not
a one-off script — is: **use Z3 to pick concrete witness configurations
from skbuild's own extracted conditions, run the real build under each
witness, and check whether the files skbuild predicted are exactly the
files that got built.** This is "compile the theorem prover's output and
see if it's still true" — the strongest validation available short of a
mechanized soundness proof, and it is the thing that would actually catch
a wrong condition, not just a crash.

### M1.0 — Shared witness-generation and build-validation tool

Build this once, generically, so M2 (Linux) and M3 (coreboot) reuse it
rather than each writing their own comparison script.

- [ ] `tools/validate_predictions.py` (or similar): given a run's analysis
  result (object path → Z3 condition) and a `Settings`/solver context:
  - [ ] For each distinct condition, ask Z3 for a satisfying model
    (`z3.Solver.model()` after `check()`) to get one concrete witness
    configuration that should select that file.
  - [ ] Don't stop at one witness per file: use a small greedy set-cover
    over conditions (the same technique Cybolic uses for its "sufficient
    CI matrix" result~— see `../cybolic/paper/cybolic.tex`'s RQ4) to find
    a *small* set of witness configurations that between them are
    predicted to cover every extracted object, so the real-build step
    below runs a handful of builds, not thousands.
  - [ ] Also generate at least one *negative* witness per file where
    feasible (a config under which the file's condition is false) so the
    experiment checks both directions: predicted-present files are
    actually present, and predicted-absent files are actually absent —
    not just the easier one-directional check.
  - [ ] For each witness: materialize a real `.config` (map the Z3 model's
    Boolean/tristate assignments to Kconfig's `CONFIG_X=y`/`=m`/unset
    lines; unassigned symbols need a documented default policy — probably
    "unset" — since Z3 will leave symbols the condition never mentions
    free).
  - [ ] Run the real build (`make` in a clean checkout of the pinned
    release, oldconfig/olddefconfig from the materialized `.config`, then
    a real build) and collect the actual object/module list, the same way
    M1's original `find -name '*.o'`/build-log approach did.
  - [ ] Compare predicted vs. actual per witness; do not silently ignore
    build failures — a witness whose real build fails to even complete is
    itself a data point (a Kconfig-invalid witness, or a real build-system
    bug) and should be reported, not dropped.
  - [ ] Output: one table per project, rows = witnesses, columns =
    true-positive / false-positive / false-negative object counts, plus a
    causal category for every non-true-positive (generated file skbuild
    doesn't model; unsupported construct; genuine skbuild bug; real
    Kconfig-invalid witness). This table *is* the paper's RQ4.

### M1.1 — Run it on BusyBox

- [ ] Pick a pinned BusyBox release tag; acquire it with
  `tools/acquire_source.py` into `results/workspaces/busybox` (reuse as-is;
  it's generic and was already Python-only).
- [ ] Fix `tests/busybox_skbuild.ini` / write a fresh `skbuild.ini` for the
  real release layout (the checked-in ini's `top_dirs` list was hand-curated
  for the old snapshot; verify it still matches, or regenerate from the real
  top-level `Makefile`'s `libs-y`/`core-y`).
- [ ] BusyBox's root `Makefile` uses `$(shell ...)`/`$(error ...)` — these
  are exactly the constructs flagged in the "support real constructs"
  discussion below, and skbuild not modeling them will directly show up as
  false negatives/positives in M1.0's table on BusyBox specifically, not
  just as an abstract limitation. Prioritize whichever of M2's "effects"
  work (shell execution, guarded error) BusyBox's own root Makefile
  actually needs before running the full validation loop, rather than
  doing that work generically for Linux first.
- [ ] Run M1.0's tool against a pinned BusyBox release; get the witness
  table above.
- [ ] Record a `tools/record_baseline.py` run against the real release and
  commit the manifest (not the full source) under `results/baselines/`.
- [ ] Acceptance: one pinned BusyBox release, a Z3-derived witness set with
  set-cover coverage of the extracted conditions, real builds run for each
  witness, and a predicted-vs-actual table with every non-match causally
  explained (not just counted).

## M2 — Linux kernel

This is the biggest lift; break it down as effects → root invocation →
Kconfig validity, since each depends on the previous one's state shape.

- [ ] Fix the immediate blocker found this session: `tests/linux_skbuild.ini`
  has `[DEFAULT]` but no `[COMMON]` section, while `settings.py` reads
  `config['COMMON']` unconditionally — decide whether to fix the ini or make
  `Settings` fall back to `DEFAULT`, and document why.
- [ ] Fix the `pymake3` parser crash found this session
  (`TypeError: '>=' not supported between NoneType and int` in
  `parser.py`'s `getloc`, from an "Unterminated function call") on a real
  kernel Makefile construct. Minimize the failing input to a small fixture
  under `tests/files/` before patching the parser.
- [ ] Effects: implement `shell`/`eval` as *actually executed*, not just
  diagnosed-incomplete — a real command-runner effect boundary (cwd/env,
  capture stdout/stderr/exit, timeout), gated behind an explicit opt-in
  flag, run against the real captured source tree. `shell` calls that
  probe the host/toolchain (`$(shell $(CC) --version)`-style) are common
  in real Kbuild and directly determine build membership in some cases;
  reporting them as "incomplete" forever, the way M0's implementation
  does today, is a correctness gap the M1/M1.0 real-build validation loop
  will directly expose as false positives/negatives — this is not
  optional polish, it's required for the headline experiment to mean
  anything on a tree that uses `shell`. Guarded `error` becomes path
  termination distinct from "unsupported". Add a regression fixture per
  construct, and feed every construct decision into M4's coverage census
  below (modeled vs. correctly-out-of-scope vs. deliberately unsupported
  with an honest diagnostic — not every construct needs real execution;
  see M4).
- [ ] Root invocation: model `ARCH`/`SRCARCH`/`CROSS_COMPILE`/`O`/`srctree`/
  `objtree` as an explicit invocation context threaded through `alg.py`'s
  traversal, replacing the hand-curated `top_dirs` ini list with real
  root-Makefile reachability. Validate against the checked-in snapshot
  first, then a fresh full-source acquisition.
- [ ] Kconfig validity: a minimal constraint layer that imports a subset of
  Kconfig's dependency/select/choice/tristate rules and answers, using the
  existing Z3 solver, whether a reported Make-level condition `P(file)` is
  satisfiable *and* consistent with Kconfig's own validity constraints `K`
  (i.e. query `K ∧ P(file)`, not just `P(file)` alone) — so "Make-satisfiable"
  and "Kconfig-valid" become two distinct, separately reported
  qualifications rather than being conflated.
- [ ] Run M1.0's witness-generation-and-real-build tool (unchanged, it's
  generic) against a pinned Linux release, x86 first.
- [ ] Only after the above: attempt a second architecture (arm64) and a
  default-config sweep, to get an RQ1/RQ2-style coverage number for the
  paper rather than a single anecdote.

## M3 — coreboot (new target)

Not attempted at all yet. coreboot's build is Kbuild-*derived* but not
identical: stage-based object lists (`bootblock-y`, `verstage-y`,
`romstage-y`, `ramstage-y`, `postcar-y`, `smm-y` instead of `obj-y`/`lib-y`),
its own Kconfig dialect, and `Makefile.inc` instead of `Kbuild`/`Makefile`
as the per-directory entry point.

- [ ] Read a pinned coreboot checkout's top-level `Makefile`/`Makefile.inc`
  and one representative `src/**/Makefile.inc` before writing any config —
  confirm the stage-variable names and entry-point filename above are
  actually current, don't assume from memory.
- [ ] Extend `Settings`/`skbuild.ini` to accept a configurable *set* of
  target-variable prefixes (currently hardcoded to `obj-`/`lib-` in
  `Settings.__init__`) and a configurable per-directory entry-point filename
  list (currently hardcoded `Kbuild`/`Makefile` in `kbuild.py`/`alg.py`).
  This is a small, general change that both coreboot and any future target
  need — do it once, not as a coreboot-specific hack.
- [ ] Write `tests/coreboot_skbuild.ini` (or wherever the convention lands)
  and a minimal fixture under `Tests/Fixtures`/`tests/` exercising the
  stage-object pattern end to end before pointing at the full tree.
- [ ] Acquire a pinned coreboot release, run M1.0's witness-generation-and-
  real-build tool for at least one board (coreboot calls its config
  `.config` too, generated via `make menuconfig`).
- [ ] Acceptance: same bar as M1/M2 — one pinned release, a Z3-derived
  witness set, real builds run per witness, predicted-vs-actual reconciled
  with the `Settings`/entry-point generalization above landed (not a
  one-off script).

## M4 — Engine hardening for paper-quality evaluation numbers

- [ ] Construct-coverage census (this is RQ2 in the paper, and the direct
  answer to "the current code doesn't support many things in real Kbuild
  files"): instrument the parser/evaluator to count, per construct kind,
  how many times each real project (BusyBox/coreboot/Linux) actually uses
  it, then classify every construct into exactly one of three buckets —
  mirroring `../cybolic/paper/cybolic.tex`'s RQ2 methodology:
  - *Modeled*: has real symbolic semantics today (or gets them via M2's
    effects work).
  - *Correctly out of scope*: affects recipes/linking/installation, not
    which files are selected, so a no-op is provably harmless (e.g.
    `.PHONY`, most recipe bodies) — say so explicitly rather than silently
    ignoring.
  - *Deliberately unsupported*: does affect file selection and is not yet
    modeled — report exactly which construct and how many real-file
    predictions it could plausibly affect, the way cybolic's
    `get_filename_component` discussion (its most-invoked, plausibly-
    file-affecting unmodeled command) does, rather than a bare "N warnings"
    count. Prioritize M2's effects work using this census's actual
    frequency data, not intuition about what real Kbuild "probably" uses
    most.
- [ ] Oracle/differential test suite: one small fixture + real-GNU-Make-oracle
  case per construct, under `Tests/Examples/<id>/`, at minimum covering:
  `obj-$(CONFIG_X)` Boolean/tristate selection; nested `ifeq`/`ifdef` guards;
  `:=`/`=`/`+=`/`?=` flavor and timing semantics; computed/expanded variable
  names; `define`/`call`/`foreach`/`eval`; effects inside an unselected
  branch (must not mutate state); guarded `error` (terminates only the
  affected path); include plus generated include; wildcard/filesystem
  sensitivity; and the two correctness bugs found this session
  (conditional-name `:=` overwrite; branch-guard re-gating at merge) as
  permanent regression cases.
- [ ] Basic performance instrumentation: wall time, peak RSS, number of
  `set_var` calls, number of Z3 `is_sat`/`is_valid` calls, per analyzed
  tree — cybolic's `paper/cybolic.tex` RQ3 (profiling the dominant cost) is
  the template; skbuild's dominant cost is plausibly Z3 call count under
  deep nesting, but confirm with data rather than assuming.
- [ ] Decide and document skbuild's own answer to cybolic's "eager merge
  cost" finding: does condition-expression size stay bounded on Linux-scale
  nesting, or does it need the same kind of factoring/case-cond-pruning
  cybolic's `sym.py` `_optimize_switch_generic` does? Only build that if
  profiling on M2's real Linux run shows it's needed.
- [ ] Durable output: the CLI still only prints a tmpdir path and requires
  loading `Analysis` programmatically to query results (see
  `src/skbuild.py`, `src/analysis.py`). Add a `--json`/query surface before
  writing the evaluation section, so RQ tables can be generated from real
  command output, not ad hoc scripts.

## M5 — Paper prep

Target venue/format: FSE (PACMSE), acmart `acmsmall,screen,review`, same as
`../cybolic/paper/cybolic.tex`. Structure and prose style: `cybolic.tex`
for the CMake-analogous parts (worked example, branch/merge representation,
RQ-driven evaluation, per-category Related Work, candid Discussion/Threats),
and Ishimwe/Nguyen/Nguyen 2021 ("Dynaplex", OOPSLA) for the
contributions-bullet-list-after-abstract convention, the crisp one-paragraph
Conclusion, and the plain, hedge-honestly sentence style throughout.

- [ ] `paper/skbuild.tex` skeleton created this session (mirrors
  `cybolic.tex`'s document class/macros). Fill in as milestones above land:
  - [ ] Introduction: motivation is drafted from `paper/NOTES.md` — revise
    once M2/M3 give real numbers to cite instead of "preliminary".
  - [ ] Overview / worked example: use `tests/paper_example/Makefile` (the
    same fixture already used to hand-verify M0's branch/merge fix) as the
    running example, the way cybolic uses a small worked `CMakeLists.txt`.
  - [ ] Design section: single-state guarded-value representation,
    branch/merge, and how it differs from (and was directly inspired by)
    cybolic — cite `nguyen2022analyzing` the same way cybolic's paper does,
    and describe skbuild's own domain-specific angle (finite Kconfig
    domains vs. cybolic's CMake `option()`/cache-variable domains).
  - [ ] Evaluation, RQ-shaped (RQ4 is the headline result — see M1.0):
    - RQ0 Fork-per-branch does not scale — the before/after measurement
      motivating \Cref{sec:design} (see \Cref{sec:eval:motivation} in the
      skeleton).
    - RQ1 Applicability — does it run to completion on real BusyBox,
      coreboot, and Linux (M1–M3's acceptance criteria, literally).
    - RQ2 Coverage — the M4 construct-coverage census: per project, which
      real Kbuild/Makefile.inc constructs are modeled, correctly out of
      scope, or deliberately unsupported, with real usage-frequency counts
      (cybolic's RQ2 table is the exact template).
    - RQ3 Performance — wall time / memory / Z3 call counts across the
      three projects (needs M4's instrumentation).
    - RQ4 Agreement with real builds — M1.0's Z3-witness-generation +
      real-build validation loop: true/false positive/negative object
      counts per project, every non-match causally categorized. This is
      the experiment that actually tests soundness against ground truth,
      not just internal consistency, and should be positioned as the
      paper's central empirical contribution.
  - [ ] Related Work: variability-aware analysis (kmax and similar Kbuild
    literature — `src/README.org`'s "Existing works" note already flags
    kmax specifically as a prior point of comparison; check what it does
    with the right-hand side of Kbuild assignments before citing it),
    CMake/cybolic, general symbolic execution, Kconfig tooling.
  - [ ] Discussion / Threats to validity: unsound on unmodeled `shell`
    effects until M2's effects work lands; partial Kconfig-validity
    modeling; single architecture per run; historical-snapshot vs.
    live-release version drift — write this section candidly, don't soften
    it for the paper.
  - [ ] Conclusion: one paragraph, no new claims, matching Dynaplex's
    conclusion length/tone.
- [ ] Artifact: decide what "Tool and evaluation artifacts available at
  ..." (cybolic's footnote convention) points to for this paper — a public
  repo, a Zenodo archive (Dynaplex's approach), or both.
- [ ] Internal review pass against `paper/NOTES.md`'s existing "Writing
  cautions" list (don't claim GNU Make compatibility; don't call an
  incomplete report a complete build graph; never describe skbuild as a
  build executor) before circulating a draft.

## Sequencing note

M0 is done except the two cleanup bullets. M1.0 (the witness-generation
and real-build validation tool) is the fastest remaining path to a
genuine RQ4 data point, is reused unchanged by M2/M3, and should be built
before M2/M3's much larger lifts. M1.1 (running it on BusyBox) will likely
pull in a small, BusyBox-scoped slice of M2's "effects" work early, since
BusyBox's own root Makefile already uses `shell`/`error` — that's fine and
expected; don't block M1.1 on all of M2 finishing first. M4's oracle suite
and construct-coverage census should start in parallel with M1 rather than
waiting for M2/M3, since the fixtures it needs (paper_example, small
E-series cases) already exist and the census itself needs real per-project
data that M1.1's BusyBox run will start producing. Do not start M5's
evaluation subsections until at least M1 is complete with real numbers —
placeholder numbers in a paper draft have a way of becoming load-bearing.
