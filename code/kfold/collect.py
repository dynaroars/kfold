def collect(directory, variables, guard):
    '''Return {object path relative to the source root: condition}.

    Each condition is conjoined with `guard`, the condition under which the
    build enters `directory`.
    '''
    raise NotImplementedError
