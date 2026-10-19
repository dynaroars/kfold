import json
import time
import os

from tool.evaluate import read_config, evaluate
from scenario.helper import kmax, target
from tool.analyze import analyze
from scenario import helper
from tool.load import load
from tool.save import save


def _analyze(args, path):
    # --tool selects the analyzer whose build conditions are evaluated
    name = args.target
    progress = helper.progress_bar.create_growing('dir', f'rq1.analyze.{name}.{args.tool}')
    if args.tool == 'kmax':
        if name not in target.KMAXALL:
            raise SystemExit(f'Kmax analyzes Kbuild trees, and {name} has no kmaxall '
                             f'arguments in scenario/helper/target.py')
        log_path = os.path.join(args.analysis_dir, args.tool, f'{name}.log')
        with open(log_path, 'w') as log:
            conditions = kmax.analyze(path, target.VARIABLES[name], target.KMAXALL[name],
                                      progress, log)
        print(f'[save] {log_path}')
        return conditions
    return analyze(path, target.VARIABLES[name], progress)


def _in_scope(obj):
    # the objects compared: built-in.o files are link products, and scripts/ holds
    # the host tools that run kconfig, built before any configuration exists
    return obj.endswith('.o') and not obj.endswith('built-in.o') and not obj.startswith('scripts/')


def _observed(tree):
    # objects the build compiled; os.walk leaves symlinks alone, so the `source`
    # link of a Linux O= build tree is not followed
    objects = set()
    for directory, _, files in os.walk(tree):
        for name in files:
            obj = os.path.relpath(os.path.join(directory, name), tree)
            if _in_scope(obj):
                objects.add(obj)
    return objects


def main():
    args = helper.args.parse_args()
    root = os.path.join(args.target_dir, args.target)
    # the directory of each tree that holds the Kbuild tree, such as xen/ in a Xen release
    subdir = target.SUBDIR.get(args.target, '')

    # the analysis is saved as <target>.smt2 with its time in <target>.json, and reused
    # unless --clear asks for a new one; a saved analysis without its .json (written
    # before timing was recorded) is reused with an unknown time
    smt2_path = os.path.join(args.analysis_dir, args.tool, f'{args.target}.smt2')
    json_path = os.path.join(args.analysis_dir, args.tool, f'{args.target}.json')
    if os.path.isfile(smt2_path) and not args.clear:
        conditions = load(smt2_path)
        analyze_seconds = float('nan')
        if os.path.isfile(json_path):
            with open(json_path) as f:
                analyze_seconds = json.load(f)['analyze_seconds']
        print(f'[load] {smt2_path} ({len(conditions)} objects, analyzed in {analyze_seconds:.2f}s); '
              f'--clear reruns the analysis')
    else:
        start = time.perf_counter()
        conditions = _analyze(args, os.path.join(root, 'src', subdir))
        analyze_seconds = time.perf_counter() - start
        print(f'[rq1.run] target={args.target} tool={args.tool} analyzed {len(conditions)} objects '
              f'in {analyze_seconds:.2f}s')
        save(conditions, smt2_path)
        with open(json_path, 'w') as f:
            json.dump({'analyze_seconds': analyze_seconds}, f)
        print(f'[save] {smt2_path}')
        print(f'[save] {json_path}')

    conditions = {obj: condition for obj, condition in conditions.items() if _in_scope(obj)}

    # the build trees prepare made, each with its .config: <i>/, or <base>-<i>/ for a
    # target with several base configurations; the first --n_build of each base, sorted
    # by base, then i
    trees = sorted((d for d in os.listdir(root)
                    if os.path.isfile(os.path.join(root, d, subdir, '.config'))
                    and int(d.rpartition('-')[2]) < args.n_build),
                   key=lambda d: (d.rpartition('-')[0], int(d.rpartition('-')[2])))
    csv_path = os.path.join(args.csv_dir, f'rq1_{args.target}_{args.tool}.csv')
    pbar = helper.progress_bar.create(
        total=len(trees),
        unit='config',
        desc=f'rq1.run.{args.target}.{args.tool}',
        csv_path=csv_path,
    )
    # the objects behind fp, fn_u, and out of every configuration, to count distinct
    # objects across configurations and to group the errors by cause
    errors = {}
    for name in trees:
        tree = os.path.join(root, name, subdir)
        on = read_config(os.path.join(tree, '.config'))
        predicted = evaluate(conditions, on)
        observed = _observed(tree)
        tp = len(predicted & observed)
        # metrics of the paper's setup: fn_u are extracted objects the analysis missed,
        # out are compiled objects outside the extracted universe; analyze_seconds is
        # the one whole-tree analysis, repeated on every row
        errors[name] = {
            'fp': sorted(predicted - observed),
            'fn_u': sorted((observed & conditions.keys()) - predicted),
            'out': sorted(observed - conditions.keys()),
        }
        pbar.step(
            build=name,
            analyze_seconds=analyze_seconds,
            universe=len(conditions),
            n_on=len(on),
            predicted=len(predicted),
            observed=len(observed),
            tp=tp,
            fp=len(errors[name]['fp']),
            fn_u=len(errors[name]['fn_u']),
            out=len(errors[name]['out']),
            precision=tp / len(predicted),
            overlap=tp / len(observed),
        )
    pbar.to_csv()
    print(f'[save] {csv_path}')
    errors_path = os.path.join(args.analysis_dir, args.tool, f'{args.target}.rq1.json')
    with open(errors_path, 'w') as f:
        json.dump(errors, f, indent=1)
    print(f'[save] {errors_path}')


if __name__ == '__main__':
    main()
