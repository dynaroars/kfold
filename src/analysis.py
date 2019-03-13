import os

import vcommon as CM
import pdb
import z3
import zsolver
from kbuild import Kbuild
from ds import Paths

import settings
mlog = CM.getLogger(__name__, settings.logger_level)

trace = pdb.set_trace
pause = CM.pause


class Analysis:
    def __init__(self, result_dir):
        assert os.path.isdir(result_dir), result_dir

        self.kbuilds = self.load(result_dir)
        self.COptTyp, self.COptD, self.config_vars = self.kbuilds[0].typ_info

    def get_target_files(self, config_file):
        assert os.path.isfile(config_file), config_file

        contents = [l.split("=") for l in
                    CM.strip_contents(CM.iread(config_file))]

        myconfig = {s: self.COptD[v] for s, v in contents}
        undef = self.COptD[settings.undef_val]
        for s in self.config_vars:
            if s not in myconfig:
                myconfig[s] = undef

        myconfig = [z3.Const(s, self.COptTyp) == v for s, v
                    in myconfig.items()]
        myconfig = z3.simplify(z3.And(*myconfig))
        solver = zsolver.ZSolver()

        paths = [path for kbuild in self.kbuilds
                 for path in kbuild.paths
                 if solver.is_valid(z3.Implies(myconfig, path.cond))]
        files = list(Paths(paths).get_target_files())
        rs = {}
        for name, vals in files:
            if name not in rs:
                rs[name] = []
            rs[name].extend(list(vals))

        mlog.debug(', '.join("{}={}".format(s, v) for s, v in contents))
        mlog.debug("{} targets\n{}".format(
            len(rs), '\n'.join("{} = {}".format(
                name, ', '.join(rs[name])) for name in rs)))

        return rs

    @staticmethod
    def load(result_dir):
        assert os.path.isdir(result_dir), result_dir

        kbuilds = []
        for filename in os.listdir(result_dir):
            kbuild = Kbuild.load(os.path.join(result_dir, filename))
            kbuilds.append(kbuild)

        return kbuilds
