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
assert set(by_path) == {
    "first.o", "second.o", "guarded.o", "if.o", "concat.o", "macro.o"
}
assert by_path["guarded.o"]["condition_text"] == "CONFIG_EXTRA=y"
assert by_path["if.o"]["condition_text"] == "CONFIG_EXTRA=y"
assert report["coverage"]["qualification"] == "exact-within-modeled-scope"
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

python3 - "$tmp_dir/safe.tar" "$tmp_dir/unsafe.tar" <<'PY'
import io
import sys
import tarfile

with tarfile.open(sys.argv[1], "w") as archive:
    member = tarfile.TarInfo("linux/Kbuild")
    data = b"obj-y += kernel.o\n"
    member.size = len(data)
    archive.addfile(member, io.BytesIO(data))
with tarfile.open(sys.argv[2], "w") as archive:
    member = tarfile.TarInfo("../escape")
    member.size = 1
    archive.addfile(member, io.BytesIO(b"x"))
PY
safe_sha256=$(sha256sum "$tmp_dir/safe.tar" | awk '{print $1}')
"$project_root/tools/acquire_source.py" "$tmp_dir/safe.tar" \
  --sha256 "$safe_sha256" --output-dir "$tmp_dir/verified-output" > /dev/null
python3 - "$tmp_dir/verified-output/manifest.json" <<'PY'
import json
import sys

manifest = json.load(open(sys.argv[1], encoding="utf-8"))
assert manifest["verification"]["status"] == "verified"
assert manifest["verification"]["method"] == "sha256"
PY
set +e
"$project_root/tools/acquire_source.py" "$tmp_dir/safe.tar" \
  --sha256 "0000000000000000000000000000000000000000000000000000000000000000" \
  --output-dir "$tmp_dir/mismatched-output" > /dev/null 2> "$tmp_dir/mismatch.err"
checksum_rc=$?
set -e
test "$checksum_rc" -eq 2
test ! -e "$tmp_dir/mismatched-output"
grep -q "SHA-256 mismatch" "$tmp_dir/mismatch.err"
set +e
"$project_root/tools/acquire_source.py" "$tmp_dir/unsafe.tar" \
  --output-dir "$tmp_dir/unsafe-output" > /dev/null 2> "$tmp_dir/unsafe.err"
acquire_rc=$?
set -e
test "$acquire_rc" -eq 2
test ! -e "$tmp_dir/unsafe-output"
grep -q "escapes extraction root" "$tmp_dir/unsafe.err"

python3 - "$project_root" <<'PY'
import importlib.util
import json
import sys
from pathlib import Path

module_path = Path(sys.argv[1]) / "tools/acquire_source.py"
spec = importlib.util.spec_from_file_location("acquire_source", module_path)
acquire_source = importlib.util.module_from_spec(spec)
spec.loader.exec_module(acquire_source)
source, resolution = acquire_source.resolve_latest_metadata(json.dumps({
    "latest_stable": {"version": "6.12.9"},
    "releases": [{
        "moniker": "stable",
        "version": "6.12.9",
        "source": "https://cdn.kernel.org/pub/linux/kernel/v6.x/linux-6.12.9.tar.xz",
        "released": {"isodate": "2025-01-01"},
        "pgp": "https://cdn.kernel.org/linux.sign",
    }],
}))
assert source.endswith("linux-6.12.9.tar.xz")
assert resolution["version"] == "6.12.9"
assert resolution["pgp"].endswith("linux.sign")
PY

"$project_root/tools/skbuild_analyze.py" \
  "$project_root/Tests/Fixtures/tree" \
  --output "$tmp_dir/analyze-pipeline" > "$tmp_dir/analyze-pipeline.json"
python3 - "$tmp_dir/analyze-pipeline" <<'PY'
import json
import sys
from pathlib import Path

root = Path(sys.argv[1])
report = json.loads((root / "report.json").read_text(encoding="utf-8"))
run = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
acquisition = json.loads((root / "workspace/manifest.json").read_text(encoding="utf-8"))
assert report["complete"] is True
assert run["analysis_root"] == "workspace/source"
assert acquisition["input_kind"] == "local-tree"
assert (root / "command.json").exists()
assert (root / "acquire.stderr").exists()
assert (root / "analyzer.stderr").exists()
PY

