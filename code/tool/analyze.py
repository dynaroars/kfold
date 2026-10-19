import os

import z3

from tool import parse, execute, collect, descend, top


def kbuild_file(path, directory):
    '''Locate the build file for a directory: prefers 'Kbuild', falling back to 'Makefile'.'''
    kbuild = os.path.join(path, directory, 'Kbuild')
    return kbuild if os.path.isfile(kbuild) else os.path.join(path, directory, 'Makefile')


def analyze(path, variables, progress=None):
    '''Extract build conditions for all compiled objects across a Kbuild repository.

    Performs a whole-tree worklist traversal over the source directory hierarchy,
    starting from the entry directories declared in the top-level Makefile.

    Parameters:
        path:      root directory of the source tree
        variables: command-line Make variables ({name: string}), e.g., ARCH bindings
        progress:  optional callback for reporting progress (done, left, objects, dir)

    Returns:
        {object_path: build_condition}:
            Mapping from each extracted target object path to its Boolean build condition formula.
    '''
    conditions = {}
    work, state = top.top_dirs(path, variables)
    done = 0
    while work:
        directory, path_condition = work.pop()
        if progress:
            progress(done=done, left=len(work) + 1, objects=len(conditions), dir=directory)
        # Each subdirectory starts from the top-level environment exported by Make,
        # with automatic variables $(obj) and $(src) set to the directory path
        start = dict(state, **execute.from_strings({'obj': directory, 'src': directory}))
        statements = parse.parse(kbuild_file(path, directory))
        local, _ = execute.execute(statements, path, start)
        # Collect target objects and expand composites within the directory
        for obj, condition in collect.collect(directory, local, path_condition).items():
            conditions[obj] = z3.simplify(z3.Or(conditions.get(obj, z3.BoolVal(False)),
                                                condition))
        # Recurse into subdirectories referenced in obj-y
        work.extend(descend.descend(directory, local, path_condition))
        done += 1
        if progress:
            progress(done=done, left=len(work), objects=len(conditions), dir=directory)
    return conditions
