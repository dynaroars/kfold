from z3 import z3util
import z3


def read_config(path):
    '''Return the options set to y in the .config at `path`.'''
    with open(path) as f:
        return {line.split('=')[0] for line in f if line.rstrip().endswith('=y')}


def evaluate(conditions, on):
    '''Return the objects whose build condition holds when exactly the options in `on` are set.'''
    # a .config is a model: every option in the conditions is true or false
    options = {v for condition in conditions.values() for v in z3util.get_vars(condition)}
    solver = z3.Solver()
    solver.add([v if str(v) in on else z3.Not(v) for v in options])
    solver.check()
    model = solver.model()
    return {obj for obj, condition in conditions.items() if z3.is_true(model.eval(condition))}
