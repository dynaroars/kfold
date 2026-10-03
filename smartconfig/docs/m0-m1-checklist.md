# M0–M1 execution checklist

| ID | Status | Acceptance evidence / limit |
|---|---|---|
| M0-01 | done | Upstream revision `bf5d6cf` audited; MIT license and remote retained. |
| M0-02 | done | `docs/foundations.md` records reuse/extend decisions and backend boundary. |
| M0-03 | done | `smartconfig doctor` reports Python, make, source, Kconfig, and Makefile prerequisites. |
| M0-04 | done | Native normalization uses argv, `O=<run>`, C locale, timeout, captured log, and no source mutation. |
| M0-05 | done | Offline fixture command is documented in `README.md` and passes. |
| M1-01 | done | Parser preserves disabled values, duplicates, and unparsed lines. |
| M1-02 | done | JSON/YAML (when PyYAML is installed) requirement input supports `all`, `any`, `not`, exact/allowed values, and numeric ranges. |
| M1-03 | done | Baseline and candidate normalize independently; requested/effective differences and baseline violations are reported. |
| M1-04 | done | Versioned, sorted JSON report and native diagnostics are written under the run directory. |
| M1-05 | partial | Fixture covers parent/child ineffective assignment. Full real-kernel matrix and all Kconfig semantic cases remain pending. |
| M1-06 | partial | `explain` provides finding-based diagnostics; structural causal explanations from Kconfig introspection remain pending. |

## Verification

Focused command:

```sh
.venv/bin/python -m pytest -q tests/test_smartconfig.py \
  tests/test_config_check.py tests/test_kconfig_walk.py
# 29 passed
.venv/bin/python -m ruff check src/autokernel/smartconfig.py tests/test_smartconfig.py
# All checks passed
```

The upstream full-suite run reached 344 passing tests before the first
environment-dependent failure: `test_execute_invokes_apt_install` attempts
to execute apt in this read-only sandbox and receives `OSError: [Errno 30]`.
No project test failure was caused by the SmartConfig slice. Hardware,
real-kernel integration, and distro build gates are not claimed as passed.

## Continued TODO progress (M2–M3)

The existing AutoKernel `scan` command and typed `Snapshot` model are reused.
SmartConfig now accepts `--snapshot` and records host evidence counts plus an
explicit running-kernel/target-kernel boundary. A versioned built-in catalog
defines six bounded configuration-level recipes (`wireguard`, `kvm-host`,
`overlayfs`, `tun-tap`, `usb-mass-storage`, and `root-storage`) with user-origin metadata,
scope, alternatives, and exclusions. Root-storage support and target-specific
mapping caches remain pending because they require pinned real-kernel source
evidence.

The first M4 planning boundary is also available: `smartconfig plan` applies
only explicit removals to a copied baseline, normalizes and rechecks them, and
writes `effective.config` only for a passing plan. A failing plan is marked
`blocked`; it cannot be exported as a checked configuration.

Additional bounded workflows now cover M6/M7 software-only stages:
`diagnose` tests each changed symbol trial with an optional shell-free test
argv and reports a relative failure-inducing set without global-minimality
claims; `upgrade` compares effective values across two exact target trees and
rechecks requirements on the new target. Runtime, package, boot, and hardware
validation are still required before those workflows can certify a kernel.

Target mappings are now emitted by `smartconfig map` with a target identity,
method, symbol predicates, and `complete`/`unknown` status. Native
introspection failures remain visible and do not become evidence of support.

M5 artifact handling now includes hash-bound kernel/config/module inventory
(`artifacts`) and a validation record with explicit `pass/fail/skip/unknown`
states (`vm-test`). On the Prime snapshot, Linux 6.6.99 and 6.12.99 both
completed native builds, final configuration validation, artifact inventory,
and QEMU boot smoke tests. The VM test only certifies that the kernel reaches
rootfs lookup; it does not certify physical hardware or a usable installed
system.

The M4 evidence boundary is implemented with `smartconfig history`: imported
module lists are hashed and labeled with source-file scope, unknown timing,
and explicit absence semantics. M5’s configuration-level artifact gate is
implemented with `smartconfig validate`, which runs native normalization and
the complete requirement check for a final config. Package identity and
initramfs inclusion remain pending. Linux 5.15.99 was checked successfully but
its full build is currently incompatible with the host GCC 16 toolchain; no
5.15 build is claimed. Physical-host validation remains pending.
