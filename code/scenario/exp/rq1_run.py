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
        log_path = os.path.join(args.analysis_dir, args.tool, f'{name}.log')
        with open(log_path, 'w') as log:
            conditions = kmax.analyze(path, target.VARIABLES[name], target.KMAXALL[name],
                                      progress, log)
        print(f'[save] {log_path}')
        return conditions
    return analyze(path, target.VARIABLES[name], progress)


def _observed(tree):
    # objects the build compiled; built-in.o files are link products and
    # scripts/ holds the host tools that run kconfig. os.walk leaves symlinks
    # alone, so the `source` link of a Linux O= build tree is not followed
    objects = set()
    for directory, _, files in os.walk(tree):
        for name in files:
            obj = os.path.relpath(os.path.join(directory, name), tree)
            if obj.endswith('.o') and not obj.endswith('built-in.o') and not obj.startswith('scripts/'):
                objects.add(obj)
    return objects


def main():
    args = helper.args.parse_args()
    root = os.path.join(args.target_dir, args.target)

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
        conditions = _analyze(args, os.path.join(root, 'src'))
        analyze_seconds = time.perf_counter() - start
        print(f'[rq1.run] target={args.target} tool={args.tool} analyzed {len(conditions)} objects '
              f'in {analyze_seconds:.2f}s')
        save(conditions, smt2_path)
        with open(json_path, 'w') as f:
            json.dump({'analyze_seconds': analyze_seconds}, f)
        print(f'[save] {smt2_path}')
        print(f'[save] {json_path}')

    # the build trees prepare made: 0/ ... for random BusyBox configurations, 0/ alone for Linux
    trees = sorted((d for d in os.listdir(root) if d.isdigit()), key=int)
    csv_path = os.path.join(args.csv_dir, f'rq1_{args.target}_{args.tool}.csv')
    pbar = helper.progress_bar.create(
        total=len(trees),
        unit='config',
        desc=f'rq1.run.{args.target}.{args.tool}',
        csv_path=csv_path,
    )
    for name in trees:
        tree = os.path.join(root, name)
        on = read_config(os.path.join(tree, '.config'))
        predicted = evaluate(conditions, on)
        observed = _observed(tree)
        tp = len(predicted & observed)
        # metrics of the paper's setup: fn_u are extracted objects the analysis missed,
        # out are compiled objects outside the extracted universe; analyze_seconds is
        # the one whole-tree analysis, repeated on every row
        pbar.step(
            analyze_seconds=analyze_seconds,
            n_on=len(on),
            predicted=len(predicted),
            observed=len(observed),
            tp=tp,
            fp=len(predicted - observed),
            fn_u=len((observed & conditions.keys()) - predicted),
            out=len(observed - conditions.keys()),
            precision=tp / len(predicted),
            overlap=tp / len(observed),
        )
    pbar.to_csv()
    print(f'[save] {csv_path}')


if __name__ == '__main__':
    main()
