import os

import vcommon as CM
import pdb

from kbuild import Kbuild

import settings
mlog = CM.getLogger(__name__, settings.logger_level)

trace = pdb.set_trace
pause = CM.pause


class Analysis:
    def __init__(self, result_dir):
        assert os.path.isdir(result_dir), result_dir

        self.kbuilds = self.load(result_dir)

    @staticmethod
    def load(result_dir):
        assert os.path.isdir(result_dir), result_dir

        kbuilds = []
        for filename in os.listdir(result_dir):
            kbuild = Kbuild.load(os.path.join(result_dir, filename))
            kbuilds.append(kbuild)

        return kbuilds
