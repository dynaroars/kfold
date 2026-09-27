"""Object paths and their selection conditions for an analyzed Kbuild tree.

``object_conditions`` collects every object path that a run's Makefiles
select: the words of target-family variables (``obj-y``, ``lib-y``, stage
families), the members of composite objects (``foo-y``, ``foo-objs``), the
objects of multi-object host and user programs, configured link artifacts,
and the objects that rules build as prerequisites of selected files. Each
path has the condition under which Kbuild builds it. ``predicted_objects``
evaluates those conditions under a normalized ``.config``.
"""
import os
import os.path
import pathlib

import z3
from z3.z3util import get_vars

import helpers.zsolver as zsolver

STAGES = {"bootblock", "romstage", "ramstage", "postcar", "verstage", "smm",
          "decompressor"}


def config_values(config):
    return dict(line.split("=", 1)
                for line in pathlib.Path(config).read_text(errors="replace").splitlines()
                if line.startswith("CONFIG_") and "=" in line)



def target_path(word, var_name, parent, source):
    if word.endswith((".c", ".C", ".S", ".s")):
        word = str(pathlib.Path(word).with_suffix(".o"))
    elif not word.endswith((".o", ".a")):
        return None
    # Kbuild words such as ../display/dc.o are relative to the Makefile's
    # directory; normalize them to the path the compiler writes.
    full = pathlib.Path(os.path.normpath(parent / word))
    try:
        rel = full.relative_to(source)
    except ValueError:
        rel = pathlib.Path(word)
    stage = var_name.split("-", 1)[0]
    if stage in STAGES:
        parts = rel.parts[1:] if rel.parts and rel.parts[0] == "src" else rel.parts
        rel = pathlib.Path("build") / stage / pathlib.Path(*parts)
    return str(rel)



def _suffixed(rel, var_name, suffixes):
    """Apply a family's object suffix (family_suffixes), e.g. foo.o in pbl-y
    is written as foo.pbl.o."""
    suffix = suffixes.get(var_name.rsplit("-", 1)[0])
    if rel is not None and suffix and rel.endswith(".o"):
        return rel[:-2] + suffix
    return rel


def _add(targets, kinds, rel, cond, kind):
    if rel in targets:
        targets[rel] = zsolver.disj(targets[rel], cond)
        if kind == "target":
            kinds[rel] = "target"
    else:
        targets[rel] = cond
        kinds[rel] = kind



def builtin_guards(runner):
    """{Makefile: guard under which it is reached through obj-y entries only},
    starting from the entry Makefiles; a fixpoint over all analyzed
    instances."""
    from alg import Run
    solver = zsolver.ZSolver(runner.mysettings)
    guards = {}
    for mk, cond in runner.makefiles:
        c = zsolver.T if cond is None else cond
        guards[mk] = zsolver.disj(guards[mk], c) if mk in guards else c
    child_cache = {}
    changed = True
    while changed:
        changed = False
        for kb in runner.all_kbuilds:
            parent_guard = guards.get(kb.makefile)
            if parent_guard is None:
                continue
            var = kb.state.states.get("obj-y")
            if var is None or var.ignorable:
                continue
            for d, c in var.subdirs_with_cond(kb.makefile.parent).items():
                if d not in child_cache:
                    child_cache[d] = Run.get_makefile(d, runner.mysettings)
                mk = child_cache[d]
                if mk is None:
                    continue
                new = zsolver.conj(c, parent_guard)
                old = guards.get(mk)
                if old is None:
                    guards[mk] = new
                    changed = True
                elif not solver.is_valid(z3.Implies(new, old)):
                    guards[mk] = zsolver.disj(old, new)
                    changed = True
    return guards



