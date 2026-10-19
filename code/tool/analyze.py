import os

import z3

from tool import parse, execute, collect, descend


def analyze(src, top_dirs):
    '''Return {object path relative to src: build condition}.

    src       root of the source tree
    top_dirs  directories the top-level Makefile enters unconditionally
    '''
    conditions = {}
    work = [(directory, z3.BoolVal(True)) for directory in top_dirs]
    while work:
        directory, guard = work.pop()
        statements = parse.parse(os.path.join(src, directory, 'Kbuild'))
        variables = execute.execute(statements)
        for path, condition in collect.collect(directory, variables, guard).items():
            conditions[path] = z3.simplify(z3.Or(conditions.get(path, z3.BoolVal(False)),
                                                 condition))
        work.extend(descend.descend(directory, variables, guard))
    return conditions
