def descend(directory, variables, guard):
    '''Return [(child directory relative to the source root, guard)].

    Each child's guard is its condition in `variables` conjoined with `guard`.
    '''
    raise NotImplementedError
