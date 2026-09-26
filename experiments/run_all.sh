#!/bin/sh
# Run the canonical evaluation end to end (see experiments/README.md).
# Long steps: the Linux builds (hours) and Kmax on Linux (about 1.5 hours).
set -e
cd "$(dirname "$0")/.."
python3 experiments/fetch.py
python3 experiments/build.py
python3 experiments/check_kconfig.py
python3 experiments/evaluate.py --variants full,no_includes,no_rules,no_link_semantics
python3 experiments/timing.py
python3 experiments/kmax.py busybox linux
python3 tools/bench_scaling.py --out results/bench_scaling.json
python3 experiments/devtasks.py why
python3 experiments/devtasks.py config-for
python3 experiments/devtasks.py compile
python3 experiments/devtasks.py blindspots
python3 experiments/paper_numbers.py