def object_conditions(runner, include_members=True, origins=None):
    """Return ({path: condition}, {path: kind}), where kind is "target",
    "member", "program", "extra", or "rule". If ``origins`` is a dict, it
    receives {path: {(Makefile relative to the tree, variable or rule)}}."""
    targets, kinds = {}, {}

    def note(path, makefile, what):
        if origins is not None and path is not None:
            try:
                mk = str(makefile.relative_to(runner.maindir))
            except ValueError:
                mk = str(makefile)
            origins.setdefault(path, set()).add((mk, what))
    link_semantics = not os.environ.get("KFOLD_NO_LINK_SEMANTICS")  # ablation switch
    modules_only = link_semantics and getattr(runner.mysettings, "composite_objects", "all") == "modules"
    if include_members:
        solver = zsolver.ZSolver(runner.mysettings)
        for path, sym in getattr(runner.mysettings, "extra_objects", []):
            guard = zsolver.T
            if sym:
                zvar, values = solver.get_sort(sym)
                guard = zvar == values["y"]
            _add(targets, kinds, path, guard, "extra")
            note(path, runner.maindir / "skbuild.ini", "extra_objects")
    suffixes = getattr(runner.mysettings, "family_suffixes", {})
    fguards = {}
    for fam, sym in getattr(runner.mysettings, "family_guards", {}).items():
        gsolver = zsolver.ZSolver(runner.mysettings)
        zvar, values = gsolver.get_sort(sym)
        fguards[fam] = zvar == values["y"]

    def fguard(name, cond):
        g = fguards.get(name.rsplit("-", 1)[0])
        return cond if g is None else zsolver.conj(cond, g)
    need_builtin = link_semantics and getattr(runner.mysettings, "need_builtin", False)
    builtin = builtin_guards(runner) if need_builtin else {}
    roots = []  # non-object targets whose rules the closure follows
    for kb in runner.all_kbuilds:
        state, parent = kb.state, kb.makefile.parent
        for var in state.target_files:
            if var.name in runner.mysettings.target_vars:
                continue
            # obj-y objects go into built-in.a, which Kbuild builds only for
            # a directory with a built-in route; lib-y, extra-y, and always-y
            # objects are built whenever the directory is visited.
            bguard = (builtin.get(kb.makefile, zsolver.F)
                      if need_builtin and var.name == "obj-y" else None)
            family = var.name.rsplit("-", 1)[0]
            aliases = getattr(runner.mysettings, "family_aliases", {}).get(family)
            names = [f"{a}-y" for a in aliases] if aliases else [var.name]
            for word, cond in var.valconds.items():
                if not isinstance(word, str):
                    continue
                if bguard is not None:
                    cond = zsolver.conj(cond, bguard)
                # A built-in composite's container is linked from its members
                # without an object file of its own under "modules".
                unwritten = (include_members and modules_only
                             and not var.name.endswith("-m") and word.endswith(".o")
                             and state.composite_members(word[:-2]))
                for name in names:
                    rel = _suffixed(target_path(word, name, parent, runner.maindir), name, suffixes)
                    if rel is not None and not unwritten:
                        _add(targets, kinds, rel, fguard(name, cond), "target")
                        note(rel, kb.makefile, var.name)
                rel = target_path(word, names[0], parent, runner.maindir)
                if rel is None:
                    # Kbuild builds every always-y and extra-y target, e.g.
                    # kernel/trace's simple_ring_buffer.o.checked, whose
                    # pattern rule needs undefsyms_base.o.
                    if family in ("always", "extra") and "$" not in word:
                        root = _norm(parent, word, runner.maindir)
                        if root is not None:
                            roots.append((root, cond))
                    continue
                if not include_members:
                    continue
                modular = var.name.endswith("-m")
                work, seen = [(word, cond)], {word}
                while work:
                    obj, obj_cond = work.pop()
                    stem = obj[:-2] if obj.endswith((".o", ".a")) else obj
                    for member, mcond in state.composite_members(stem, include_m=modular).items():
                        # A composite may list an object of its own name,
                        # e.g. lib/dim: dim-y := dim.o net_dim.o.
                        if member in seen and member != obj:
                            continue
                        eff = zsolver.conj(obj_cond, mcond)
                        for name in names:
                            mrel = _suffixed(target_path(member, name, parent, runner.maindir),
                                             name, suffixes)
                            if mrel is not None:
                                _add(targets, kinds, mrel, fguard(name, eff), "member")
                                note(mrel, kb.makefile, f"member of {obj}")
                        if member not in seen:
                            seen.add(member)
                            work.append((member, eff))
        if not include_members:
            continue
        # Multi-object host and user programs: p in hostprogs with p-objs.
        for var in state.program_files:
            for prog, cond in var.valconds.items():
                if not isinstance(prog, str) or "$" in prog:
                    continue
                for member, mcond in state.composite_members(prog).items():
                    rel = target_path(member, "obj-y", parent, runner.maindir)
                    if rel is not None:
                        _add(targets, kinds, rel, zsolver.conj(cond, mcond), "program")
                        note(rel, kb.makefile, f"object of program {prog} ({var.name})")
    if include_members and not os.environ.get("KFOLD_NO_RULES"):  # ablation switch
        rule_closure(runner, targets, kinds, note, roots)
    return targets, kinds



def _norm(parent, word, maindir):
    full = pathlib.Path(os.path.normpath(parent / word))
    try:
        return str(full.relative_to(maindir))
    except ValueError:
        return None



