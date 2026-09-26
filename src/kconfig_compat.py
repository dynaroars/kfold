"""Let kconfiglib parse Kconfig syntax newer than kconfiglib itself.

Importing this module patches ``kconfiglib.Kconfig._open`` once so that
lines using newer syntax are read in an equivalent older form (REWRITES):

``modules``
    Newer scripts/kconfig accepts a bare ``modules`` line in a config entry
    (lexer.l: "modules" -> T_MODULES; parser.y: config_option: T_MODULES)
    where it used to require ``option modules``; kconfiglib knows only the
    older spelling, which means the same thing.

``depends on X if C``
    A conditional dependency (Linux 7.x). scripts/kconfig/menu.c
    (menu_add_dep) turns it into ``X || (C = n)`` and expr_trans_compare
    rewrites ``(C = n)`` for C = SYM as ``SYM = n`` and for C = !SYM as
    ``SYM = y``; the line is rewritten to that older syntax. Only a single
    symbol or its negation is accepted as C (all such lines in Linux 7.2.8);
    anything else raises an error rather than being guessed at. Note that
    ``X || !C`` would not be equivalent: for C = m it is m, not X.

``transitional``

Linux 6.18 added the ``transitional`` symbol attribute (Documentation/kbuild/
kconfig-language.rst): a transitional symbol may have only a help text, is
read from an old .config so that another symbol's ``default`` can migrate its
value, and is never written back. kconfiglib (14.1.0) rejects the keyword with
a syntax error, which makes it unable to parse Linux 7.x at all. Without the
keyword, kconfiglib sees the same symbol with no prompt, no default, and no
dependencies -- exactly how scripts/kconfig evaluates it -- so dropping the
line does not change any symbol value kfold computes. The only difference, not
writing the symbol back to a .config, does not matter to kfold, which never
writes .config files through kconfiglib.
"""
import os
import re
import subprocess

import kconfiglib

REWRITES = {"transitional": "", "modules": "option modules"}
_COND_DEP = re.compile(r"^(\s*)depends\s+on\s+(.*?)\s+if\s+(!?)\s*([A-Za-z0-9_]+)\s*$")


def _rewrite_cond_dep(line):
    code, hash_, comment = line.rstrip("\n").partition("#")
    if not re.match(r"\s*depends\s+on\b", code) or not re.search(r"\sif\s", code):
        return line
    m = _COND_DEP.match(code)
    if not m:
        raise ValueError(f"unsupported conditional dependency: {line.strip()}")
    indent, dep, neg, sym = m.groups()
    test = f"{sym} = y" if neg else f"{sym} = n"
    return f"{indent}depends on ({dep}) || ({test}){' ' + hash_ + comment if hash_ else ''}\n"


class _Filtered:
    """A read-only file object applying REWRITES to lines that consist of
    exactly one rewritten keyword (indentation is kept)."""

    def __init__(self, f):
        self._f = f

    def readline(self):
        line = self._f.readline()
        word = line.strip()
        if word in REWRITES:
            indent = line[:len(line) - len(line.lstrip())]
            return indent + REWRITES[word] + "\n"
        return _rewrite_cond_dep(line)

    def __iter__(self):
        return iter(self.readline, "")

    def read(self):
        return "".join(self)

    def close(self):
        self._f.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


if not getattr(kconfiglib.Kconfig, "_kfold_compat", False):
    _open = kconfiglib.Kconfig._open

    def _open_compat(self, filename, mode):
        f = _open(self, filename, mode)
        return _Filtered(f) if "r" in mode else f

    kconfiglib.Kconfig._open = _open_compat

    _str_value = kconfiglib.Symbol.str_value
    _EMPTY = {kconfiglib.INT: "0", kconfiglib.HEX: "0x0"}

    def _str_value_compat(self):
        v = _str_value.fget(self)
        return _EMPTY.get(self.orig_type, v) if v == "" else v

    kconfiglib.Symbol.str_value = property(_str_value_compat)
    kconfiglib.Kconfig._kfold_compat = True


def makefile_exports(srctree, env=None):
    """Values the Linux top-level Makefile computes and exports to Kconfig
    (Makefile: CC_VERSION_TEXT, RUSTC_VERSION_TEXT, PAHOLE_VERSION), computed
    the same way from the tools named in ``env`` (default os.environ). Kconfig
    reads them as "$(CC_VERSION_TEXT)" etc.; left unset, the options that
    probe them evaluate as if the tools were absent."""
    env = os.environ if env is None else env

    def first_line(cmd):
        try:
            out = subprocess.run(cmd, capture_output=True, text=True,
                                 env=dict(env, LC_ALL="C")).stdout
        except OSError:
            return ""
        return out.splitlines()[0].replace("#", "") if out else ""

    pahole = os.path.join(str(srctree), "scripts", "pahole-version.sh")
    return {
        "CC_VERSION_TEXT": first_line([env.get("CC", "gcc"), "--version"]),
        "RUSTC_VERSION_TEXT": first_line([env.get("RUSTC", "rustc"), "--version"]),
        "PAHOLE_VERSION": first_line([pahole, env.get("PAHOLE", "pahole")]) if os.path.exists(pahole) else "",
    }
