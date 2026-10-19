import subprocess
import pickle

import z3

from tool.top import top_dirs


def analyze(path):
    '''Return {object path relative to path: build condition} computed by Kmax's kmaxall.'''
    # kmaxall starts from the same top-level directories as the tool and prints a
    # pickled {path: SMT-LIB condition} to stdout
    dirs = [directory + '/' for directory, _ in top_dirs(path)]
    result = subprocess.run(['kmaxall', *dirs], cwd=path, capture_output=True, check=True)
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
