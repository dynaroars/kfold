# kfold web interface

A small Flask app for Linux developers and users to explore kfold's results:

1. **Explore Linux v6.6** — search any object path and see the Kbuild condition under
   which it is built, which Makefile and variable (or rule) select it, and whether it
   is built under `tinyconfig`, `defconfig`, a Debian configuration, `allmodconfig`, or
   a pasted `.config`. Deep links work: `/?path=fs/ext2/xattr.o`.
2. **What does a configuration build?** — list every object a configuration builds,
   grouped by top-level directory, with a download.
3. **Try your own Makefile** — paste a Kbuild Makefile and see its guarded variables
   and object conditions, optionally evaluated under an assignment.

## Run

```bash
cd web
python3 -m venv --system-site-packages .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python server.py                 # http://127.0.0.1:8090
# or: .venv/bin/gunicorn -w 2 -b 0.0.0.0:8090 server:app
```

`HOST` and `PORT` override the listening address.

## Data

The Linux explorer serves `data/linux-v6.6.json.gz`, which
`tools/build_web_data.py` builds from `results/workspaces/linux` (about 35 s of
analysis). It stores each object's kind, origins, and a readable condition, plus all
conditions as one hash-consed node table, so the server evaluates any configuration
in pure Python without Z3 or the kernel tree. On the four evaluated profiles the
server's predictions equal kfold's own (489, 2,874, 15,419, and 25,950 objects).

## Safety

Submitted Makefiles run in a separate process (`run_makefile.py`) with a 20 s timeout
and `KFOLD_SANDBOX=1`: `$(shell ...)` expands to nothing, and `include` cannot read
files outside the submitted Makefile's temporary directory. Inputs are limited to
64 KB (Makefile) and 2 MB (configuration).
