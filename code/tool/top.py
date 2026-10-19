import os

import z3

from tool import parse, execute

# the Kbuild recipe that enters a directory: $(MAKE) $(build)=<directory>
DESCENT = '$(build)=$@'


def top_dirs(path):
    '''Return [(directory, guard)] the top-level Makefile at `path` enters.

    They are the targets of the rules whose recipe runs $(MAKE) $(build)=$@.
    '''
    variables, rules = execute.execute(parse.parse(os.path.join(path, 'Makefile')))
    dirs = {}
    for targets, guard, recipe in rules:
        if any(DESCENT in line for line in recipe):
            for directory, condition in execute.to_words(targets).items():
                dirs[directory] = z3.simplify(z3.Or(dirs.get(directory, z3.BoolVal(False)),
                                                    z3.And(guard, condition)))
    return list(dirs.items())
