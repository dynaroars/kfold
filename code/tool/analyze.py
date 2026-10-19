import os

import z3

from tool import parse, execute, collect, descend, top


def kbuild_file(path, directory):
    # Kbuild reads a directory's Kbuild file, or its Makefile when there is none
    kbuild = os.path.join(path, directory, 'Kbuild')
    return kbuild if os.path.isfile(kbuild) else os.path.join(path, directory, 'Makefile')


def analyze(path, variables):
    '''Return {object path relative to path: build condition}.

    path       root of the source tree; its top-level Makefile names the first directories
    variables  Make variables the build passes on the command line, {name: string}
    '''
    conditions = {}
    work, state = top.top_dirs(path, variables)
    while work:
        directory, path_condition = work.pop()
        # each directory starts from the top-level state, which Make exports to the
        # sub-make that builds it, with obj and src naming the directory
        start = dict(state, **execute.from_strings({'obj': directory, 'src': directory}))
        statements = parse.parse(kbuild_file(path, directory))
        local, _ = execute.execute(statements, path, start)
        for obj, condition in collect.collect(directory, local, path_condition).items():
            conditions[obj] = z3.simplify(z3.Or(conditions.get(obj, z3.BoolVal(False)),
                                                condition))
        work.extend(descend.descend(directory, local, path_condition))
    return conditions
