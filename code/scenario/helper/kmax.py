import subprocess
import tempfile
import shutil
import pickle
import sys
import os

import z3

from tool.top import top_dirs

# kmaxall 4.10 writes a child's stderr bytes with sys.stderr.write, which raises
# TypeError under Python 3 when any directory fails and aborts the whole run
BUGGY = 'sys.stderr.write(err)\n'
FIXED = "sys.stderr.write(err.decode(errors='replace'))\n"


def analyze(path, variables, arguments):
    '''Return {object path relative to path: build condition} computed by Kmax's kmaxall.

    arguments  kmaxall's arguments; None starts it from the tool's top-level directories
    '''
    if arguments is None:
        arguments = [directory + '/' for directory, _ in top_dirs(path, variables)[0]]
    with open(shutil.which('kmaxall')) as f:
        source = f.read()
    assert source.count(BUGGY) == 1, 'unexpected kmaxall version'
    with tempfile.NamedTemporaryFile('w', suffix='_kmaxall.py') as patched:
        patched.write(source.replace(BUGGY, FIXED))
        patched.flush()
        # kmaxall prints a pickled {path: SMT-LIB condition} to stdout and its progress
        # to stderr; PYTHONOPTIMIZE keeps the kmax process per directory out of debug mode
        result = subprocess.run([sys.executable, '-O', patched.name, *arguments], cwd=path,
                                stdout=subprocess.PIPE, env=dict(os.environ, PYTHONOPTIMIZE='1'))
    raw = {name: z3.And(*z3.parse_smt2_string(smt))
           for name, smt in pickle.loads(result.stdout).items()}
    # kmaxall conditions are local to each Makefile; an object also needs the
    # conditions of the directory entries above it
    conditions = {}
    for name, condition in raw.items():
        if not name.endswith('.o') or '$(' in name:
            continue
        parts = name.split('/')[:-1]
        ancestors = ['/'.join(parts[:i]) + '/' for i in range(1, len(parts) + 1)]
        conditions[name] = z3.simplify(z3.And(condition, *[raw[d] for d in ancestors if d in raw]))
    return conditions
