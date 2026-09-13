#!/bin/sh
set -eu

project_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
tmp_dir=$(mktemp -d "${TMPDIR:-/tmp}/skbuild-e2e.XXXXXX")
trap 'rm -rf "$tmp_dir"' EXIT HUP INT TERM

PYTHONWARNINGS=ignore PYTHONPATH="$project_root/src" \
  python3 "$project_root/tools/pymake_ast.py" \
    "$project_root/tests/paper_example/Makefile" > "$tmp_dir/paper.json"

"$project_root/.lake/build/bin/skbuild" "$tmp_dir/paper.json" \
  | sort > "$tmp_dir/paper.bridge.actual"

"$project_root/.lake/build/bin/skbuild" \
  "$project_root/tests/paper_example/Makefile" \
  | sort > "$tmp_dir/paper.native.actual"

diff -u "$project_root/Tests/Golden/paper_example.expected" \
  "$tmp_dir/paper.bridge.actual"

diff -u "$project_root/Tests/Golden/paper_example.expected" \
  "$tmp_dir/paper.native.actual"

diff -u "$tmp_dir/paper.bridge.actual" "$tmp_dir/paper.native.actual"

"$project_root/.lake/build/bin/skbuild" \
  --config="$project_root/Tests/Fixtures/paper.config" \
  "$project_root/tests/paper_example/Makefile" \
  | sort > "$tmp_dir/paper.config.actual"

diff -u "$project_root/Tests/Golden/paper_config.expected" \
  "$tmp_dir/paper.config.actual"

"$project_root/.lake/build/bin/skbuild" \
  "$project_root/Tests/Fixtures/include/Main.mk" \
  | sort > "$tmp_dir/include.actual"

diff -u "$project_root/Tests/Golden/include.expected" \
  "$tmp_dir/include.actual"

"$project_root/.lake/build/bin/skbuild" \
  "$project_root/Tests/Fixtures/tree" \
  | sort > "$tmp_dir/tree.actual"

diff -u "$project_root/Tests/Golden/tree.expected" \
  "$tmp_dir/tree.actual"

"$project_root/.lake/build/bin/skbuild" \
  "$project_root/Tests/Fixtures/wildcard" \
  | sort > "$tmp_dir/wildcard.actual"

diff -u "$project_root/Tests/Golden/wildcard.expected" \
  "$tmp_dir/wildcard.actual"

"$project_root/.lake/build/bin/skbuild" --json \
  "$project_root/Tests/Fixtures/eval" > "$tmp_dir/eval.json"

python3 - "$tmp_dir/eval.json" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as stream:
    report = json.load(stream)

assert report["complete"] is True
assert report["diagnostics"] == []
by_path = {item["path"]: item for item in report["files"]}
assert set(by_path) == {"first.o", "second.o", "guarded.o"}
assert by_path["guarded.o"]["condition_text"] == "CONFIG_EXTRA=y"
PY

cp -R "$project_root/Tests/Fixtures/wildcard" "$tmp_dir/wildcard-cache"
"$project_root/.lake/build/bin/skbuild" --json \
  --cache="$tmp_dir/wildcard.cache.json" "$tmp_dir/wildcard-cache" \
  > "$tmp_dir/wildcard.cached.first.json"
touch "$tmp_dir/wildcard-cache/src/b.c"
"$project_root/.lake/build/bin/skbuild" --json \
  --cache="$tmp_dir/wildcard.cache.json" "$tmp_dir/wildcard-cache" \
  > "$tmp_dir/wildcard.cached.second.json"
python3 - "$tmp_dir/wildcard.cached.first.json" "$tmp_dir/wildcard.cached.second.json" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as stream:
    first = json.load(stream)
with open(sys.argv[2], encoding="utf-8") as stream:
    second = json.load(stream)
assert [item["path"] for item in first["files"]] == ["a.o"]
assert [item["path"] for item in second["files"]] == ["a.o", "b.o"]
PY

"$project_root/.lake/build/bin/skbuild" --json --cache="$tmp_dir/tree.cache.json" \
  "$project_root/Tests/Fixtures/tree" > "$tmp_dir/tree.cached.first.json"
"$project_root/.lake/build/bin/skbuild" --json --cache="$tmp_dir/tree.cache.json" \
  "$project_root/Tests/Fixtures/tree" > "$tmp_dir/tree.cached.second.json"
diff -u "$tmp_dir/tree.cached.first.json" "$tmp_dir/tree.cached.second.json"
python3 - "$tmp_dir/tree.cache.json" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as stream:
    cache = json.load(stream)
assert cache["cache_schema"] == 2
assert cache["report"]["schema"] == 1
PY

"$project_root/.lake/build/bin/skbuild" --json \
  "$project_root/Tests/Fixtures/tree" > "$tmp_dir/tree.json"

python3 -m json.tool "$tmp_dir/tree.json" > /dev/null
python3 - "$tmp_dir/tree.json" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as stream:
    report = json.load(stream)

assert report["schema"] == 1
assert report["complete"] is True
assert report["coverage"] == {
    "selected_scope": "recursive-tree",
    "input_coverage": "complete",
    "unsupported_semantics": False,
    "kconfig_validity": "not-checked",
    "build_validation": "not-requested",
    "qualification": "exact-within-modeled-scope",
}
assert [item["path"] for item in report["files"]] == ["child/child.o", "root.o"]
PY

