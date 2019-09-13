import helpers.vcommon as CM
from collections import OrderedDict
import pdb
import pathlib

import helpers.vcommon as CM

DBG = pdb.set_trace

tmpdir = pathlib.Path("/var/tmp")
logger_level = 3
do_mp = True
mp_task_len = 50  # parallel processing when >= mp_task_len
detail = False


sym_prefix = "CONFIG_"
RESULT_EXT = ".kbuild_results"  # extensions of result files

settings_file = 'skbuild.ini'

# Linux config var that might not be tristate
# CONFIG_EXTRA_FIRMWARE_DIR in /firmware/Makefile


class ZState:
    y_str = "y"
    m_str = "m"
    undef_str = "undef"
    undef_val = ''

    def __init__(self, states):
        assert isinstance(states, OrderedDict), states
        self.states = states


class TriState(ZState):
    def __init__(self):
        super().__init__(OrderedDict([
            (self.y_str, self.y_str),
            (self.m_str, self.m_str),
            (self.undef_str, self.undef_val)]))


class TwoState(ZState):
    def __init__(self):
        super().__init__(OrderedDict([
            (self.y_str, self.y_str),
            (self.undef_str, self.undef_val)]))


mlog = CM.getLogger(__name__, logger_level)


class Settings:

    def __init__(self, makefile_dir):
        assert makefile_dir.is_dir(), makefile_dir
        self.makefile_dir = makefile_dir

        self.zstate = TwoState()
        self.top_dirs = []
        self.ignore_dirs = frozenset()
        self.ignore_files = frozenset()
        self.ignore_setvar_startswith = frozenset()
        self.ignore_setvar_endswith = frozenset()
        self.ignore_setvar_kws = frozenset()
        self.target_vars = frozenset(["obj-", "lib-"])
        self.ignore_vars = frozenset(["src"])

        config_file = (self.makefile_dir / settings_file).resolve()
        if not config_file.is_file():
            return

        self.config_file = config_file
        import configparser
        config = configparser.ConfigParser()
        config.read(config_file)
        myconfig = config['DEFAULT']

        try:
            self.zstate = TriState() if myconfig.getboolean(
                'use_tristate') else TwoState()
        except AttributeError:
            pass

        try:
            self.top_dirs = myconfig.get('top_dirs').split()
        except AttributeError:
            pass

        try:
            self.ignore_dirs = frozenset(
                myconfig.get('ignore_dirs').split())
        except AttributeError:
            pass

        try:
            self.ignore_files = frozenset(myconfig.get(
                'ignore_files').split())
        except AttributeError:
            pass

        try:
            self.ignore_vars = frozenset(myconfig.get(
                'ignore_vars').split())
        except AttributeError:
            pass

        try:
            self.ignore_setvar_startswith = frozenset(myconfig.get(
                'ignore_setvar_startswith').split())
        except AttributeError:
            pass

        try:
            self.ignore_setvar_endswith = frozenset(myconfig.get(
                'ignore_setvar_endswith').split())
        except AttributeError:
            pass

        try:
            self.ignore_setvar_kws = frozenset(myconfig.get(
                'ignore_setvar_kws').split())
        except AttributeError:
            pass

    @property
    def makefile_dirs(self):
        assert self.makefile_dir.is_dir(), self.makefile_dir

        try:
            return self._makefile_dirs
        except AttributeError:

            makefile_dir = self.makefile_dir.resolve()
            if self.top_dirs:
                top_dirs = [makefile_dir / d for d in self.top_dirs]
                top_dirs_ = []
                for d in top_dirs:
                    if d.is_dir():
                        top_dirs_.append(d)
                    else:
                        mlog.warn("invalid dir '{}'".format(d))
                self._makefile_dirs = top_dirs_
            else:
                self._makefile_dirs = [makefile_dir]

            mlog.debug("'{}' has {} Makefile dirs".format(
                self.makefile_dir, len(self._makefile_dirs)))

            assert all(d.is_dir() for d in self._makefile_dirs)
            return self._makefile_dirs

    def ignore_symbol(self, symbol):
        return (any(
            symbol.startswith(x)
            for x in self.ignore_setvar_startswith) or any(
                symbol.endswith(x) for x in self.ignore_setvar_endswith)
            or any(kw in symbol for kw in self.ignore_setvar_kws))
