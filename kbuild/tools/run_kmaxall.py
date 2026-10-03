#!/usr/bin/env python3
"""Run Kmax's kmaxall with two workarounds that leave its analysis unchanged.

1. kmaxall 4.10 passes a subprocess's bytes to sys.stderr.write when a
   subdirectory fails, which raises TypeError under Python 3 and aborts the
   whole run. We run a copy of kmaxall with that one call decoding the bytes.
2. kmaxall spawns one `kmax` process per directory; PYTHONOPTIMIZE=1 keeps
   those children out of Kmax's debug mode, as `python3 -O` does for the parent.

Usage (from the source tree): run_kmaxall.py OUT.pickle META.json ARGS...
"""
import json
import os
import pathlib
import resource
import subprocess
import sys
import tempfile
import time

BUGGY = "sys.stderr.write(err)\n"
FIXED = "sys.stderr.write(err.decode(errors='replace'))\n"


def main():
    out_path, meta_path, args = sys.argv[1], sys.argv[2], sys.argv[3:]
    src = pathlib.Path("~/.local/bin/kmaxall").expanduser().read_text()
    assert src.count(BUGGY) == 1, "unexpected kmaxall version"
    with tempfile.NamedTemporaryFile("w", suffix="_kmaxall.py", delete=False) as f:
        f.write(src.replace(BUGGY, FIXED))
        patched = f.name
    env = dict(os.environ, PYTHONOPTIMIZE="1")
    t0 = time.monotonic()
    with open(out_path, "wb") as out:
        rc = subprocess.run([sys.executable, "-O", patched] + args,
                            stdout=out, env=env).returncode
    elapsed = time.monotonic() - t0
    os.unlink(patched)
    json.dump({"rc": rc, "args": args, "time_s": round(elapsed, 1),
               "maxrss_mb": round(resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss / 1024, 1)},
              open(meta_path, "w"), indent=1)
    sys.exit(rc)


if __name__ == "__main__":
    main()
