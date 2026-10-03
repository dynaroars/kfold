# SmartConfig: implementation plan and agent checklist

Prepared 13 September 2026. Working name; check naming conflicts before public release.

## 0. Start here — first implementation assignment

Read Sections 1–4 for the product decisions and execution rules, then implement M0 and M1 in Sections 5–6. Complete gate G0 before moving to later milestones. Sections 7–13 describe the subsequent implementation sequence; Sections 14–17 provide evaluation, maintenance, gates, and references.

Implement M0 and M1 only, starting from https://github.com/mjbommar/autokernel and reusing its MIT-licensed implementation. Use a development branch from a recorded upstream revision; preserve license/copyright notices. Run its existing tests and inspect the collectors, models, resolver, policy, config checker, apply/build flow, and CLI. First write a concise reuse/extend/fix/missing map tied to the checklist. Do not scaffold a replacement application.

Add or extend AutoKernel commands to compare baseline and candidate kernel configurations against an exact target source tree and declarative requirements. Reuse its CLI and models with compatible schema extensions. Normalize in isolated output directories using native Kconfig, record requested versus effective values, check all requirements after normalization, explain violations, and export stable JSON plus readable diagnostics. Add a validation hook after the last configuration-changing preparation step in the existing build pipeline, including localmodconfig and any restoration logic. A pre-build fragment check alone is insufficient. Add synthetic semantic fixtures and pinned real-kernel integration tests. Make a documented example work without root, API keys, or cloud access. Evaluate oddlama's native bridge and existing introspection code only for gaps in the current backend. Record unsupported cases explicitly. Preserve existing optional workflows; do not redesign collectors, packaging, bootloader integration, or LLM behavior without a demonstrated need. Do not add a new solver encoding in this assignment. Finish with runnable commands, baseline/new test results, the backend/reuse decision, and a remaining-work checklist.

## 1. Product decision

Build a Python command-line tool that helps Linux users understand, check, and maintain custom kernel configurations. Its first valuable operation is answering: “Does this proposed configuration conflict with the hardware and capabilities I want to keep?” It subsequently proposes conservative reductions, exports checked configuration fragments, and helps diagnose configuration regressions.

Primary initial users: people who already compile kernels—kernel testers, Gentoo/Arch enthusiasts, and developers doing repeated local builds. Debian and Fedora developers are useful early testers, but generic desktop users are not the initial market. Saving disk space alone does not justify taking over their kernel maintenance.

User-directed foundation: start from the MIT-licensed `mjbommar/autokernel` repository linked in this conversation. The user called it “autoconfig”; this plan interprets that as that exact AutoKernel repository, not an unrelated project. Extend its existing implementation. SmartConfig is the working name for the new capability, not a requirement to rename the repository or CLI.

Product promise: explain configuration changes using inspectable evidence; check declared requirements against the effective target configuration; report the limits of those checks. Never equate “configuration checked” with “all hardware will work.”

First release: local, deterministic, useful without an account, cloud service, LLM, solver, root privileges, or rebuilding the running kernel. A supplied target source tree and working build environment are required for authoritative target checks, not for basic inventory.

### Success criteria

- A new user can run an example and understand its report within ten minutes.
- An existing kernel builder can check their own candidate configuration and export a reproducible report.
- Every blocking finding identifies the requirement, evidence, actual value, expected condition, and a useful next step.
- Unknown or missing information remains visible. It is never converted into evidence that a feature is unnecessary.
- At least five independent testers use it on their own configurations; at least three use it again for another change or upgrade before expanding scope substantially. These are product decision targets, not research sample sizes.

### Correct earlier assumptions

- A list of retained options plus dependency closure does not establish functional preservation.
- Kconfig constraints are richer than Boolean implications. `select`, `imply`, defaults, hidden symbols, choices, tristates, and toolchain conditions matter.
- Kconfig-valid configurations can still fail to compile, boot, or run a workload.
- An installed package or loaded module suggests possible use; neither is a complete specification.
- Module history is an underapproximation of past observations, not a specification of future use.
- Smaller module packages do not imply proportionally lower resident memory, better performance, or fewer exploitable vulnerabilities.
- One-shot boot selection changes the next selection. It does not necessarily reboot a hung machine; physical reset or a separately configured watchdog may be needed.
- Audit, upgrade checking, tracing, and SAT solving all have prior art. Their combination needs empirical justification before claiming novelty.

