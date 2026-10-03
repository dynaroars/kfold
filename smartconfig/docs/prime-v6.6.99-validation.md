# Prime real-kernel validation record

Executed against the root-collected snapshot at `/home/tnguyen/smartconfig-snapshot`.

## Source and configuration

- Source: Linux `v6.6.99`, extracted at `/tmp/smartconfig-kernels/linux-6.6.99`
- Native `defconfig`: requirements failed for `CONFIG_OVERLAY_FS` and `CONFIG_TUN`
- Candidate: explicitly enabled OverlayFS, TUN, KVM, and KVM Intel provider
- Candidate normalization: pass
- Candidate idempotence: pass
- Candidate hard requirement violations: 0

## Build

- Isolated output: `/tmp/prime-smartconfig-v6.6.99/kernel-build`
- Command: native `make ARCH=x86_64 -j8 bzImage modules`
- Result: pass
- bzImage: 13,947,904 bytes
- bzImage SHA-256: `2b41a439cef89bd97ad575d2502e730ea01e241f4423a3c30f41a2c6cc6166bb`
- vmlinux: 52,578,168 bytes
- vmlinux SHA-256: `d863d6b9c9de0e4136226cd61a287ddde5995e24aabecbe5d149570542109f59`
- Isolated `modules_install` staging: `/tmp/prime-smartconfig-v6.6.99/module-stage`
- Staged module files inventoried: 9

## VM gate

- Method: QEMU kernel-only, TCG, 512 MiB, one vCPU
- Result: PASS
- Duration: 4.8 seconds
- Verdict: kernel reached rootfs lookup without an earlier panic
- Recorded at: `/tmp/prime-smartconfig-snapshot-vm/boot-test.json`

The test used a disposable copy of the snapshot because this execution
environment mounts `/home/tnguyen/smartconfig-snapshot` read-only. The
physical-host snapshot was not changed. This is a VM smoke pass only; it does
not certify physical hardware, firmware, initramfs, packaging, or bootloader
behavior.

The same workflow was also completed for Linux `v6.12.99`:

- Build and final native configuration validation: PASS; idempotent, with zero candidate violations.
- bzImage SHA-256: `b51597324ab81dee1d641c446cf99aa4f7c1e87116d9514d9bd53cbd282b8efa`
- QEMU kernel-only boot smoke test: PASS in 5.0 seconds.
- Build report: `/tmp/prime-smartconfig-v6.12.99-native/linux-6.12.99/validation/report.json`
- Artifact report: `/tmp/prime-smartconfig-v6.12.99-native/linux-6.12.99/built-artifacts.json`
- VM record: `/tmp/prime-smartconfig-snapshot-vm-612/boot-test.json`

## Stable-series matrix

The same Prime running configuration and six-recipe requirements were checked
against three extracted exact stable trees:

| Target | Mapping | Idempotence | Hard violations | Status |
|---|---:|---:|---:|---|
| v5.15.99 | 6/6 | pass | 0 | incomplete: native warnings |
| v6.6.99 | 6/6 | pass | 0 | incomplete: native warnings |
| v6.12.99 | 6/6 | pass | 0 | incomplete: native warnings |

The warnings are expected cross-version evidence: Prime’s running 7.1 config
contains values invalid or unavailable in older targets. The checker keeps
these results provisional instead of treating normalization as a safety proof.
