"""kfold web interface: explore Linux object conditions and analyze Makefiles.

Run:  python3 web/server.py            (development, http://127.0.0.1:8090)
      gunicorn -w 2 -b 0.0.0.0:8090 web.server:app

Data: web/data/linux-v6.6.json.gz, built by tools/build_web_data.py.
"""
import gzip
import json
import logging
import os
import subprocess
import sys
import time
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("kfold-web")

WEB = Path(__file__).resolve().parent
DATA = WEB / "data" / "linux-v6.6.json.gz"
EXAMPLES = WEB / "examples"
MAX_MAKEFILE = 64 * 1024
MAX_CONFIG = 2 * 1024 * 1024
MAKEFILE_TIMEOUT = 20

app = Flask(__name__, static_folder=None)


class LinuxData:
    """Object conditions for one Linux tree, evaluated in pure Python over
    the shared node table of tools/build_web_data.py."""

    def __init__(self, path):
        t0 = time.monotonic()
        with gzip.open(path, "rt") as f:
            d = json.load(f)
        self.meta = {k: d[k] for k in ("tree", "commit", "analysis_seconds", "makefile_instances")}
        self.nodes = d["nodes"]
        self.objects = d["objects"]
        self.profiles = d["profiles"]
        self.paths = sorted(self.objects)
        self.kind_counts = {}
        for o in self.objects.values():
            self.kind_counts[o["kind"]] = self.kind_counts.get(o["kind"], 0) + 1
        log.info("loaded %d objects in %.1fs", len(self.paths), time.monotonic() - t0)

    @staticmethod
    def values(config):
        """Option values as kfold sees them: y, m, or undef."""
        return {k: v for k, v in config.items() if v in ("y", "m")}

    def truth(self, root, values, memo):
        stack = [(root, False)]
        nodes = self.nodes
        while stack:
            i, expanded = stack.pop()
            if i in memo:
                continue
            n = nodes[i]
            op = n[0]
            if op == "t" or op == "f":
                memo[i] = op == "t"
            elif op == "eq":
                memo[i] = values.get(n[1], "undef") == n[2]
            elif not expanded:
                stack.append((i, True))
                stack.extend((c, False) for c in n[1:] if c not in memo)
            else:
                v = [memo[c] for c in n[1:]]
                memo[i] = (not v[0]) if op == "not" else (all(v) if op == "and" else any(v))
        return memo[root]

    def options_of(self, root):
        seen, out, stack = set(), set(), [root]
        while stack:
            i = stack.pop()
            if i in seen:
                continue
            seen.add(i)
            n = self.nodes[i]
            if n[0] == "eq":
                out.add(n[1])
            elif n[0] in ("not", "and", "or"):
                stack.extend(n[1:])
        return sorted(out)


def parse_config(text):
    values = {}
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("CONFIG_") and "=" in line:
            k, v = line.split("=", 1)
            values[k.strip()] = v.strip().strip('"')
    return values


linux = LinuxData(DATA) if DATA.exists() else None


def config_from_request(data):
    if data.get("profile"):
        if data["profile"] not in linux.profiles:
            return None, "unknown profile"
        return linux.profiles[data["profile"]], None
    text = data.get("config", "")
    if len(text) > MAX_CONFIG:
        return None, "configuration too large"
    if not text.strip():
        return None, "no configuration given"
    return parse_config(text), None


@app.route("/api/health")
def health():
    return jsonify({"status": "ok", "linux": linux.meta if linux else None})


@app.route("/api/linux/info")
def linux_info():
    if not linux:
        return jsonify({"error": "Linux data not built; run tools/build_web_data.py"}), 503
    return jsonify({**linux.meta, "objects": len(linux.paths), "kinds": linux.kind_counts,
                    "profiles": list(linux.profiles)})


@app.route("/api/linux/search")
def linux_search():
    q = request.args.get("q", "").strip()
    if not linux or len(q) < 2:
        return jsonify({"matches": []})
    ql = q.lower()
    starts = [p for p in linux.paths if p.lower().startswith(ql)]
    contains = [p for p in linux.paths if ql in p.lower() and not p.lower().startswith(ql)]
    matches = (starts + contains)[:50]
    return jsonify({"matches": matches, "total": len(starts) + len(contains)})


