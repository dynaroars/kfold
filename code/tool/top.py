import os

import z3

from tool import parse, execute

# The canned Kbuild recipe pattern that descends into a subdirectory:
# $(MAKE) $(build)=<directory>
DESCENT = '$(build)=$@'


def top_dirs(path, variables):
    '''Extract entry subdirectories and initial symbolic state from the top-level Makefile.

    Parameters:
        path:      root directory of the source repository
        variables: command-line variable overrides passed to Make (e.g., {'ARCH': 'x86'})

    Returns:
        ([(directory, path condition)], state):
            directory:      relative path of entry subdirectory
            path condition: Boolean condition under which Kbuild descends into directory
            state:          initial top-level symbol table exported to sub-makes
    '''
    state, rules = execute.execute(parse.parse(os.path.join(path, 'Makefile')), path,
                                   execute.from_strings(variables))
    dirs = {}
    for targets, path_condition, recipe in rules:
        if any(DESCENT in line for line in recipe):
            for directory, condition in execute.to_words(targets).items():
                dirs[directory] = z3.simplify(z3.Or(dirs.get(directory, z3.BoolVal(False)),
                                                    z3.And(path_condition, condition)))
    return list(dirs.items()), state
