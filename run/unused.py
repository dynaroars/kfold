"""
Not comfortable using this

For this example
myhello := 1                                                                  lib-$(CONFIG_1) += 1
lib-$(CONFIG_2) += 2
lib-$(CONFIG_3) += 3

This version will not merge myhello path into new paths,
instead it just append new paths with myhell path
"""


def _parse(self):
        nameexp = self.stmt.vnameexp
        token = self.stmt.token   # :=
        val = self.stmt.value
        new_paths = self.parse_opt(nameexp, token, val)
        if new_paths:
            return Paths(self.paths + new_paths)
        else:
            return super().parse()

    def parse_opt(self, nameexp, token, val):
        """
        Exploit specific structure to obtain new paths
        """
        if token != "+=":
            return

        myeval = EvalSimple(self.solver.__config_vars__, self.solver)
        try:
            names = myeval.do_expansion(nameexp)
            vals = myeval.do_val(val)
        except NotSimpleAssignmentException as ex:
            return

        state_vals = frozenset(
            v for path in self.paths for v in path.state_vals)

        if any(v_ in state_vals for v, _ in vals for v_ in v.split()):
            return

        src_dir = self.paths[0].states['src']
        new_paths = Paths()

        for (name, ncond), (val, vcond) in itertools.product(*[names, vals]):
            assert vcond == zsolver.T, vcond
            pathcond = z3.Or([path.cond for path in self.paths])
            pathcond = zsolver.simplify(pathcond)
            if not pathcond == zsolver.T:
                return

            new_cond = ncond
            if self.solver.is_sat(new_cond):
                new_path = Path.get_default(new_cond, src_dir)
                new_path.set_var(name, token, val)
                new_paths.append(new_path)

        if settings.detail:
            print('--- ORIG --- ({} paths)'.format(len(self.paths)))
            print(self.paths)
            print('--- NEW --- ({} paths)'.format(len(new_paths)))
            print(new_paths)

        return new_paths


class NotSimpleAssignmentException(Exception):
    pass


class EvalSimple(Eval):
    def do_fun_VariableRef(self, fun):
        assert isinstance(fun, functions.VariableRef), fun
        names = self.do_expansion(fun.vname)

        rs = []
        for name, _ in names:
            if (name not in self.states and
                    name.startswith(settings.sym_prefix)):
                vals = self.do_config_var(name)
                rs.extend(vals)
            else:
                raise NotSimpleAssignmentException(fun)
        return rs


    
