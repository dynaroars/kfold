import os

import z3

from tool import parse, execute, collect, descend, top


def kbuild_file(path, directory):
    '''Locate the build file for a directory: prefers 'Kbuild', then Xen's 'build.mk',
    falling back to 'Makefile'.'''
    for name in ['Kbuild', 'build.mk']:
        file = os.path.join(path, directory, name)
        if os.path.isfile(file):
            return file
    return os.path.join(path, directory, 'Makefile')


def analyze(path, variables, progress=None):
    '''Extract build conditions for all compiled objects across a Kbuild repository.

    Performs a whole-tree worklist traversal over the source directory hierarchy,
    starting from the sub-makes that the top-level Makefile runs for its default goal.

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
    # (directory, makefile, goals) -> path condition it was analyzed under; one reached
    # again is analyzed again when its new path condition holds in other configurations.
    # top_dirs has analyzed the top-level Makefile
    analyzed = {('.', 'Makefile', ()): execute.TRUE}
    done = 0
    while work:
        directory, makefile, goals, assignments, path_condition = work.pop()
        if progress:
            progress(done=done, left=len(work) + 1, objects=len(conditions), dir=directory)
        key = (directory, makefile, goals)
        file = os.path.join(path, makefile) if makefile else kbuild_file(path, directory)
        # directories without a Makefile, such as $(dtstree) on x86, have nothing to build
        if os.path.isfile(file) and not (key in analyzed and execute.implied(path_condition, analyzed[key])):
            analyzed[key] = z3.simplify(z3.Or(analyzed.get(key, execute.FALSE), path_condition))
            # each subdirectory starts from the top-level environment exported by Make,
            # with automatic variables $(obj) and $(src) set to the directory path
            # and the variables the sub-make line sets, which its Makefile cannot overwrite;
            # the key leaves them out, so Linux's need-builtin=1 and need-builtin= on the
            # same path condition analyze a directory once
            start = dict(state)
            if makefile is None:
                start.update(execute.from_strings({'obj': directory, 'src': directory}))
            start.update(execute.from_strings(dict(assignments)))
            local, rules = execute.execute(parse.parse(file), path, start,
                                           [*variables, *(name for name, _ in assignments)])
            # Make builds the goals, or else the default goal: for a directory, the files
            # Kbuild lists; for a standalone Makefile, its first target
            if goals:
                sub_goals = dict.fromkeys(goals, execute.TRUE)
            elif makefile is None:
                sub_goals = collect.goals(directory, local)
            else:
                sub_goals = {descend.default_goal(rules): execute.TRUE}
            reach = descend.reachable(rules, sub_goals)
            # collect target objects and expand composites within the directory, plus the
            # other objects its rules build for the goals
            objects = collect.collect(directory, local, path_condition)
            for target, condition in reach.items():
                if target.endswith('.o'):
                    objects[target] = z3.Or(objects.get(target, execute.FALSE),
                                            z3.And(path_condition, condition))
            for obj, condition in objects.items():
                conditions[obj] = z3.simplify(z3.Or(conditions.get(obj, execute.FALSE), condition))
            # recurse into subdirectories referenced in obj-y and the sub-makes of the recipes
            work.extend(descend.descend(directory, local, path_condition))
            work.extend(descend.submakes(path, local, rules, reach, path_condition))
        done += 1
        if progress:
            progress(done=done, left=len(work), objects=len(conditions), dir=directory)
    return conditions
