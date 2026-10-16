# the toy program under test
def f(x, y):
    if x > 10:
        if y == x - 5:
            return 'bug'
        return 'a'
    return 'b'

# symbolic executor

from z3 import Int, Solver, And, Not, sat

x = Int('x')
y = Int('y')

def run(pc): # pc: path condition
    for c1, then1 in ((x > 10, True), (Not(x > 10), False)):
        pc1 = pc + [c1]
        if not then1:
            yield pc1, 'b'
            continue
        for c2, then2 in ((y == x - 5), True), (Not(y == x - 5), False):
            pc2 = pc1 + [c2]
            if then2:
                yield pc2, 'bug'
            else:
                yield pc2, 'a'

for pc, result in run([]):
    s = Solver()
    s.add(And(*pc))
    if s.check() == sat:
        m = s.model()
        print(f"{result:3} path={pc}  ->  x={m[x]}, y={m[y]}")
    else:
        print(f"{result:3} path={pc}  ->  infeasible")
