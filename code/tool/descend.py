import os

import z3


def descend(directory, variables, path_condition):
    '''Find subdirectory descent targets declared in obj-y.

    In Kbuild, appending a directory path (ending in '/') to obj-y instructs Make
    to recurse into that subdirectory's Makefile.

    Parameters:
        directory:      path of the current directory relative to the repository root
        variables:      symbolic variable table produced after executing the directory Makefile
        path_condition: incoming path condition reaching the current directory

    Returns:
        [(child_directory, child_path_condition)]:
            child_directory:      normalized relative path to child subdirectory
            child_path_condition: conjunction of directory reaching condition and obj-y condition
    '''
    return [(os.path.normpath(os.path.join(directory, word)),
             z3.simplify(z3.And(path_condition, condition)))
            for word, condition in variables.get('obj-y', {}).items() if word.endswith('/')]