## 2. Foundation and reuse decisions

Start from a pinned checkout of `mjbommar/autokernel`, create a development branch, and extend the existing Python application. Reuse its collectors, snapshot models, commands, config handling, packaging adapters, tests, and iteration machinery wherever suitable. Preserve the MIT license and copyright notices. Record the upstream revision and keep the upstream remote so later fixes can be incorporated. Creating a hosted fork or publishing changes is separate from preparing this local implementation.

Audit reuse rather than assuming correctness. For each requirement below, classify existing code as reuse unchanged, extend, fix, or missing, with file/function references and test evidence. Prefer adding a focused module or validation hook to replacing the pipeline. Refactor only where required by a concrete milestone; avoid a wholesale architecture rewrite. Isolate cloud/LLM imports so the checker works offline, while preserving the existing optional LLM workflow.

| Foundation | Reuse or learn from | Required boundary |
|---|---|---|
| mjbommar/autokernel | Primary codebase: existing collectors, snapshots, CLI, build/review/apply pipeline, tests, packaging and probation workflows | Reuse directly; verify behavior and extend checks; keep offline analysis independent of optional LLM/install execution |
| oddlama/autokernel | Native Kconfig bridge, checked assignments, dependency diagnostics, reusable configuration organization | Evaluate a subprocess adapter or upstream contribution; do not assume its internals are a stable public API |
| Kernel `conf`, `olddefconfig`, `diffconfig`, `merge_config.sh` | Target-tree normalization and effective configuration comparisons | Use isolated build/output directories and inspect all side effects |
| `localmodconfig` | Generate an optional aggressive candidate for comparison | It is a candidate producer, not a safety checker; pass output through all requirement checks |
| modprobed-db | Existing historical module usage | Import its data; preserve what is known about timing and coverage rather than invent timestamps |
| Kmax/krepair and ConfigFix | Constraint extraction, configuration repair, Kconfig semantic lessons | Optional research backend, evaluated on current target trees; don't write a fresh SAT encoding first |
| Existing distro build/initramfs tooling | Packaging and integration later | Keep distro security updates, signing, and recovery conventions; never start by writing a custom initramfs generator |

Keep the core Python. Start with the standard library, one CLI library, a schema/validation library if justified, and pytest. SQLite is sufficient for history. Do not add NetworkX, a database server, an eBPF subsystem, multiple solvers, Rust, or Lean until a demonstrated requirement needs them. Native adapters may use C or Rust when they substantially reduce semantic risk.

For the Kconfig backend, conduct a short spike with an explicit decision record: native `conf` is the authoritative normalizer; evaluate oddlama's bridge and maintained Python parsers for introspection. A parser that silently removes unsupported syntax is unacceptable. If introspection cannot handle a target, retain native checks and clearly reduce explanation coverage.

## 3. Agent execution contract

- [ ] Read repository instructions; use an existing user checkout if provided, otherwise clone the exact AutoKernel repository into an isolated workspace. Create a development branch and record the upstream commit before editing.
- [ ] Map milestones to existing implementation and tests before writing new code. Do not create a parallel standalone implementation of already-working AutoKernel functionality.
- [ ] Convert each milestone below into a tracked local checklist with task ID, status, acceptance evidence, and known limits. Do not create external issues unless separately asked.
- [ ] Implement milestones in order. Finish one usable vertical slice before broadening coverage.
- [ ] Keep one small end-to-end sample runnable throughout development.
- [ ] For each milestone report: changed behavior, commands to reproduce, tests performed, unsupported cases, next milestone.
- [ ] Document actual results. Never fabricate host runs, performance numbers, successful boots, user feedback, or supported kernels.
- [ ] If hardware is unavailable, complete fixture/VM work and list hardware-dependent gates as pending. Do not label them passed.
- [ ] Build and test only in disposable environments or expressly authorized targets. Exporting a plan is separate from executing it on a host.
- [ ] Finish at the requested milestone boundary; do not build every future feature in one autonomous implementation session.

