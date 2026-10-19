import os

import z3

# Kbuild goal definition variables that specify target compilation objects
TARGET_LISTS = ('obj-y', 'lib-y')

# Variable suffixes that declare component member objects for a composite target.
# For example, a composite object `foo.o` looks up members in `foo-objs` and `foo-y`.
MEMBER_SUFFIXES = ('-objs', '-y')


def collect(directory, variables, path_condition):
    '''Extract compiled object files and expand composite objects.

    Parameters:
        directory:      path of the current directory relative to the repository root
        variables:      symbolic variable table produced after executing the directory Makefile
        path_condition: incoming path condition under which the build enters `directory`

    Returns:
        {object_path: build_condition}:
            Mapping from normalized object path to its Boolean build condition formula.
            For composite objects (e.g., `foo.o` composed of `member1.o` and `member2.o`),
            the composite is replaced by its constituent members, each inheriting the
            conjunction of the composite's selection condition and its own membership condition.
    '''
    objects = {}
    for name in TARGET_LISTS:
        for word, condition in variables.get(name, {}).items():
            if not word.endswith('.o'):
                continue
            members = {}
            for suffix in MEMBER_SUFFIXES:
                for member, member_condition in variables.get(word[:-2] + suffix, {}).items():
                    members[member] = z3.Or(members.get(member, z3.BoolVal(False)), member_condition)
            parts = {member: z3.And(condition, member_condition)
                     for member, member_condition in members.items() if member.endswith('.o')}
            # If composite members exist, emit members; otherwise emit the standalone object
            for part, part_condition in (parts or {word: condition}).items():
                obj = os.path.normpath(os.path.join(directory, part))
                objects[obj] = z3.simplify(z3.Or(objects.get(obj, z3.BoolVal(False)),
                                                 z3.And(path_condition, part_condition)))
    return objects
