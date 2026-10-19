import os

import z3

from tool import execute


def descend(directory, variables, path_condition):
    '''Find subdirectory descent targets declared in obj-y.

    In Kbuild, appending a directory path (ending in '/') to obj-y instructs Make
    to recurse into that subdirectory's Makefile.

    Parameters:
        directory:      path of the current directory relative to the repository root
        variables:      symbolic variable table produced after executing the directory Makefile
        path_condition: incoming path condition reaching the current directory

    Returns:
        [(child_directory, None, (), child_path_condition)]:
            child_directory:      normalized relative path to child subdirectory
            None, ():             the child's own Kbuild file, built for its default goal
            child_path_condition: conjunction of directory reaching condition and obj-y condition
    '''
    return [(os.path.normpath(os.path.join(directory, word)), None, (),
             z3.simplify(z3.And(path_condition, condition)))
            for word, condition in variables.get('obj-y', {}).items() if word.endswith('/')]


def default_goal(rules):
    '''Return the first target of the first rule, which make builds when given no goal.'''
    for targets, _, _, _ in rules:
        for target in execute.to_words(targets):
            if not target.startswith('.') and '%' not in target:
                return target
    return None


def reachable(rules, goals):
    '''Find the targets make builds for `goals` by following rule prerequisites.

    Parameters:
        rules: recorded Make rules, as execute() returns them
        goals: {target: path condition} that make is asked to build

    Returns:
        {target: path condition}:
            each target the goals reach, with the condition under which a goal needs it.
            A pattern rule applies to every target its pattern matches, with the stem in
            place of % in its prerequisites, and at most once in a chain, as in Make;
            `%: %_shipped` would otherwise grow targets forever.
    '''
    explicit, patterns = {}, []
    for targets, prerequisites, rule_condition, _ in rules:
        words = execute.to_words(prerequisites)
        for target, target_condition in execute.to_words(targets).items():
            entry = (words, z3.And(rule_condition, target_condition))
            if '%' in target:
                patterns.append((os.path.normpath(target), entry))
            else:
                explicit.setdefault(os.path.normpath(target), []).append(entry)
    reach = {}
    # (target, condition, pattern rules used in the chain that reached it)
    work = [(os.path.normpath(goal), condition, frozenset()) for goal, condition in goals.items()]
    while work:
        target, condition, used = work.pop()
        if target in reach and execute.implied(condition, reach[target]):
            continue
        reach[target] = z3.simplify(z3.Or(reach.get(target, execute.FALSE), condition))
        entries = [(entry, None, used) for entry in explicit.get(target, [])]
        entries += [(entry, stem, used | {i}) for i, (pattern, entry) in enumerate(patterns)
                    if i not in used for stem in [execute.match(pattern, target)] if stem is not None]
        for (words, rule_condition), stem, chain in entries:
            for prerequisite, prerequisite_condition in words.items():
                if stem is not None:
                    prerequisite = prerequisite.replace('%', stem, 1)
                work.append((os.path.normpath(prerequisite),
                             z3.simplify(z3.And(condition, rule_condition, prerequisite_condition)),
                             chain))
    return reach


def submakes(root, variables, rules, reach, path_condition):
    '''Find the sub-makes that the recipes of reached targets run.

    Parameters:
        root:           source tree root path
        variables:      symbolic variable table after executing the Makefile; recipes
                        expand with it, as Make expands them when they run
        rules:          recorded Make rules, as execute() returns them
        reach:          {target: path condition} of the targets make builds, from reachable()
        path_condition: incoming path condition reaching the current Makefile

    Returns:
        [(directory, makefile, goals, path condition)]:
            a line running $(MAKE) -f <file> obj=<dir> <goal>..., such as $(MAKE) $(build)=<dir>,
            gives (<dir>, None, (<goal>, ...), ...): the directory's own Kbuild file. A line
            running $(MAKE) -f <file> <goal>... without obj= gives ('.', <file>, ...), as
            Kbuild runs that file from the tree root. Each path condition conjoins
            `path_condition` with the conditions of the rule, the target, its reach, and the line.
    '''
    executor = execute.Executor(root, variables)
    found = []
    for targets, _, rule_condition, recipe in rules:
        lines = [(line, condition) for line, condition in recipe if 'MAKE)' in line.to_source()]
        if not lines:
            continue
        # pattern rules, such as %.o for single-object builds, name no directory
        for target, target_condition in execute.to_words(targets).items():
            if '%' in target or os.path.normpath(target) not in reach:
                continue
            executor.variables['@'] = {target: execute.TRUE}
            for line, line_condition in lines:
                for s, g in execute.alternatives(executor.expand(line)):
                    words = s.split()
                    if '-f' not in words[:-1]:
                        continue
                    i = words.index('-f') + 1
                    makefile = os.path.normpath(words[i])
                    dirs = [word[len('obj='):] for word in words if word.startswith('obj=')]
                    # the goals are the words after the Makefile that set no variable
                    goals = tuple(word for word in words[i + 1:]
                                  if '=' not in word and not word.startswith('-'))
                    condition = z3.simplify(z3.And(path_condition, rule_condition, target_condition,
                                                   reach[os.path.normpath(target)], line_condition, g))
                    if dirs:
                        found.append((os.path.normpath(dirs[0]), None, goals, condition))
                    else:
                        found.append(('.', makefile, goals, condition))
    return found