"$project_root/.lake/build/bin/skbuild" analyze \
  "$project_root/Tests/Fixtures/tree" \
  --output="$tmp_dir/native-analyze" > "$tmp_dir/native-analyze.json"
python3 - "$tmp_dir/native-analyze" <<'PY'
import json
import sys
from pathlib import Path

root = Path(sys.argv[1])
report = json.loads((root / "report.json").read_text(encoding="utf-8"))
assert report["complete"] is True
assert json.loads((root / "manifest.json").read_text(encoding="utf-8"))["complete"] is True
PY

"$project_root/.lake/build/bin/skbuild" resume \
  "$tmp_dir/native-analyze" > "$tmp_dir/resumed.json"
python3 - "$tmp_dir/native-analyze" "$tmp_dir/resumed.json" <<'PY'
import json
import sys
from pathlib import Path

root = Path(sys.argv[1])
resumed = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
original = json.loads((root / "report.json").read_text(encoding="utf-8"))
manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
assert resumed == original
assert manifest["last_resume"]["status"] == "success"
PY

"$project_root/.lake/build/bin/skbuild" query \
  "$tmp_dir/native-analyze" --file=child/child.o > "$tmp_dir/query-file.json"
"$project_root/.lake/build/bin/skbuild" query \
  "$tmp_dir/native-analyze" --option=CONFIG_CHILD > "$tmp_dir/query-option.json"
python3 - "$tmp_dir/query-file.json" "$tmp_dir/query-option.json" <<'PY'
import json
import sys

file_rows = json.load(open(sys.argv[1], encoding="utf-8"))
option_rows = json.load(open(sys.argv[2], encoding="utf-8"))
assert len(file_rows) == 1 and file_rows[0]["path"] == "child/child.o"
assert any(row["path"] == "child/child.o" for row in option_rows)
PY

python3 - "$tmp_dir/http-workspace" "$project_root" <<'PY'
import io
import importlib.util
import sys
import tarfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

module_path = Path(sys.argv[2]) / "tools/acquire_source.py"
spec = importlib.util.spec_from_file_location("acquire_source", module_path)
acquire_source = importlib.util.module_from_spec(spec)
spec.loader.exec_module(acquire_source)

archive = io.BytesIO()
with tarfile.open(fileobj=archive, mode="w") as stream:
    member = tarfile.TarInfo("linux/Kbuild")
    data = b"obj-y += kernel.o\n"
    member.size = len(data)
    stream.addfile(member, io.BytesIO(data))
payload = archive.getvalue()

class Handler(BaseHTTPRequestHandler):
    requests = 0

    def do_GET(self):
        Handler.requests += 1
        start = int(self.headers.get("Range", "bytes=0-").split("=")[1].split("-")[0])
        if Handler.requests == 1:
            self.send_response(200)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload[: len(payload) // 2])
            self.wfile.flush()
            self.connection.close()
            return
        self.send_response(206)
        self.send_header("Content-Length", str(len(payload) - start))
        self.send_header("Content-Range", f"bytes {start}-{len(payload)-1}/{len(payload)}")
        self.end_headers()
        self.wfile.write(payload[start:])

    def log_message(self, *_):
        pass

server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
thread = threading.Thread(target=server.serve_forever, daemon=True)
thread.start()
try:
    url = f"http://127.0.0.1:{server.server_port}/linux.tar"
    output = Path(sys.argv[1])
    cache = output.parent / "source-cache"
    try:
        acquire_source.acquire(
            url,
            output,
            {"max_files": 100, "max_expanded_bytes": 10000, "max_download_bytes": 100000},
            1,
            cache,
        )
    except acquire_source.AcquireError:
        pass
    assert list(cache.glob("*.part"))
    manifest = acquire_source.acquire(
        url,
        output,
        {"max_files": 100, "max_expanded_bytes": 10000, "max_download_bytes": 100000},
        3,
        cache,
    )
    assert Handler.requests >= 2
    assert manifest["input_kind"] == "https-archive"
    assert manifest["archive_format"] == "tar"
    assert (output / "source/linux/Kbuild").exists()
finally:
    server.shutdown()
    thread.join()
PY

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
