import os

import z3

from tool import execute, collect, parse, top
from pymake3 import parserdata

# the path-forking baseline of RQ2: the statements of the tool's executor, with a copy
# of the state per feasible branch of every conditional in place of merging the branches,
# as in the path-forking symbolic execution of Kbuild Makefiles (Nguyen and Nguyen, 2020)


class Forking(execute.Executor):

    def fork(self, statements, path_condition):
        '''Execute statements, forking at each conditional, and return the final
        (variables, path condition) of every path.'''
        for i, statement in enumerate(statements):
            if not isinstance(statement, parserdata.ConditionBlock):
                self.run([statement], path_condition)
                continue
            rest = list(statements[i + 1:])
            paths = []
            taken = execute.FALSE
            # each branch, and the path past the block where no branch holds
            groups = [(self.condition(condition), list(body)) for condition, body in statement._groups]
            for holds, body in groups + [(execute.TRUE, [])]:
                branch = z3.simplify(z3.And(path_condition, holds, z3.Not(taken)))
                taken = z3.Or(taken, holds)
                if execute.implied(branch, execute.FALSE):
                    continue
                child = Forking(self.root, {}, self.command_line)
                child.variables = {name: dict(words) for name, words in self.variables.items()}
                paths += child.fork(body + rest, branch)
            return paths
        return [(self.variables, path_condition)]


def analyze(path, variables):
    '''Return ({object path: build condition}, number of paths) of a source tree whose
    top-level Makefile descends into directories without subdirectories, such as the
    synthetic trees of RQ2.'''
    conditions = {}
    paths = 0
    work, state = top.top_dirs(path, variables)
    for directory, _, _, _, path_condition in work:
        start = dict(state)
        start.update(execute.from_strings({'obj': directory, 'src': directory}))
        executor = Forking(path, start, variables)
        for local, condition in executor.fork(parse.parse(os.path.join(path, directory, 'Makefile')),
                                              path_condition):
            paths += 1
            for obj, obj_condition in collect.collect(directory, local, condition).items():
                conditions[obj] = z3.Or(conditions.get(obj, execute.FALSE), obj_condition)
    return {obj: z3.simplify(condition) for obj, condition in conditions.items()}, paths
