import os

import z3


def descend(directory, variables, guard):
    '''Return [(child directory relative to the source root, guard)].

    Each child's guard is its condition in `variables` conjoined with `guard`.
    '''
    return [(os.path.normpath(os.path.join(directory, word)), z3.simplify(z3.And(guard, condition)))
            for word, condition in variables.get('obj-y', {}).items() if word.endswith('/')]
