import os

from tool import parse, execute, descend


def top_dirs(path, variables):
    '''Extract entry subdirectories and initial symbolic state from the top-level Makefile.

    Parameters:
        path:      root directory of the source repository
        variables: command-line variable overrides passed to Make (e.g., {'ARCH': 'x86'})

    Returns:
        ([(directory, makefile, goals, path condition)], state):
            entries:        the sub-makes that the top-level recipes run for the default
                            goal, as descend.submakes() returns them
            state:          initial top-level symbol table exported to sub-makes
    '''
    state, rules = execute.execute(parse.parse(os.path.join(path, 'Makefile')), path,
                                   execute.from_strings(variables))
    reach = descend.reachable(rules, {descend.default_goal(rules): execute.TRUE})
    return descend.submakes(path, state, rules, reach, execute.TRUE), state