class _RuleIndex:
    """Explicit rules, pattern rules, and sub-makes of analyzed Makefiles,
    keyed by target paths relative to the source root."""

    def __init__(self, maindir):
        self.maindir = maindir
        self.explicit = {}   # target -> [(prereq, cond)]
        self.patterns = []   # (dir, target pattern, [(prereq pattern, cond)])
        self.submakes = {}   # target -> [(makefile dir, goal, cond)]
        self.seen = set()

    def add_state(self, makefile, state):
        key = (makefile, id(state))
        if key in self.seen:
            return
        self.seen.add(key)
        parent = makefile.parent
        for name, var in state.states.items():
            if not (name.startswith("__rule") and name.endswith("_t")):
                continue
            base = name[:-2]
            prereqs = state.states.get(base + "_p")
            subs = state.states.get(base + "_m")
            for t, tc in var.valconds.items():
                if not isinstance(t, str):
                    continue
                if "%" in t:
                    ps = [(p, zsolver.conj(tc, pc)) for p, pc in (prereqs.valconds.items() if prereqs else [])]
                    self.patterns.append((parent, t, ps))
                    continue
                tpath = _norm(parent, t, self.maindir)
                if tpath is None:
                    continue
                if prereqs:
                    for p, pc in prereqs.valconds.items():
                        ppath = _norm(parent, p, self.maindir) if isinstance(p, str) else None
                        if ppath:
                            self.explicit.setdefault(tpath, []).append((ppath, zsolver.conj(tc, pc)))
                if subs:
                    for w, wc in subs.valconds.items():
                        d, _, goal = w.partition("|")
                        subdir = pathlib.Path(os.path.normpath(parent / d))
                        g = _norm(parent, goal, self.maindir) if goal else None
                        self.submakes.setdefault(tpath, []).append((subdir, g, zsolver.conj(tc, wc)))

    def _pattern_matches(self, path):
        """Instantiated prerequisites of each pattern rule matching path."""
        for parent, pattern, ps in self.patterns:
            ptext = _norm(parent, pattern.replace("%", "\0"), self.maindir)
            if ptext is None:
                continue
            pre, _, post = ptext.partition("\0")
            if path.startswith(pre) and path.endswith(post) and len(path) >= len(pre) + len(post):
                stem = path[len(pre):len(path) - len(post)]
                inst = []
                for p, pc in ps:
                    if p == "FORCE":
                        continue
                    pp = _norm(parent, p.replace("%", stem, 1), self.maindir)
                    if pp:
                        inst.append((pp, pc))
                # A match-anything rule (target "%" or "dir/%", such as
                # Kbuild's "$(obj)/%:: $(src)/%_shipped") never chains in GNU
                # Make: terminal ones need existing prerequisites, and
                # nonterminal ones do not apply to prerequisites of other
                # implicit rules. Following them would build x_shipped,
                # x_shipped_shipped, ... without end.
                if post == "" and (pre == "" or pre.endswith("/")) and not all(
                        (self.maindir / pp).exists() or pp in self.explicit for pp, _ in inst):
                    continue
                yield inst

    def makeable(self, path, depth=0):
        """GNU Make applies a pattern rule only if each prerequisite exists
        or can be made; this approximates that test."""
        if (self.maindir / path).exists() or path in self.explicit or path in self.submakes:
            return True
        if depth > 3:
            return False
        if path.endswith(".o") and any(self.makeable(path[:-2] + e, depth + 1) for e in (".c", ".S")):
            return True
        return any(all(self.makeable(p, depth + 1) for p, _ in inst)
                   for inst in self._pattern_matches(path))

    def prereqs(self, path):
        out = list(self.explicit.get(path, []))
        for inst in self._pattern_matches(path):
            if all(self.makeable(p) for p, _ in inst):
                out.extend(inst)
        return out



