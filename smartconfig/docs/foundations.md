# SmartConfig foundation audit (M0–M1)

## Upstream

The implementation starts from `mjbommar/autokernel` at revision
`bf5d6cf` (`Merge origin/master (kconfig-inventory / reboot-candidate work)`).
The checkout retains the `origin` remote and the upstream MIT `LICENSE` and
copyright notices. Existing collectors, snapshot models, CLI, build pipeline,
Kconfig surface walker, and `config_check` remain available and are not
replaced.

## Reuse map

| Area | Decision | Evidence |
|---|---|---|
| CLI and models | reuse | `src/autokernel/cli.py`, `src/autokernel/models.py` |
| native build preparation | extend/retain | `src/autokernel/build.py:prepare` |
| Kconfig introspection | reuse as optional enrichment | `src/autokernel/kconfig_walk.py` |
| pre-build static checking | reuse | `src/autokernel/config_check.py` |
| isolated authoritative normalization | add | `src/autokernel/smartconfig.py` |
| declarative requirements/report | add | `src/autokernel/smartconfig.py` |

The new checker is standard-library based at runtime and keeps cloud/LLM
imports out of the checking path. It calls native `make` with an argv list,
`O=<run-directory>`, `ARCH=<arch>`, a C locale, and a bounded timeout. Source
trees must be trusted because kernel Makefiles execute code.

## Backend decision

Native Kconfig normalization is authoritative. The existing kconfiglib-backed
surface walker is useful for explanation metadata, but remains optional and
does not certify an effective configuration. oddlama/autokernel was not added
as a dependency in M0–M1; its bridge remains a follow-up comparison item.

## Supported/unsupported cases

The first slice targets x86-64 Linux and requires a target source tree whose
native `make olddefconfig` succeeds. It reports incomplete execution when
normalization fails. It does not infer hardware requirements, certify runtime
behavior, validate firmware, or promise compatibility for non-x86 targets.
