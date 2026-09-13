# Baseline summaries

`fixture-2026-09-13.json` records a clean-revision baseline for the checked-in
Linux and BusyBox fixture snapshots. It is a measurement checkpoint, not a
complete-release correctness claim: both inputs are historical partial
snapshots and both reports are incomplete.

The summary records input digests, commands, toolchain/machine, timing, peak
RSS, result counts, diagnostic classes, and hashes of the raw report/stderr.
The raw Linux report is intentionally not checked in because it is approximately
47 MiB. Recreate artifacts with:

```sh
tools/record_baseline.py --output-dir /tmp/skbuild-linux-baseline \
  tests/linux/linux_orig --tristate
tools/record_baseline.py --output-dir /tmp/skbuild-busybox-baseline \
  tests/busybox/Makfiles_only/busybox_orig --tristate
```
