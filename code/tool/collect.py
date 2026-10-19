import os

import z3

# variables listing the objects a Kbuild directory builds
TARGET_LISTS = ('obj-y', 'lib-y')
# suffixes of the variables that list a composite object's members, as Kbuild's
# suffix-search looks them up for foo.o: foo-objs and foo-y
MEMBER_SUFFIXES = ('-objs', '-y')


def collect(directory, variables, path_condition):
    '''Return {object path relative to the source root: condition}.

    Each condition is conjoined with `path_condition`, the path condition under which the
    build enters `directory`. A composite object foo.o with members in foo-y or foo-objs
    is replaced by its members: Kbuild compiles them and links them into the directory's
    archive without writing foo.o.
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
            for part, part_condition in (parts or {word: condition}).items():
                obj = os.path.normpath(os.path.join(directory, part))
                objects[obj] = z3.simplify(z3.Or(objects.get(obj, z3.BoolVal(False)),
                                                 z3.And(path_condition, part_condition)))
    return objects
