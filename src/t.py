import subprocess as sp
import random
import z3


def vwrite(filename, contents, mode='w'):
    with open(filename, mode) as fh:
        fh.write(contents)


def iread(filename):
    """ return a generator """
    with open(filename, 'r') as fh:
        for line in fh:
            yield line


def vcmd(cmd, inp=None, shell=True):
    proc = sp.Popen(cmd, shell=shell, stdin=sp.PIPE,
                    stdout=sp.PIPE, stderr=sp.PIPE)
    return proc.communicate(input=inp)


solver = z3.Solver()
x = z3.Int('x')
f = x > 0

solver.add(f)

filename = '/var/tmp/t.smt2'

myseed = random.randint(0, 1000000)
smt2_str = [
    '(set-option :smt.arith.random_initial_value true)',
    solver.to_smt2().replace('(check-sat)', ''),
    '(check-sat-using (using-params smt :random-seed {}))'.format(myseed),
    '(get-model)']
smt2_str = '\n'.join(smt2_str)

print smt2_str
vwrite(filename, smt2_str)

cmd = 'z3 {}'.format(filename)
print cmd
msg1, msg2 = vcmd(cmd)
assert not msg2
print msg1  # contain the model value


# parse_smt2_string doesn't seem to work
myexpr = z3.parse_smt2_string('(define-fun x () Int 310)')
print(myexpr)
