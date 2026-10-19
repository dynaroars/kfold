import os

import z3

from tool import parse, execute

# the Kbuild recipe that enters a directory: $(MAKE) $(build)=<directory>
DESCENT = '$(build)=$@'


def top_dirs(path, variables):
    '''Return ([(directory, path condition)], top-level state) of the Makefile at `path`.

    variables  Make variables the build passes on the command line, {name: string}
    The directories are the targets of the rules whose recipe runs $(MAKE) $(build)=$@.
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