## 4. Architecture and persistent records

Use these logical boundaries within the existing AutoKernel package; reuse its actual module names and models rather than imposing a new directory tree. Add modules only for missing responsibilities:

1. `collect`: inspect host evidence through adapters.
2. `requirements`: load user intentions and versioned capability recipes.
3. `kconfig`: inspect and normalize the exact target configuration.
4. `check`: evaluate requirements and explain changes.
5. `plan`: produce candidate edits and recheck the resulting effective configuration.
6. `history`: record observations, runs, and validation evidence.
7. `validate`: execute or describe scoped capability tests.
8. `cli`: render reports and stable machine-readable output.

### Minimum schemas

- **Target identity:** source commit or content digest, dirty-tree status/digest, architecture, relevant build variables, compiler identity, baseline hash, candidate hash, schema/backend versions. Release strings alone are insufficient. Detect source changes during a run.
- **Evidence:** stable ID, kind, collector/version, source locator, observation time, scope/host ID, status (`observed`, `unavailable`, `failed`, `not_applicable`), structured value, privacy classification. Negative observations require explicit scope, such as “no matching device among enumerated PCI devices.”
- **Requirement:** stable ID, origin (`user`, `profile`, `evidence`), strength (`required`, `preferred`), capability or symbol predicate, rationale, recipe version, target applicability, evidence references. System-suggested requirements remain distinguishable from user-confirmed ones.
- **Mapping:** evidence/module/object/capability to symbol predicates; target identity; provenance; method (`native`, `build_metadata`, `maintained_recipe`, `heuristic`); completeness/ambiguity status.
- **Finding:** stable ID, requirement ID, condition, observed value, severity, evidence path, explanation, suggested action, unresolved assumptions.
- **Plan:** explicit requested assignments, normalized effective configuration, all incidental changes, requirement-check result, proposed costs/benefits with measured/estimated labels, source/evidence/recipe hashes.
- **Validation:** test ID/version, environment (`fixture`, `VM`, `host`), kernel/artifact identity, capability facet, `pass/fail/skip/unknown`, duration, logs, preconditions, cleanup outcome.

Use atomic file writes and versioned JSON for interchange. Separate raw local evidence from sanitized exports. Prefer simple adjacency records for explanations; sophisticated graph analysis can be added later.

## 5. M0 — Establish a reproducible development baseline

Objective: prove the tool can inspect and normalize real configurations without touching the running system.

- [ ] Run the existing AutoKernel tests and development checks first; record baseline failures separately. Reuse its package, CLI, models, test layout, formatting, and CI. Check whether its minimum Python/dependency requirements unnecessarily block the intended offline checker users before changing them.
- [ ] Inspect at least `resolve.py`, `policy.py`, `config_check.py`, `build.py`, `boottest.py`, `iteration.py`, `cli.py`, model definitions, and their tests. Locate existing review/apply behavior and the final point at which a config can change.
- [ ] Verify project-name availability before packaging publicly; `smartconfig` is provisional.
- [ ] Record audited upstream versions, licenses, copied code, and adapter decisions in `docs/foundations.md`.
- [ ] Select two adjacent supported stable kernel series, one older LTS series, and a distro-patched source example. Pin exact revisions for tests; do not assume compatibility from a version range.
- [ ] Start with x86-64 Linux. State architecture limits explicitly.
- [ ] Build a tiny Kconfig fixture suite plus an integration harness for actual kernel trees.
- [ ] Extend AutoKernel's existing preflight/doctor behavior to report source identity, architecture, available config, and checker prerequisites. All `smartconfig ...` examples in this plan describe intended functionality; implement them as appropriate AutoKernel subcommands, reusing existing commands where possible.
- [ ] Implement subprocess execution with argv arrays, controlled environment, timeouts, cancellation, captured diagnostics, and no untrusted shell interpolation.
- [ ] Ensure fixture/read-only commands run offline and unprivileged.
- [ ] Establish a reproducible sample command in the README.

Acceptance: clean checkout installs in an isolated environment; `doctor` works on a fixture and a supported host; normalization runs in an isolated output directory; original inputs and host files are unchanged. Note that kernel Makefiles execute code: source trees used for normalization must be trusted or placed in an appropriate sandbox.

