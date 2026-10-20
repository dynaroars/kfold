import subprocess
import tempfile
import shutil
import pickle
import sys
import os

import z3

from tool.top import top_dirs

# the patches applied to a copy of kmaxall 4.10, as (original line, replacement)
PATCHES = [
    # kmaxall writes a child's stderr bytes with sys.stderr.write, which raises
    # TypeError under Python 3 when any directory fails and aborts the whole run
    ('sys.stderr.write(err)\n', "sys.stderr.write(err.decode(errors='replace'))\n"),
    # after each directory, report directories done (loop iterations) and left (the
    # pending set) and the units found, read by analyze() for the progress bar
    ('    pending_subdirectories.update(covering_set(pending_subdirectories.pop()))\n',
     '    pending_subdirectories.update(covering_set(pending_subdirectories.pop()))\n'
     '    covering_set.done = getattr(covering_set, "done", 0) + 1\n'
     "    sys.stderr.write('PROGRESS %d %d %d\\n' % (covering_set.done,"
     ' len(pending_subdirectories), len(z3_pcs)))\n'),
]


def _patched_kmaxall():
    with open(shutil.which('kmaxall')) as f:
        source = f.read()
    for old, new in PATCHES:
        assert source.count(old) == 1, 'unexpected kmaxall version'
        source = source.replace(old, new)
    return source


def analyze(path, variables, arguments, progress=None, log=None):
    '''Return {object path relative to path: build condition} computed by Kmax's kmaxall.

    arguments  kmaxall's arguments; None starts it from the tool's top-level directories
    progress   called after each directory with done, left, and units (found so far)
    log        file that receives kmaxall's messages, one per line
    '''
    if arguments is None:
        # the directories the tool enters first; a directory reached twice is listed once
        arguments = list(dict.fromkeys(directory + '/' for directory, makefile, _, _, _
                                       in top_dirs(path, variables)[0] if makefile is None))
    with tempfile.NamedTemporaryFile('w', suffix='_kmaxall.py') as script, \
            tempfile.TemporaryFile() as out:
        script.write(_patched_kmaxall())
        script.flush()
        # kmaxall writes a pickled {path: SMT-LIB condition} to stdout (here a file, so a
        # full pipe cannot block it) and a line per directory to stderr; PYTHONOPTIMIZE
        # keeps the kmax process it starts per directory out of debug mode
        process = subprocess.Popen([sys.executable, '-O', script.name, *arguments], cwd=path,
                                   stdout=out, stderr=subprocess.PIPE, text=True,
                                   env=dict(os.environ, PYTHONOPTIMIZE='1'))
        # the messages go to the log so they do not break the progress bar; the
        # most common is '<dir>/$(subdir-y)/ does not exist', a directory name that
        # kmax leaves unexpanded and kmaxall then cannot find
        messages = {'unexpanded': 0, 'missing': 0, 'error': 0}
        for line in process.stderr:
            if line.startswith('PROGRESS '):
                done, left, units = map(int, line.split()[1:])
                if progress:
                    progress(done=done, left=left, units=units)
                continue
            if log and not line.startswith(('kmax ', 'running covering_set')):
                log.write(line)
            if line.endswith('does not exist\n'):
                messages['unexpanded' if '$(' in line else 'missing'] += 1
            elif line.startswith('ERROR(kmax)'):
                messages['error'] += 1
        process.wait()
        # the counts close the log
        if log:
            log.write(f'[kmax] directories skipped: {messages["unexpanded"]} unexpanded names, '
                      f'{messages["missing"]} missing; {messages["error"]} directories kmax '
                      f'could not analyze\n')
        out.seek(0)
        raw = {name: z3.And(*z3.parse_smt2_string(smt)) for name, smt in pickle.load(out).items()}
    # kmaxall conditions are local to each Makefile; an object also needs the
    # conditions of the directory entries above it
    conditions = {}
    for name, condition in raw.items():
        if not name.endswith('.o') or '$(' in name:
            continue
        parts = name.split('/')[:-1]
        ancestors = ['/'.join(parts[:i]) + '/' for i in range(1, len(parts) + 1)]
        condition = z3.And(condition, *[raw[d] for d in ancestors if d in raw])
        # the entry directory . names its objects ./<path>, and another entry directory
        # can reach the same object as <path>
        obj = os.path.normpath(name)
        conditions[obj] = z3.simplify(z3.Or(conditions.get(obj, z3.BoolVal(False)), condition))
    return conditions
