import os

import z3


def descend(directory, variables, path_condition):
    '''Return [(child directory relative to the source root, path condition)].

    Each child's path condition is its condition in `variables` conjoined with `path_condition`.
    '''
    return [(os.path.normpath(os.path.join(directory, word)),
             z3.simplify(z3.And(path_condition, condition)))
            for word, condition in variables.get('obj-y', {}).items() if word.endswith('/')]