## 6. M1 — Build the configuration checker first

Objective: a useful tool even before hardware inference or minimization.

Proposed interface (commands are specifications to implement, not existing commands):

```sh
smartconfig check --source /path/to/linux --arch x86_64 \
  --baseline baseline.config --candidate candidate.config \
  --requirements requirements.yaml --out run/
smartconfig explain CONFIG_OVERLAY_FS --run run/
```

- [ ] Parse baseline/candidate assignments, preserving unknown names and conflicting duplicate assignments for diagnostics.
- [ ] Define a small declarative requirement language: `all`, `any`, `not`, exact values, allowed tristate values, typed ranges, and explicit target predicates. No embedded Python, shell, or Lua in third-party recipes.
- [ ] Separate direct assignments from predicates on effective values: a hidden symbol may be required without being user-assignable.
- [ ] Normalize baseline and candidate separately against the same target and environment. Report baseline incompatibilities separately from candidate effects.
- [ ] Preserve requested, normalized, and baseline configurations as distinct immutable artifacts.
- [ ] Report requested changes that did not take effect; symbols that disappeared; incidental changes; unavailable target introspection; native Kconfig warnings.
- [ ] Evaluate every hard requirement on the normalized candidate, never only on the input fragment.
- [ ] If native normalization produces warnings, preserve them and make affected checks provisional or blocked according to explicit diagnostic policy. Native output alone is not a logical safety proof.
- [ ] Verify idempotence on supported targets: normalizing the effective config again should not alter it under the same environment.
- [ ] Produce concise text plus versioned JSON. Proposed exit codes: 0 = all declared checks satisfied at this scope; 1 = violation; 2 = incomplete/unsupported check; 3 = execution error. Document precedence.
- [ ] Implement `explain` with a short causal chain and an explicit fallback when only structural evidence is available.

Mandatory tests:

- [ ] Boolean/tristate domains; `MODULES=n`; mandatory/optional choices; hidden symbols; conditional and ordered defaults; `select` versus dependencies; `imply`; numeric ranges; strings; architecture/toolchain conditions; removed/renamed options; syntax introduced by newer kernels.
- [ ] Turning off a parent makes an apparently retained child ineffective: the checker catches the resulting requirement violation.
- [ ] Direct `y` to `m` changes are rejected when a boot requirement needs built-in availability.
- [ ] Missing/unsupported metadata yields incomplete status, not success.
- [ ] Conflicting requirements produce clear diagnostics without silently relaxing the user's request.

Acceptance: a user can supply a candidate from any editor or generator and detect meaningful ineffective assignments and requirement conflicts. This milestone is already worth sharing with kernel builders for feedback.

## 7. M2 — Collect evidence and explain host relevance

Objective: connect checks to actual machines without pretending to know future needs.

- [ ] Reuse existing AutoKernel collectors and snapshot fields for running config discovery, PCI/USB modaliases, bound drivers, loaded modules, built-in module metadata, root filesystem and block-device stack, mounts, and basic boot context. Extend missing evidence/status fields with backward-compatible schema migration; add adapters only for uncovered sources.
- [ ] Label running-kernel evidence separately from target-kernel mappings. Never reuse a running module-to-symbol mapping as authoritative for a different target revision.
- [ ] Record collection failures individually and continue collecting independent evidence.
- [ ] Use existing metadata/interfaces before parsing human-oriented command output. Fix locale where unavoidable.
- [ ] Traverse block stacks sufficiently to identify supported plain, encrypted, and layered roots. Unsupported storage topology blocks confident boot-path conclusions.
- [ ] Inspect module dependencies/aliases and source/build metadata. A module can map to multiple objects or configuration predicates; retain ambiguity. Do not derive `CONFIG_` names by uppercasing module names.
- [ ] Implement a target mapping cache keyed by full relevant target identity.
- [ ] Record firmware dependencies as separate runtime assets; a Kconfig check cannot certify firmware availability.
- [ ] Add lightweight software signals only where they support a concrete recipe. Default network inspection should use connection types, not VPN credentials or endpoint contents.
- [ ] Add `scan --out snapshot/` and `check --snapshot snapshot/`.
- [ ] Permit snapshots to be collected on one host and analyzed/built on another.
- [ ] Document what cannot be collected unprivileged and offer explicit optional collectors; never re-run the entire CLI as root automatically.