def rule_closure(runner, targets, kinds, note=None, roots=()):
    """Objects that Kbuild builds only as prerequisites of selected files
    (and of ``roots``, guarded non-object targets): follow explicit and
    pattern rules, the implicit %.o <- %.c/%.S steps, and sub-makes
    ($(MAKE) $(build)=DIR GOAL) into other directories."""
    from alg import Run
    from kbuild import Kbuild
    solver = zsolver.ZSolver(runner.mysettings)
    index = _RuleIndex(runner.maindir)
    analyzed = {}
    for kb in runner.all_kbuilds:
        index.add_state(kb.makefile, kb.state)
        analyzed[kb.makefile.parent] = True

    def analyze_dir(d):
        if d in analyzed:
            return
        analyzed[d] = True
        mk = Run.get_makefile(d, runner.mysettings)
        if mk is None:
            return
        kb = Kbuild(mk, runner.mysettings)
        kb.preprocess()
        kb.symexe()
        index.add_state(mk, kb.state)

    work = list(targets.items()) + list(roots)
    for goal, sym in getattr(runner.mysettings, "entry_goals", []):
        g = zsolver.T
        if sym:
            zvar, values = solver.get_sort(sym)
            g = zvar != values[""]
        analyze_dir((runner.maindir / goal).parent)
        work.append((goal, g))
    reached = {}
    via = {}  # prerequisite -> the file whose rule needed it
    while work:
        path, cond = work.pop()
        old = reached.get(path)
        if old is not None and (old is zsolver.T or solver.is_valid(z3.Implies(cond, old))):
            continue
        reached[path] = cond if old is None else zsolver.disj(old, cond)
        if path.endswith(".o") and kinds.get(path) is None:
            _add(targets, kinds, path, cond, "rule")
            if note is not None:
                note(path, runner.maindir / via.get(path, "?"), "prerequisite")
        elif path.endswith(".o") and path in targets:
            # Already known (as a rule prerequisite, or as a target or member
            # under another route): building it as a prerequisite is one more
            # route. E.g. "obj-y := $(patsubst %.o,%.pi.o,$(obj-y))" leaves
            # gdt_idt.o only under its obj-m condition, while the rule
            # "%.pi.o: %.o" builds it whenever gdt_idt.pi.o is built.
            targets[path] = zsolver.disj(targets[path], cond)
        for d, goal, c in index.submakes.get(path, []):
            analyze_dir(d)
            if goal:
                work.append((goal, zsolver.conj(cond, c)))
        for p, c in index.prereqs(path):
            via.setdefault(p, path)
            work.append((p, zsolver.conj(cond, c)))
        if path.endswith(".o"):
            for ext in (".c", ".S"):
                work.append((path[:-2] + ext, cond))


class _Symbolic(Exception):
    """A formula mentions a variable that the configuration does not value."""



def _truth(expr, value_of, cache):
    """Evaluate a guard whose atoms are ``CONFIG_X == v``, memoized on AST ids
    so subterms shared across formulas are evaluated once."""
    stack = [(expr, False)]
    while stack:
        e, expanded = stack.pop()
        key = e.get_id()
        if key in cache:
            continue
        if z3.is_true(e) or z3.is_false(e):
            cache[key] = z3.is_true(e)
            continue
        k = e.decl().kind()
        if k == z3.Z3_OP_EQ and z3.is_const(e.arg(0)) and z3.is_const(e.arg(1)):
            a, b = e.arg(0), e.arg(1)
            if a.decl().kind() != z3.Z3_OP_UNINTERPRETED:
                a, b = b, a
            if a.decl().kind() != z3.Z3_OP_UNINTERPRETED:
                raise _Symbolic()
            cache[key] = value_of(str(a)) == str(b)
            continue
        kids = e.children()
        if k not in (z3.Z3_OP_NOT, z3.Z3_OP_AND, z3.Z3_OP_OR):
            raise _Symbolic()
        if not expanded:
            stack.append((e, True))
            stack.extend((c, False) for c in kids if c.get_id() not in cache)
            continue
        v = [cache[c.get_id()] for c in kids]
        cache[key] = (not v[0]) if k == z3.Z3_OP_NOT else (all(v) if k == z3.Z3_OP_AND else any(v))
    return cache[expr.get_id()]



def predicted_objects(runner, targets, config):
    """Paths whose condition is true under the values in ``config``."""
    solver = zsolver.ZSolver(runner.mysettings)
    configured = config_values(config)
    assignments, predicted = {}, set()
    names = {}

    def value_of(sym):
        if sym not in names:
            if not sym.startswith("CONFIG_"):
                raise _Symbolic()
            _, values = solver.get_sort(sym)
            names[sym] = str(values.get(configured.get(sym, ""), values[""]))
        return names[sym]

    cache = {}
    for target, cond in targets.items():
        if cond is True or cond is zsolver.T:
            predicted.add(target)
            continue
        if not isinstance(cond, z3.ExprRef):
            continue
        try:
            if _truth(cond, value_of, cache):
                predicted.add(target)
            continue
        except _Symbolic:
            pass
        # Fallback for formulas over other variables: substitute and simplify.
        variables = get_vars(cond)
        for v in variables:
            sym = str(v)
            if sym.startswith("CONFIG_") and v not in assignments:
                zvar, values = solver.get_sort(sym)
                assignments[zvar] = values.get(configured.get(sym, ""), values[""])
        subs = [(v, assignments[v]) for v in variables if v in assignments]
        result = zsolver.simplify(z3.substitute(cond, subs))
        if z3.is_true(result) or str(result) == "y":
            predicted.add(target)
    return predicted


