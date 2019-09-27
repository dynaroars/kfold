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


RESULT_SINFO = 'sinfo'

settings_file = 'skbuild.ini'


# Linux config var that might not be tristate
# CONFIG_EXTRA_FIRMWARE_DIR in /firmware/Makefile


class ZState:
    COPT_PREFIX = "CONFIG_"

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

    def __init__(self, settings_file):
        # default values
        self.zstate = TwoState()
        self.top_dirs = []
        self.ignore_dirs = frozenset()
        self.ignore_files = frozenset()
        self.ignore_setvar_startswith = frozenset()
        self.ignore_setvar_endswith = frozenset()
        self.ignore_setvar_kws = frozenset()
        self.target_vars = frozenset(["obj-", "lib-"])
        self.ignore_vars = frozenset(["src"])

        if not settings_file.is_file():
            return

        # read from config file
        import configparser
        config = configparser.ConfigParser()
        config.optionxform = str  # preserve case sensitvity
        config.read(settings_file)
        myconfig = config['COMMON']

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

        self.xopts = {}
        try:
            myconfig = config['COPTIONS']  # BITS = 32 64
            for k in myconfig:
                vals = ['' if v ==
                        'None' else v for v in myconfig.get(k).split()]

                self.xopts[k] = vals
        except KeyError:
            pass

    def is_copt(self, name):
        return name.startswith(self.zstate.COPT_PREFIX)

    def is_xopt(self, name):
        return name in self.xopts

    def ignore_symbol(self, symbol):
        return (any(symbol.startswith(x)
                    for x in self.ignore_setvar_startswith) or
                any(symbol.endswith(x)
                    for x in self.ignore_setvar_endswith) or
                any(kw in symbol for kw in self.ignore_setvar_kws))