Acceptance: two dissimilar host snapshots generate traceable hardware-related findings; disconnected peripherals and unknown target mappings remain explicit gaps. Sanitized fixtures are reviewed for identifiers and secrets.

## 8. M3 — Deliver a small, testable capability catalog

Start with six bounded capabilities: WireGuard interface support; KVM host support; OverlayFS mount support; TUN/TAP interface support; USB mass storage with explicitly chosen filesystems; configured root-storage support for supported topologies.

Treat Docker/Podman, Bluetooth audio, suspend, hibernation, GPU/display, USB-C docks, and Secure Boot as later composite capabilities. For example, creating an OverlayFS mount does not certify Docker networking, rootless containers, or device access.

- [ ] For each capability define exact scope, supported target context, evidence rules, required predicates, alternative providers, evidence provenance, test facets, and known exclusions.
- [ ] Cite primary documentation/source for each mapping and pin its tested applicability. Avoid broad “all kernels >= X” declarations without evidence.
- [ ] Separate observed/suggested capability use from confirmed requirements. Provide editable YAML plus an optional short interactive selection flow.
- [ ] Split composite capabilities by mode: KVM on Intel versus AMD; kernel WireGuard versus a userspace implementation; plain versus encrypted root; filesystem reading versus writing where relevant.
- [ ] Keep configured root/boot needs required when identified; unresolved boot-chain components remain blockers for reduction in that scope.
- [ ] Add recipe schema validation, positive/negative fixtures, conflicting-requirement tests, and target applicability tests.
- [ ] Add a contributor recipe template with required evidence and acceptance test instructions.
- [ ] Support user-local recipes with clear precedence and stable IDs; record exactly which recipe versions produced a plan.

Acceptance: for each supported capability, a deliberately incompatible normalized config produces a correct finding and a compatible config clears the configuration-level finding. Reports distinguish configuration availability, packaged module availability, runtime access permissions, and functional testing.

## 9. M4 — Add historical evidence and conservative candidate generation

Objective: make repeated builds smaller while preserving explicit requirements and exposing uncertainty.

- [ ] Import modprobed-db histories, retaining source/coverage limits.
- [ ] Add optional periodic lightweight collection using SQLite. Record sampling intervals, gaps, boot IDs, host identity, and module observations. Periodic sampling can miss brief loads; say so.
- [ ] Provide timer/service examples with explicit enablement. Core use must not require a daemon or weeks of training.
- [ ] Add `require`, `plan`, and `export` operations with a reproducible requirements file.
- [ ] First candidate policy: propose only a constrained set of module removals; preserve unrelated built-ins, hardening choices, and tuning settings. Unsupported mappings remain retained/unknown.
- [ ] Keep unobserved modules as reviewable candidates, not automatically “safe to remove.” Require an explicit trimming policy from the user.
- [ ] Offer `localmodconfig` plus historical module list as an alternative candidate producer for fair comparisons and advanced use.
- [ ] Apply candidate edits to a copy, normalize, inspect the entire resulting delta, re-evaluate all requirements and explicit preservation predicates, then export.
- [ ] Block export as a checked plan when hard requirements fail or checks are incomplete. Allow a clearly labeled raw diagnostic candidate export only through a separate explicit operation.
- [ ] Produce a fragment and complete effective config, plus source/recipe/evidence hashes and explanations.
- [ ] Estimate module-package size savings only from matching available artifacts; otherwise report counts or unknown. Do not add object sizes blindly when shared/compressed code makes them non-additive.
- [ ] Explain why a proposed trim was rejected after normalization.

Acceptance: plans are reproducible for fixed inputs; input-order changes do not change meaning; every effective change is reported; unseen-device uncertainty is visible; candidate generation cannot bypass M1 checks.

Release checkpoint: publish a pre-release for audit/check/plan/export users. Installation automation is not required for adoption at this stage.

