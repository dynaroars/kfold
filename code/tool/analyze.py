import os

import z3

from tool import parse, execute, collect, descend, top


def analyze(path):
    '''Return {object path relative to path: build condition}.

    path  root of the source tree; its top-level Makefile names the first directories
    '''
    conditions = {}
    work = top.top_dirs(path)
    while work:
        directory, guard = work.pop()
        variables, _ = execute.execute(parse.parse(os.path.join(path, directory, 'Kbuild')))
        for obj, condition in collect.collect(directory, variables, guard).items():
            conditions[obj] = z3.simplify(z3.Or(conditions.get(obj, z3.BoolVal(False)),
                                                condition))
        work.extend(descend.descend(directory, variables, guard))
    return conditions
