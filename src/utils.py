#! /usr/bin/env python


import vcommon as CM
import z3
import copy
from collections import OrderedDict, Counter
import itertools
import time
import re

from shutil import copyfile
import os
import os.path
import sys

import pdb
trace = pdb.set_trace

pause = CM.pause

logger_level = 3


# class Analyze:
#     def __init__(self, path):
#         self.path = path

#     def go(self):
#         makefiles, _ = self.get_makefiles(self.path)

#         counter = {}
#         for makefile in makefiles:
#             counter[makefile] = self.count_var_CONFIG(makefile)

#         counter = Counter(counter)
#         ss = ["{}. {} has {} CONFIG vars".format(i+1, file, n_occurs)
#               for i, (file, n_occurs) in enumerate(counter.most_common()[::-1])
#               if n_occurs]
#         print("{} Kbuild makefiles\n{}".format(len(file), '\n'.join(ss)))


def fileOK(makefile):
    n_configs = count_var_CONFIG(makefile)
    return n_configs >= 1


def create_makefiles(from_dir, to_dir, fileOK):
    assert os.path.isdir(from_dir) and os.path.isabs(from_dir), from_dir
    #assert os.path.isdir(to_dir) and os.path.isabs(to_dir), to_dir

    makefiles = get_makefiles(from_dir)
    if fileOK is not None:
        makefiles = [f for f in makefiles if fileOK(f)]
    for file in makefiles:

        new_file = file.replace(from_dir, '')
        if new_file.startswith('/'):
            new_file = new_file[1:]
        new_file = os.path.join(to_dir, new_file)

        new_dir = os.path.dirname(new_file)

        if not os.path.isdir(new_dir):
            os.makedirs(new_dir)

        copyfile(file, new_file)
    print("copy {} makefiles from '{}' to '{}'".format(
        len(makefiles), from_dir, to_dir))


def get_makefiles(from_dir):
    assert os.path.isdir(from_dir) and os.path.isabs(from_dir), from_dir

    kbuild_files = []
    for root, subdirs, files in os.walk(from_dir):
        subdirs[:] = [sdir for sdir in subdirs if not sdir.startswith('.')]

        kbuild_file = os.path.join(root, 'Kbuild')
        if os.path.isfile(kbuild_file):
            kbuild_files.append(kbuild_file)
        else:
            kbuild_file = os.path.join(root, 'Makefile')
            if os.path.isfile(kbuild_file):
                kbuild_files.append(kbuild_file)

    return kbuild_files


def count_var_CONFIG(makefile):
    results = []
    for l in CM.iread(makefile):
        config_s = re.findall(r"\(CONFIG_\w+\)", l)
        results.extend(config_s)

    results = set(results)
    return len(results)


# scripts
from_dir = os.path.abspath(os.path.expanduser("~/Src/LOCAL/EXP/kmax/linux/"))
to_dir = os.path.abspath(os.path.expanduser(
    "~/Src/LOCAL/EXP/kmax/linux_makefiles_only"))

create_makefiles(from_dir, to_dir, fileOK)
