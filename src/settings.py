import helpers.vcommon as CM
from collections import OrderedDict
import pdb
import pathlib

import helpers.vcommon as CM

DBG = pdb.set_trace

import os
tmpdir = pathlib.Path(os.environ.get("SKBUILD_TMP", "/tmp"))
logger_level = 3
detail = False


RESULT_SINFO = 'sinfo'


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
    filename = 'skbuild.ini'

    def __init__(self, maindir, use_tristate: bool = False):
        assert maindir.is_dir(), maindir

        # default values
        self.maindir = maindir   # original inpt dir
        self.zstate = TriState() if use_tristate else TwoState()
        self.topdirs = []
        # top_dirs entries may carry a guard, "dir?CONFIG_X", for directories
        # that top-level orchestration (e.g. drivers-$(CONFIG_PCI) += pci/)
        # enters only when CONFIG_X=y.
        self.topdir_guards = {}
        # defines: variables with a fixed value in every Makefile, such as
        # SRCARCH=x86, like Make's command-line definitions.
        self.defines = {}
        self.define_guards = {}
        # composite_objects: "all" if a composite's container object is
        # written whenever it is selected, "modules" if only for obj-m (Linux
        # links built-in composites' members into built-in.a directly).
        self.composite_objects = "all"
        # need_builtin: Kbuild builds a directory's obj-y objects only when
        # the directory is reached through obj-y entries from the top
        # (Makefile.build's need-builtin); obj-m or subdir-y reachability is
        # not enough.
        self.need_builtin = False
        # extra_objects: objects produced by top-level link steps, each
        # optionally guarded by an option that must be y.
        self.extra_objects = []
        # entry_goals: files that top-level rules build (e.g. the boot image),
        # each optionally guarded by an option that must be y or m.
        self.entry_goals = []
        # family_aliases: a family whose objects Make adds to other families,
        # e.g. coreboot's all-y joins bootblock-y, romstage-y, ...
        self.family_aliases = {}
        self.ignore_dirs = frozenset()
        self.ignore_files = frozenset()
        self.ignore_setvar_startswith = frozenset()
        self.ignore_setvar_endswith = frozenset()
        self.ignore_setvar_kws = frozenset()
        self.target_vars = frozenset(["obj-", "lib-"])
        self.entry_files = ["Kbuild", "Makefile", "Makefile.inc"]
        self.ignore_vars = frozenset(["src"])
        self.xopts = {}

        settings_file = maindir / self.filename
        if os.environ.get("KFOLD_SETTINGS_FILE"):  # ablation: other settings
            settings_file = pathlib.Path(os.environ["KFOLD_SETTINGS_FILE"])
        if not settings_file.is_file():
            return

        # read from config file
        import configparser
        config = configparser.ConfigParser()
        config.optionxform = str  # preserve case sensitvity
        config.read(settings_file)
        section = 'COMMON' if 'COMMON' in config else 'DEFAULT'
        myconfig = config[section]

        try:
            if myconfig.getboolean('use_tristate'):
                self.zstate = TriState()
        except AttributeError:
            pass

        try:
            for entry in myconfig.get('top_dirs').split():
                # A directory listed several times is entered if any of its
                # guards holds; an unguarded entry makes it unconditional.
                d, _, guard = entry.partition('?')
                if d not in self.topdirs:
                    self.topdirs.append(d)
                    self.topdir_guards[d] = []
                if self.topdir_guards[d] is not None:
                    self.topdir_guards[d] = (self.topdir_guards[d] + [guard]
                                             if guard else None)
        except AttributeError:
            pass

        if 'need_builtin' in myconfig:
            self.need_builtin = myconfig.getboolean('need_builtin')
        if 'composite_objects' in myconfig:
            self.composite_objects = myconfig.get('composite_objects').strip()
        if 'entry_goals' in myconfig:
            for entry in myconfig.get('entry_goals').split():
                path, _, guard = entry.partition('?')
                self.entry_goals.append((path, guard or None))
        if 'extra_objects' in myconfig:
            for entry in myconfig.get('extra_objects').split():
                path, _, guard = entry.partition('?')
                self.extra_objects.append((path, guard or None))

        if 'family_aliases' in myconfig:
            for entry in myconfig.get('family_aliases').split():
                name, _, targets = entry.partition(':')
                self.family_aliases[name] = targets.split(',')

        # defines entries are NAME=VALUE or NAME=VALUE?CONFIG_X; a name given
        # several guarded values takes each where its option is y.
        self.define_guards = {}
        if 'defines' in myconfig:
            for entry in myconfig.get('defines').split():
                name, _, rest = entry.partition('=')
                value, _, guard = rest.partition('?')
                if guard:
                    self.define_guards.setdefault(name, []).append((value, guard))
                else:
                    self.defines[name] = value

        try:
            if 'entry_files' in myconfig:
                self.entry_files = myconfig.get('entry_files').split()
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
            if 'target_vars' in myconfig:
                self.target_vars = frozenset(
                    myconfig.get('target_vars').split())
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