## 10. M5 — Build artifact identity and scoped runtime validation

Objective: establish that tests actually apply to the candidate users are evaluating.

- [ ] Reuse AutoKernel build instructions/adapters and validate one distro path end to end first. Keep existing adapters available with honest validation status; do not replace them with a new build system.
- [ ] Reuse distro kernel packaging and existing initramfs generation. Record build provenance and unique release identity.
- [ ] Read back the final build's effective config and recheck requirements. Any later transformation, including localmodconfig, invalidates earlier certification until rechecked.
- [ ] Inventory the built module package and dependencies. Distinguish module configuration, actual package inclusion, and initramfs inclusion.
- [ ] Link validation records to exact artifacts, config, compiler, and source, not just `uname` text.
- [ ] Implement VM smoke tests and tests of virtualizable capability facets, with isolated scratch storage/network namespaces where appropriate.
- [ ] Run corresponding tests on the baseline first; a pre-existing failure is not a candidate regression.
- [ ] Tests record pass/fail/skip/unknown plus cleanup results and logs. Missing hardware or privileges means skip/unknown.
- [ ] Make tests declare effects: network changes, writes, suspend, reboot, external connectivity. Separate passive checks from disruptive tests.
- [ ] Provide a user-run physical-host checklist for audio, display, suspend/resume, dock reconnection, and other non-virtualizable behavior as those recipes mature.
- [ ] Initially generate explicit installation/trial instructions and preserve the known-good kernel. Automate one bootloader/distro combination only after disposable-VM failure testing validates its actual behavior.
- [ ] Treat Secure Boot, signing, DKMS, encryption, remote-only hosts, and insufficient boot-space handling as adapter support gates. Unsupported cases keep export/manual workflows available.

Acceptance: baseline/candidate tests are attributable to their real artifacts; a VM pass cannot mark physical-device tests passed; failures retain logs and recoverable state; no automatic promotion to default occurs because only a VM test passed.

## 11. M6 — Diagnose configuration regressions

Objective: reduce the time users spend finding the option that broke a capability.

- [ ] Accept a known-good and failing configuration built from the same source/toolchain, plus a reproducible test command or named capability test.
- [ ] Establish baseline pass/candidate fail, repeating sufficiently to detect flakiness. Return inconclusive for unstable tests.
- [ ] Restrict candidate causes using effective config delta, capability provenance, and observed failure scope.
- [ ] Implement dependency-aware grouped delta debugging: normalize and validate each trial; record incidental changes rather than treating requested bits as independent.
- [ ] Cache by effective config and test/environment identity. Deduplicate trials that normalize to the same config.
- [ ] Distinguish invalid, build-failing, test-failing, passing, and inconclusive trials.
- [ ] Bound builds, elapsed time, and reboots; support resume. Start with VM-reproducible failures, not unattended physical-host reboot loops.
- [ ] Return a failure-inducing set relative to the oracle and search performed. Claim 1-minimality only if verified; never claim global minimum by default.
- [ ] Confirm the proposed repair restores the failed test and does not regress the existing selected suite.
- [ ] Store a learned constraint as local, scoped empirical evidence. One repaired test does not justify a universal upstream rule.

Acceptance: diagnose at least three real/reproduced failures and a multi-option interaction under a fixed budget; demonstrate that diagnosis saves builds versus a simple baseline. Synthetic cases alone do not establish practical value.

## 12. M7 — Preserve requirements across kernel upgrades

- [ ] Carry user-level requirements and their provenance to the new target.
- [ ] Re-extract target mappings and normalize both migrated baseline and candidate.
- [ ] Classify removed symbols, changed defaults/dependencies, newly unavailable providers, unresolved mappings, and changed effective values.
- [ ] Suggest renames only when supported by source history or maintained mappings; textual similarity is not semantic equivalence.
- [ ] Reuse test evidence only when its scope remains justified; changed target identity requires new candidate validation.
- [ ] Produce a compact report organized by affected capability with detailed symbol diff available.
- [ ] Compare against native olddefconfig/diffconfig and oddlama/autokernel to demonstrate additional user-level value.

