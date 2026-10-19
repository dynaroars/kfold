import z3


def save(conditions, path):
    '''Write {object path: build condition} to `path` in SMT-LIB 2.

    Each object is a Boolean named by its path, with one assertion per object:
    (assert (= archival/tar.o CONFIG_TAR))
    '''
    solver = z3.Solver()
    for obj, condition in conditions.items():
        solver.add(z3.Bool(obj) == condition)
    with open(path, 'w') as f:
        f.write(solver.sexpr())
