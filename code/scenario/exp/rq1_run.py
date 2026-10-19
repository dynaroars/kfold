import glob
import time
import os

from tool.evaluate import read_config, evaluate
from scenario.helper import kmax, target
from tool.analyze import analyze
from scenario import helper
from tool.save import save


def _analyze(tool, name, path):
    # --tool selects the analyzer whose build conditions are evaluated
    if tool == 'kmax':
        return kmax.analyze(path, target.VARIABLES[name], target.KMAXALL[name])
    return analyze(path, target.VARIABLES[name])


def _observed(tree):
    # objects the build compiled; built-in.o files are link products and
    # scripts/ holds the host tools that run kconfig
    objects = set()
    for path in glob.glob(os.path.join(tree, '**', '*.o'), recursive=True):
        obj = os.path.relpath(path, tree)
        if not obj.endswith('built-in.o') and not obj.startswith('scripts/'):
            objects.add(obj)
    return objects


def main():
    args = helper.args.parse_args()
    root = os.path.join(args.target_dir, args.target)

    start = time.perf_counter()
    conditions = _analyze(args.tool, args.target, os.path.join(root, 'src'))
    analyze_seconds = time.perf_counter() - start
    print(f'[rq1.run] target={args.target} tool={args.tool} analyzed {len(conditions)} objects '
          f'in {analyze_seconds:.2f}s')
    smt2_path = os.path.join(args.analysis_dir, args.tool, f'{args.target}.smt2')
    save(conditions, smt2_path)
    print(f'[save] {smt2_path}')

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