Acceptance: exercise at least two real upgrade pairs and one distro-patched target; catch at least one capability-level issue that a plain syntactic diff does not explain adequately. Cross-version runtime regressions may be code bugs, so do not automatically blame configuration.

## 13. M8 — Optional constraint-guided research backend

Begin this only after checker semantics and real-user workflows are working.

- [ ] Evaluate Kmax/krepair/ConfigFix-derived methods against the target matrix and document extraction coverage and maintenance burden.
- [ ] Select one SAT/SMT/MaxSAT backend based on measured fit; avoid implementing several solver integrations at once.
- [ ] Preserve tristate domains, provider alternatives, explicit boot-stage availability, and user constraints in the model.
- [ ] First objective: repair a conflicting requested configuration with few effective changes. Subsequent objective: reduce measured/estimated cost subject to fixed requirements and explicit preservation policy.
- [ ] Keep cost models honest: symbol count is a proxy; build time, package size, and resident memory are distinct objectives.
- [ ] Round-trip every proposed assignment through the native target configurator and recheck requirements.
- [ ] Record extraction/model disagreements, refine or reject the result, and bound retries. Native normalization is a check, not proof that the extraction is complete.
- [ ] Support time budgets and feasible results; claim optimality only relative to the encoded objective/model with a justified solver result.
- [ ] Compare solver repair against greedy restoration and solver synthesis against conservative rule-based planning at equal budgets and requirements.

Candidate research hypothesis: combining version-specific configuration/build evidence, explicit user requirements, and test-guided repair reduces functional regressions and repair cost at comparable build/package reductions versus module-history baselines.

The weak version—handwritten YAML plus a solver—is useful engineering but not automatically a strong research paper. Stronger contributions would be automatically extracting/maintaining capability mappings, accurately localizing configuration-induced failures despite normalization, or demonstrably reducing the cost of requirement-preserving upgrades.

Symbolic execution is optional targeted work for a demonstrated missing test or dependency inference problem. Whole-kernel symbolic execution and Lean are outside the implementation roadmap until a concrete experiment establishes their incremental value.

## 14. Evaluation plan

### Product pilot

- [ ] Recruit five independent kernel builders through opt-in outreach, after a runnable release exists. Prepare messages; sending is a separate authorized action.
- [ ] Observe installation, first useful finding, unclear diagnostics, config export, and repeat use.
- [ ] Track time to first useful result, environment failures, report usefulness, and whether users keep using the tool.
- [ ] Prefer anonymized issue templates and voluntary reports over built-in telemetry.

### Research evaluation

- [ ] Freeze baselines and exact revisions. Include distro baseline, localmodconfig, localmodconfig plus history, relevant AutoKernel paths, and recent configuration-debloating systems where reproducible.
- [ ] Treat ConfigFix/krepair/oddlama as task-specific baselines for conflict repair, patch/config constraints, and assignment/upgrade checking, rather than pretending each is an end-to-end hardware minimizer.
- [ ] Use the same kernel, compiler, architecture, compression, hardening policy, input history, and declared requirements wherever feasible. The earlier AutoKernel headline compares different kernel versions; do not use it as a controlled effect estimate.
- [ ] Independently curate tests and expected requirements; avoid evaluation where recipes define their own oracle.
- [ ] Hold out workloads and devices from observation: e.g. a disconnected USB device or a VPN first used after planning. Distinguish declared-but-unobserved needs from wholly undeclared future behavior.
- [ ] Include negative controls: filesystem corruption, firmware absence, runtime permissions, and network outages must not be falsely diagnosed as configuration omissions.
- [ ] Measure declared capability facets preserved, false alarms, unresolved rate, incidental changes, build/package reduction, analysis latency, trace overhead, repair builds/time, upgrade effort, and manual interventions.
- [ ] Report denominators, exclusions, incomplete cases, and per-host variation. Multiple VMs sharing hardware do not replace hardware diversity.
- [ ] Expand to a broader hardware/distro sample only after a pilot estimates variance and establishes feasibility; do not commit to arbitrary machine counts before knowing recruitment cost.
- [ ] Run ablations: no history; no explicit requirements; no native normalization check; no provenance-guided diagnosis; solver versus simple planner. Unsafe variants belong only in disposable evaluation environments.

