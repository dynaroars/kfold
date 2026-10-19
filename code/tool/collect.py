import os

import z3

# variables listing the objects a Kbuild directory builds
TARGET_LISTS = ('obj-y', 'lib-y')


def collect(directory, variables, guard):
    '''Return {object path relative to the source root: condition}.

    Each condition is conjoined with `guard`, the condition under which the
    build enters `directory`.
    '''
    objects = {}
    for name in TARGET_LISTS:
        for word, condition in variables.get(name, {}).items():
            if word.endswith('.o'):
                obj = os.path.normpath(os.path.join(directory, word))
                objects[obj] = z3.simplify(z3.Or(objects.get(obj, z3.BoolVal(False)),
                                                 z3.And(guard, condition)))
    return objects
