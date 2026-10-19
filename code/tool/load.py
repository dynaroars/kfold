import z3


def load(path):
    '''Read {object path: build condition} from a file written by save.'''
    return {assertion.arg(0).decl().name(): assertion.arg(1)
            for assertion in z3.parse_smt2_file(path)}
