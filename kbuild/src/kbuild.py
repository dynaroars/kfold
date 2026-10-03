import os
import pathlib
import pdb
import z3

from pymake3 import parser, parserdata

import helpers.vcommon as CM
import helpers.zsolver as zsolver

from ds import SState, DState
import symexe as SE

import settings
mlog = CM.getLogger(__name__, settings.logger_level)

DBG = pdb.set_trace


import re

def clean_makefile_text(text: str) -> str:
    """Normalize line endings to LF before parsing. Nothing else is changed:
    a '#' on a recipe line is shell text and "\\#" in a value is a literal
    '#', so removing a backslash after '#' would break the line
    continuation of, e.g., scripts/kconfig/Makefile's help recipe."""
    return text.replace('\r\n', '\n').replace('\r', '\n')


_VAR_REF = re.compile(r"\$[({]([A-Za-z0-9_.-]+)[)}]")
MAX_INCLUDE_DEPTH = 8


_AFFIX_CALL = re.compile(r"\$\((addprefix|addsuffix) ([^,$()]*),([^$()]*)\)")


def _affix(m):
    fun, affix, words = m.group(1), m.group(2), m.group(3).split()
    if fun == "addprefix":
        return " ".join(affix + w for w in words)
    return " ".join(w + affix for w in words)


def _resolve(text, env):
    """Substitute $(NAME) references whose value is known statically, and
    $(addprefix ...)/$(addsuffix ...) calls whose arguments are resolved."""
    for _ in range(10):
        new = _VAR_REF.sub(lambda m: env.get(m.group(1), m.group(0)), text)
        new = _AFFIX_CALL.sub(_affix, new)
        if new == text:
            break
        text = new
    return text


def read_makefile_text(path):
    raw_bytes = path.read_bytes()
    try:
        raw_text = raw_bytes.decode('utf-8')
    except UnicodeDecodeError:
        raw_text = raw_bytes.decode('latin-1', errors='replace')
    return clean_makefile_text(raw_text)


def splice_includes(stmts, env, maindir, chain=(), stats=None):
    """Replace each ``include`` whose path resolves statically to an existing
    file with that file's statements, recursively. Kbuild evaluates an
    included fragment in the including Makefile's context and with the
    source tree as working directory, so relative words keep the includer's
    directory and relative include paths are resolved against ``maindir``.
    ``env`` tracks simple constant assignments seen so far; an include whose
    path still contains an unresolved reference is left in place (and, as
    before, not executed)."""
    out = parserdata.StatementList()
    for stmt in stmts:
        if isinstance(stmt, parserdata.SetVariable) and stmt.targetexp is None:
            name = stmt.vnameexp.to_source()
            if "$" not in name:
                value = _resolve(stmt.value.strip(), env)
                if "$" not in value:
                    if stmt.token in (":=", "=", "::="):
                        env[name] = value
                    elif stmt.token == "+=" and name in env:
                        env[name] = (env[name] + " " + value).strip()
                    elif stmt.token == "?=":
                        env.setdefault(name, value)
            out.append(stmt)
        elif isinstance(stmt, parserdata.ConditionBlock):
            for i, (cond, group) in enumerate(stmt._groups):
                stmt._groups[i] = (cond, splice_includes(group, env, maindir, chain, stats))
            out.append(stmt)
        elif isinstance(stmt, parserdata.Include):
            text = _resolve(stmt.exp.to_source(), env)
            if "$" in text or len(chain) >= MAX_INCLUDE_DEPTH:
                if stats is not None:
                    stats["unresolved"] += 1
                out.append(stmt)
                continue
            for word in text.split():
                path = pathlib.Path(word)
                path = (path if path.is_absolute() else maindir / path).resolve()
                if os.environ.get("KFOLD_SANDBOX") and not path.is_relative_to(maindir):
                    if stats is not None:
                        stats["missing"] += 1
                    continue  # sandbox: only files inside the analyzed tree
                if not path.is_file() or path in chain:
                    if stats is not None:
                        stats["missing"] += 1
                    continue
                try:
                    included = parser.parsestring(read_makefile_text(path), path)
                except Exception as e:
                    mlog.warn(f"Failed to parse included {path}: {e}")
                    continue
                if stats is not None:
                    stats["spliced"] += 1
                for s2 in splice_includes(included, env, maindir, chain + (path,), stats):
                    out.append(s2)
        else:
            out.append(stmt)
    return out