@app.route("/api/linux/object")
def linux_object():
    path = request.args.get("path", "")
    if not linux or path not in linux.objects:
        return jsonify({"error": f"unknown object: {path}"}), 404
    o = linux.objects[path]
    result = {"path": path, "kind": o["kind"], "condition": o["text"],
              "origins": o["origins"], "options": linux.options_of(o["root"])}
    result["profiles"] = {name: linux.truth(o["root"], LinuxData.values(cfg), {})
                          for name, cfg in linux.profiles.items()}
    return jsonify(result)


@app.route("/api/linux/evaluate", methods=["POST"])
def linux_evaluate():
    if not linux:
        return jsonify({"error": "Linux data not built"}), 503
    data = request.get_json() or {}
    config, err = config_from_request(data)
    if err:
        return jsonify({"error": err}), 400
    values = LinuxData.values(config)
    memo = {}
    path = data.get("path")
    if path:
        if path not in linux.objects:
            return jsonify({"error": f"unknown object: {path}"}), 404
        o = linux.objects[path]
        opts = linux.options_of(o["root"])
        return jsonify({"path": path, "built": linux.truth(o["root"], values, memo),
                        "values": {k: values.get(k, "not set") for k in opts}})
    built = [p for p in linux.paths if linux.truth(linux.objects[p]["root"], values, memo)]
    prefix = data.get("prefix", "")
    shown = [p for p in built if p.startswith(prefix)] if prefix else built
    by_top = {}
    for p in built:
        top = p.split("/")[0] if "/" in p else "(top level)"
        by_top[top] = by_top.get(top, 0) + 1
    return jsonify({"built": len(built), "of": len(linux.paths),
                    "by_directory": dict(sorted(by_top.items(), key=lambda kv: -kv[1])),
                    "objects": shown})


@app.route("/api/makefile", methods=["POST"])
def analyze_makefile():
    data = request.get_json() or {}
    text = data.get("makefile", "")
    if not text.strip():
        return jsonify({"error": "empty Makefile"}), 400
    if len(text) > MAX_MAKEFILE or len(data.get("config", "")) > MAX_CONFIG:
        return jsonify({"error": "input too large"}), 400
    req = {"makefile": text, "tristate": bool(data.get("tristate", True)),
           "config": data.get("config", "")}
    t0 = time.monotonic()
    try:
        r = subprocess.run([sys.executable, str(WEB / "run_makefile.py")],
                           input=json.dumps(req), capture_output=True, text=True,
                           timeout=MAKEFILE_TIMEOUT, env={**os.environ, "KFOLD_SANDBOX": "1"})
    except subprocess.TimeoutExpired:
        return jsonify({"error": f"analysis exceeded {MAKEFILE_TIMEOUT}s"}), 408
    if r.returncode != 0:
        tail = r.stderr.strip().splitlines()[-1:] or ["unknown error"]
        return jsonify({"error": "kfold failed: " + tail[0]}), 422
    out = json.loads(r.stdout)
    out["seconds"] = round(time.monotonic() - t0, 2)
    return jsonify(out)


@app.route("/api/examples")
def examples():
    items = []
    for p in sorted(EXAMPLES.glob("*.mk")):
        lines = p.read_text().splitlines()
        desc = lines[0].lstrip("# ").strip() if lines and lines[0].startswith("#") else p.stem
        items.append({"id": p.stem, "description": desc})
    return jsonify(items)


@app.route("/api/example/<name>")
def example(name):
    p = EXAMPLES / f"{name}.mk"
    if not p.is_file() or p.parent != EXAMPLES:
        return jsonify({"error": "unknown example"}), 404
    return jsonify({"id": name, "makefile": p.read_text()})


@app.route("/")
@app.route("/index.html")
def index():
    return send_from_directory(WEB, "index.html")


if __name__ == "__main__":
    app.run(host=os.environ.get("HOST", "127.0.0.1"), port=int(os.environ.get("PORT", 8090)))
