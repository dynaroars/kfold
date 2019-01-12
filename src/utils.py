import copy
from collections import OrderedDict, Counter
import itertools
import time
import re

import os
import os.path
import sys

import pdb
trace = pdb.set_trace

import z3
import vcommon as CM
pause = CM.pause

logger_level = 3


class Analyze:
    def __init__(self, path):
        self.path = path
        
    def go(self):
        makefiles = self.get_makefiles(self.path)

        counter = {}
        for makefile in makefiles:
            n_occurs = self.count_var_CONFIG(makefile)
            counter[makefile] = n_occurs
            #mlog.debug("{} has {} CONFIGS".format(makefile, n_occurs))

        counter = Counter(counter)
        ss = ["{}. {} has {} CONFIG vars".format(i+1, makefile, n_occurs)
              for i, (makefile, n_occurs) in enumerate(counter.most_common())]
        mlog.info("{} Kbuild makefiles\n{}".format(len(makefiles), '\n'.join(ss)))
        
        
    @staticmethod
    def get_makefiles(topdir):
        kbuild_files = []
        for root, subdirs, files in os.walk(os.path.abspath(topdir)):
            subdirs[:] = [sdir for sdir in subdirs if not sdir.startswith('.')]
            
            kbuild_file = os.path.join(root, 'Kbuild')
            if os.path.isfile(kbuild_file):
                kbuild_files.append(kbuild_file)
            else:
                kbuild_file = os.path.join(root, 'Makefile')
                if os.path.isfile(kbuild_file):
                    kbuild_files.append(kbuild_file)
                
        return kbuild_files


    @staticmethod
    def count_var_CONFIG(makefile):
        results = []
        for l in CM.iread(makefile):
            config_s = re.findall(r"\(CONFIG_\w+\)", l)
            results.extend(config_s)

        results = set(results)
        return len(results)
        
if __name__ == '__main__':    

    import argparse    
    aparser = argparse.ArgumentParser("find interactions from Kbuild Makefiles")
    ag = aparser.add_argument
    ag('path',
       type=str,
       help="""path to Linux Makefiles or dirs""")
    
    ag("--log_level", "-log_level",
       help="set logger info",
       type=int, 
       choices=range(5),
       default = 3)

    ag('--case-study',
       type=str,
       help="""avail options: busybox/linux""")
    
    args = aparser.parse_args()

    from vcommon import getLogLevel , getLogger
    if args.log_level != logger_level and 0 <= args.log_level <= 4:
        logger_level = args.log_level

    logger_level = getLogLevel(logger_level)
    mlog = getLogger(__name__, logger_level)    
    if __debug__:
        mlog.warn("DEBUG MODE ON. Can be slow! (Use python -O ... for optimization)")

    myrun = Analyze(args.path)        
    myrun.go()
    
    