class Kbuild:
    def __init__(self, makefile, mysettings):
        assert makefile.is_file(), makefile
        assert isinstance(mysettings, settings.Settings), mysettings

        self.makefile = makefile
        self.mysettings = mysettings
        self.solver = zsolver.ZSolver(self.mysettings)

    def preprocess(self):
        try:
            content = read_makefile_text(self.makefile)
        except Exception as e:
            mlog.warn(f"Failed to read {self.makefile}: {e}")
            content = ""

        self.parse_error = None
        try:
            stmts = parser.parsestring(content, self.makefile)
        except Exception as e:
            # One unparsable file contributes nothing instead of stopping
            # the whole traversal; the failure is recorded.
            mlog.warn(f"Failed to parse {self.makefile}: {e}")
            self.parse_error = str(e)
            stmts = parserdata.StatementList()
        maindir = self.mysettings.maindir.resolve()
        parent = self.makefile.parent.resolve()
        try:
            rel = str(parent.relative_to(maindir)) or "."
        except ValueError:
            rel = str(parent)
        env = {"src": rel, "obj": rel, "srctree": str(maindir), "objtree": str(maindir)}
        env.update(self.mysettings.defines)
        self.include_stats = {"spliced": 0, "unresolved": 0, "missing": 0}
        if not os.environ.get("KFOLD_NO_INCLUDES"):  # ablation switch
            stmts = splice_includes(stmts, env, maindir, (self.makefile.resolve(),),
                                    self.include_stats)
        mystmts = SE.StatementList.create(stmts, sid=tuple())
        siz = mystmts.siz
        mlog.debug("Preprocessing {} stmts".format(siz))
        mystmts.set_solver(self.solver)
        dstate = DState.get_default(self.makefile.parent, self.mysettings)
        mystmts.dexe(dstate, frozenset())
        dstate.compute_used_vars()
        reduced = mystmts.myreduce(dstate.ddb)
        if reduced is None:
            # The whole file turned out irrelevant to any target var (e.g.
            # a Makefile that only sets variables no obj-/lib- var of ours
            # depends on): keep an empty, harmless statement list rather
            # than crashing.
            mystmts = SE.StatementList.create(parserdata.StatementList(), sid=tuple())
            mystmts.set_solver(self.solver)
        else:
            mystmts = reduced
        nremoved = siz - mystmts.siz
        mlog.debug("After processing {} remain {}".format(
            mystmts.siz, "({} removed)".format(nremoved) if nremoved else ''))
        mystmts.set_preds(pred=None)

        self.stmts = mystmts
        self.dstate = dstate

    def symexe(self):
        mlog.debug("Symexe ({} used vars) ...".format(
            len(self.dstate.ddb.used_vars)))
        state = SState.get_default(self.makefile.parent, self.mysettings)
        self.stmts.sexe(state, zsolver.T, self.dstate.ddb)
        state.expand_deferred(self.solver)
        self.state = state

    def fork(self, new_cond):
        """Return a new Kbuild sharing this one's (already computed) state,
        restricted to an additional external condition -- e.g. this
        Makefile's directory was reached under some parent guard. Replaces
        the old per-Path ``fork``, which forked every remaining ``Path``."""
        assert z3.is_expr(new_cond), new_cond

        kbuild = self.__class__(self.makefile, self.mysettings)
        kbuild.state = self.state.restrict(new_cond, self.solver)
        for attr in ("include_stats", "parse_error"):
            if hasattr(self, attr):
                setattr(kbuild, attr, getattr(self, attr))
        return kbuild

    def save(self, tofile):
        """
        save info to file / load info from file
        note things are a bit complex because
        Z3 data structures cannot be saved directly to file
        """
        assert (isinstance(tofile, pathlib.Path)
                and not tofile.exists() and tofile), tofile
        kinfo = (self.makefile,
                 self.state.to_savable(),
                 list(self.solver.__config_vars__.keys()))

        CM.vsave(tofile, kinfo)

    @staticmethod
    def load(fromfile, mysettings):
        assert fromfile.is_file(), fromfile
        assert isinstance(mysettings, settings.Settings), mysettings

        kinfo = CM.vload(fromfile)
        makefile, state_info, config_names = kinfo

        kbuild = Kbuild(makefile, mysettings)
        state = SState.from_savable(state_info, mysettings)
        kbuild.solver.reconstruct(config_names)
        kbuild.state = state
        return kbuild
