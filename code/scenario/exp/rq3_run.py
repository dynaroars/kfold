import subprocess
import random
import shutil
import json
import time
import os

import pandas as pd

from scenario.prepare.helper import read_config as read_values, write_config, changed
from scenario.exp.rq1_run import _in_scope, _observed
from tool.evaluate import read_config, evaluate
from scenario.helper import target, kmax
from tool.repair import repair
from scenario import helper
from tool.load import load

# objects to add to each build, drawn from those the build did not compile
OBJECTS = 10


def _save(pbar, done, visited, csv_path):
    # the rows so far and the kept rows of the earlier run not reached yet, so an
    # interrupted run loses neither
    rows = pd.DataFrame(pbar.csv_data)
    rest = pd.DataFrame([row for key, row in done.items() if key not in visited])
    pd.concat([rows, rest], ignore_index=True).to_csv(csv_path, index=None)


def _klocalizer(src, arch, env, config, obj, formulas, out, timeout):
    # Kmax's repair, krepair, as klocalizer --repair; its formulas are generated on the
    # first call for the source tree and cached in `formulas`
    command = ['klocalizer', '-a', arch, '--repair', config, '--include', obj,
               '--formulas', formulas, '--disable-downloading-formulas', '-o', out]
    return subprocess.run(command, cwd=src, env=env, capture_output=True, timeout=timeout)


def main():
    args = helper.args.parse_args()
    root = os.path.join(args.target_dir, args.target)
    src = os.path.abspath(os.path.join(root, 'src'))
    arch = target.VARIABLES[args.target]['ARCH']
    cross = {'CROSS_COMPILE': target.CROSS_COMPILE[args.target]} if args.target in target.CROSS_COMPILE else {}
    # klocalizer runs make in the source tree to read its version; under an outer make,
    # MAKELEVEL makes that make print "Entering directory" before it, which klocalizer
    # cannot parse, so it runs with the environment of a shell
    env = {k: v for k, v in os.environ.items() if k not in ('MAKEFLAGS', 'MAKELEVEL', 'MFLAGS')}
    env.update(ARCH=arch, **cross)
    make = ['make', '-C', src, f'ARCH={arch}'] + [f'{k}={v}' for k, v in cross.items()]

    # the build conditions of both tools from RQ1; the objects drawn are in both, so the
    # two repairs are asked for the same objects
    conditions = {tool: {obj: condition for obj, condition
                         in load(os.path.join(args.analysis_dir, tool, f'{args.target}.smt2')).items()
                         if _in_scope(obj)}
                  for tool in ['tool', 'kmax']}
    universe = conditions['tool'].keys() & conditions['kmax'].keys()
    bits = {target.KMAX_BITS[args.target]} if args.target in target.KMAX_BITS else set()

    # the build trees of RQ1, the first --n_build of each base
    trees = sorted((d for d in os.listdir(root)
                    if os.path.isfile(os.path.join(root, d, '.config'))
                    and int(d.rpartition('-')[2]) < args.n_build),
                   key=lambda d: (d.rpartition('-')[0], int(d.rpartition('-')[2])))
    work = os.path.abspath(os.path.join(args.analysis_dir, args.tool, f'{args.target}.rq3'))
    scratch = os.path.join(work, 'olddefconfig')
    os.makedirs(scratch, exist_ok=True)
    formulas = os.path.abspath(os.path.join(args.analysis_dir, 'kmax', f'{args.target}.klocalizer'))
    # klocalizer runs from a copy of the kmax package that Python 3.10 can import
    if args.tool == 'kmax':
        package = kmax.patched_package(os.path.join(work, 'package'))
        env['PYTHONPATH'] = os.pathsep.join([package, env.get('PYTHONPATH', '')]).rstrip(os.pathsep)
    csv_path = os.path.join(args.csv_dir, f'rq3_{args.target}_{args.tool}.csv')
    # the repairs of an earlier run that did not fail are kept unless --clear asks to redo
    # them, so a rerun redoes only those that failed
    done = {}
    visited = set()
    if os.path.isfile(csv_path) and not args.clear:
        earlier = pd.read_csv(csv_path)
        done = {(row['build'], row['object']): row for row in
                json.loads(earlier[earlier['status'] != 'error'].to_json(orient='records'))}
    pbar = helper.progress_bar.create(total=len(trees) * OBJECTS, unit='repair',
                                      desc=f'rq3.run.{args.target}.{args.tool}', csv_path=csv_path)

    for t, name in enumerate(trees):
        config = os.path.abspath(os.path.join(root, name, '.config'))
        base = read_values(config)
        candidates = sorted(universe - _observed(os.path.join(root, name)))
        objects = random.Random(0).sample(candidates, OBJECTS)
        # klocalizer generates its formulas on its first call, which is not timed
        if args.tool == 'kmax' and t == 0:
            start = time.perf_counter()
            _klocalizer(src, arch, env, config, objects[0], formulas,
                        os.path.join(work, 'warmup.config'), None)
            print(f'[rq3.run] klocalizer formulas generated in {time.perf_counter() - start:.1f}s')
        for i, obj in enumerate(objects):
            if (name, obj) in done:
                pbar.step(**{k: v for k, v in done[name, obj].items() if k != 'repair'})
                visited.add((name, obj))
                _save(pbar, done, visited, csv_path)
                continue
            out = os.path.join(work, f'{name}-{i}.config')
            status = 'ok'
            # the tool's time is the repair alone, after the conditions are loaded; Kmax's
            # is a klocalizer call, which also starts Python and reads its cached formulas
            start = time.perf_counter()
            if args.tool == 'tool':
                flips = repair(conditions['tool'], read_config(config), obj)
                seconds = time.perf_counter() - start
                if flips is None:
                    status = 'unsat'
                else:
                    values = dict(base)
                    values.update({option[len('CONFIG_'):]: 'y' if value else 'n'
                                   for option, value in flips.items()})
                    write_config(out, values)
            else:
                try:
                    result = _klocalizer(src, arch, env, config, obj, formulas, out, args.timeout)
                    # klocalizer's answer when no configuration builds the object
                    if b'No satisfying configuration found' in result.stdout + result.stderr:
                        status = 'unsat'
                    elif result.returncode != 0 or not os.path.isfile(out):
                        status = 'error'
                        # klocalizer's messages, to find why it failed
                        with open(os.path.join(work, f'{name}-{i}.log'), 'wb') as f:
                            f.write(result.stdout + result.stderr)
                except subprocess.TimeoutExpired:
                    status = 'timeout'
                seconds = time.perf_counter() - start
            row = {'build': name, 'object': obj, 'status': status, 'seconds': seconds,
                   'proposed': None, 'changed': None, 'tool_holds': None, 'kmax_holds': None}
            if status == 'ok':
                # olddefconfig applies the Kconfig rules the repaired configuration may
                # break; the changes count against the base after it, and the object counts
                # as added when its condition still holds, by each tool's conditions
                shutil.copy(out, os.path.join(scratch, '.config'))
                subprocess.run([*make, f'O={scratch}', 'olddefconfig'], check=True, capture_output=True)
                final = os.path.join(scratch, '.config')
                on = read_config(final)
                row.update(proposed=changed(base, read_values(out)),
                           changed=changed(base, read_values(final)),
                           tool_holds=obj in evaluate({obj: conditions['tool'][obj]}, on),
                           kmax_holds=obj in evaluate({obj: conditions['kmax'][obj]}, on | bits))
            pbar.step(**row)
            visited.add((name, obj))
            _save(pbar, done, visited, csv_path)
    pbar.to_csv()
    print(f'[save] {csv_path}')


if __name__ == '__main__':
    main()