"$project_root/tools/record_baseline.py" \
  --output-dir "$tmp_dir/baseline" "$project_root/Tests/Fixtures/tree"
python3 - "$tmp_dir/baseline" <<'PY'
import json
import sys
from pathlib import Path

root = Path(sys.argv[1])
manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
report = json.loads((root / "report.json").read_text(encoding="utf-8"))
assert manifest["schema"] == 1
assert manifest["revision"]
assert manifest["input_sha256"]
assert manifest["result"]["file_count"] == 2
assert report["complete"] is True
assert (root / "dirty.diff").exists()
assert (root / "stderr.txt").exists()
PY

"$project_root/tools/acquire_source.py" \
  "$project_root/Tests/Fixtures/tree" \
  --output-dir "$tmp_dir/acquired-tree" > "$tmp_dir/acquired-tree.json"
python3 - "$tmp_dir/acquired-tree" <<'PY'
import json
import sys
from pathlib import Path

root = Path(sys.argv[1])
manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
assert manifest["input_kind"] == "local-tree"
assert manifest["source_file_count"] == 2
assert (root / "source/Makefile").exists()
PY

python3 - "$tmp_dir/unsafe.tar" <<'PY'
import io
import sys
import tarfile

with tarfile.open(sys.argv[1], "w") as archive:
    member = tarfile.TarInfo("../escape")
    member.size = 1
    archive.addfile(member, io.BytesIO(b"x"))
PY
set +e
"$project_root/tools/acquire_source.py" "$tmp_dir/unsafe.tar" \
  --output-dir "$tmp_dir/unsafe-output" > /dev/null 2> "$tmp_dir/unsafe.err"
acquire_rc=$?
set -e
test "$acquire_rc" -eq 2
test ! -e "$tmp_dir/unsafe-output"
grep -q "escapes extraction root" "$tmp_dir/unsafe.err"

"$project_root/.lake/build/bin/skbuild" --json \
  "$project_root/tests/busybox/Makfiles_only/busybox_orig" \
  > "$tmp_dir/busybox.json" 2>/dev/null

python3 - "$tmp_dir/busybox.json" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as stream:
    report = json.load(stream)

paths = {item["path"] for item in report["files"]}
assert "applets/applets.o" in paths
assert "archival/gzip.o" in paths
assert len(report["files"]) > 500
assert report["complete"] is False
assert report["coverage"]["qualification"] == "unknown"
assert report["coverage"]["unsupported_semantics"] is True
assert {item["code"] for item in report["diagnostics"]} <= {"SKB1003", "SKB1004"}
PY

set +e
"$project_root/.lake/build/bin/skbuild" --strict --json \
  "$project_root/tests/busybox/Makfiles_only/busybox_orig" \
  > "$tmp_dir/busybox.strict.json" 2>/dev/null
strict_rc=$?
set -e
test "$strict_rc" -eq 1
python3 - "$tmp_dir/busybox.strict.json" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as stream:
    assert json.load(stream)["complete"] is False
PY

"$project_root/.lake/build/bin/skbuild" --tristate --json \
  "$project_root/tests/linux/linux_orig" \
  > "$tmp_dir/linux.json" 2>/dev/null

python3 - "$tmp_dir/linux.json" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as stream:
    report = json.load(stream)

paths = {item["path"] for item in report["files"]}
assert "block/badblocks.o" in paths
assert "drivers/base/core.o" in paths
assert len(report["files"]) > 40000
assert report["complete"] is False
assert report["coverage"]["qualification"] == "unknown"
assert report["coverage"]["selected_scope"] == "recursive-tree"
PY

"$project_root/.lake/build/bin/skbuild" --json \
  --config="$project_root/Tests/Fixtures/tree.config" \
  --build-dir="$project_root/Tests/Fixtures/coverage-build" \
  --src-dir="$project_root/Tests/Fixtures/coverage-src" \
  "$project_root/Tests/Fixtures/tree" > "$tmp_dir/coverage.json" 2>/dev/null

python3 - "$tmp_dir/coverage.json" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as stream:
    report = json.load(stream)

assert report["complete"] is False
codes = [item["code"] for item in report["diagnostics"]]
assert codes.count("SKB4002") == 1
assert codes.count("SKB4003") == 1
PY

find "$project_root/tests" -type f \( -name Makefile -o -name Kbuild \) -print \
  | sort \
  | xargs "$project_root/.lake/build/bin/skbuild" --parse-only > /dev/null

"$project_root/.lake/build/bin/skbuild" --tristate --batch-check --json \
  "$project_root/tests/linux/linux_orig/arch/alpha/lib/Makefile" \
  "$project_root/tests/linux/linux_orig/arch/powerpc/kernel/Makefile" \
  "$project_root/tests/linux/linux_orig/drivers/infiniband/core/Makefile" \
  > "$tmp_dir/batch.jsonl"
test "$(wc -l < "$tmp_dir/batch.jsonl")" -eq 3

python3 - "$tmp_dir/batch.jsonl" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as stream:
    rows = [json.loads(line) for line in stream]

assert all("diagnostic_codes" in row for row in rows)
assert all(row["diagnostics"] == len(row["diagnostic_codes"]) for row in rows)
assert all(row["diagnostics"] == len(row["diagnostic_details"]) for row in rows)
PY

echo "skbuild end-to-end golden tests passed"