## 15. Adoption and maintenance work

- [ ] Keep the first command useful: ship sanitized example snapshots and configs, plus an offline walkthrough.
- [ ] Support common Python installation methods; document a distro support matrix by feature: collection, target checking, building, and boot integration separately.
- [ ] Package for one community with a maintainer willing to sustain it; expand based on requests rather than claiming six distros from command-name detection.
- [ ] Provide stable JSON schemas, exit codes, plain-text output, shell completions, and concise remediation examples.
- [ ] Document an explicit release compatibility matrix and test new kernel changes regularly; pin dependencies and publish migration notes for persisted data.
- [ ] Keep contribution paths small: a fixture, recipe correction, collector fix, or diagnostic example should be a manageable first contribution.
- [ ] Offer integration instructions for AutoKernel and existing build scripts; checked fragments/configs and JSON reports are the initial interoperability interface.
- [ ] Support collect-on-laptop/analyze-on-server without copying private raw data unnecessarily.
- [ ] Before public release review license compatibility and notices for all copied code; do not assume importing a project permits arbitrary relicensing of its source.
- [ ] Publish actual examples of prevented breakage and time saved. Avoid “AI-optimized,” “provably safe kernel,” and unsupported security/performance claims.
- [ ] Publish a clear maintenance scope and a way to report a kernel-version regression with sanitized reproduction data.

## 16. Milestone gates and stop conditions

| Gate | Deliverable | Evidence needed to proceed |
|---|---|---|
| G0: M0–M1 | Deterministic standalone checker | Native normalization and semantic edge-case tests work on pinned targets |
| G1: M2–M3 | Host-aware capability report | Six bounded recipes, traceable findings, honest unknown states |
| G2: M4 | Conservative plan/export release | Repeatable plans; early testers obtain useful findings without installation integration |
| G3: M5 | Artifact-bound validation | Baseline/candidate tests and exact final-config attribution |
| G4: M6–M7 | Regression/upgrade assistant | Real reproducible failures diagnosed; measured user effort reduced |
| G5: M8 | Research backend | Clear improvement over simpler methods at controlled budgets |

If the native semantics backend is unreliable, stop synthesis and repair its compatibility. If mapping coverage is too weak, ship precise symbol checks rather than inventing capability certainty. If users find no actionable benefit beyond existing tools, revise the workflow before adding solvers. If physical-host trial integration is unreliable, keep manual installation/export. If a learned rule cannot be supported beyond one host, keep it local.

Suggested sequencing is approximately 2–3 focused weeks for a checker/fixture prototype, another 3–5 for host evidence and a small catalog, then a pilot. These are planning ranges for a capable developer with Linux expertise, not delivery promises or estimates of autonomous-agent wall time. Hardware validation, distro integration, and maintenance will take longer than the Python CLI.

## 17. Sources and prior-art starting points

These inform the plan; repository claims are not independently verified operating guarantees. Resolve current revisions during M0.

- mjbommar/autokernel: https://github.com/mjbommar/autokernel
- Its build pipeline: https://github.com/mjbommar/autokernel/blob/master/src/autokernel/build.py
- oddlama/autokernel: https://github.com/oddlama/autokernel
- Native Kconfig language: https://docs.kernel.org/kbuild/kconfig-language.html
- Native configuration targets: https://docs.kernel.org/kbuild/kconfig.html
- Kernel trimming guide and historical-module caveats: https://docs.kernel.org/admin-guide/quickly-build-trimmed-linux.html
- modprobed-db: https://github.com/graysky2/modprobed-db
- Kmax/krepair: https://github.com/paulgazz/kmax
- ConfigFix: https://github.com/isselab/configfix and https://arxiv.org/abs/2012.15342
- AutoOS (ICML 2024): https://proceedings.mlr.press/v235/chen24at.html
- Kernel debloating practicality: https://sibin.github.io/papers/2020_SIGMETRICS_Cozart_HsuanChiKuo.pdf
- Recent configuration debloating artifacts: https://github.com/akshithg/leanos-artifacts

Before formulating a paper claim, read and reproduce the closest current approaches. A product roadmap is not a completed novelty assessment.

