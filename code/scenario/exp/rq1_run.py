import glob
import time
import os

from tool.evaluate import read_config, evaluate
from tool.analyze import analyze
from scenario import helper
from tool.save import save


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
    conditions = analyze(os.path.join(root, 'src'))
    print(f'[rq1.run] target={args.target} analyzed {len(conditions)} objects '
          f'in {time.perf_counter() - start:.2f}s')
    smt2_path = os.path.join(args.analysis_dir, f'{args.target}.smt2')
    save(conditions, smt2_path)
    print(f'[save] {smt2_path}')

    csv_path = os.path.join(args.csv_dir, f'rq1_{args.target}.csv')
    pbar = helper.progress_bar.create(
        total=args.n_build,
        unit='config',
        desc=f'rq1.run.{args.target}',
        csv_path=csv_path,
    )
    for i in range(args.n_build):
        tree = os.path.join(root, str(i))
        on = read_config(os.path.join(tree, '.config'))
        predicted = evaluate(conditions, on)
        observed = _observed(tree)
        tp = len(predicted & observed)
        pbar.step(
            n_on=len(on),
            predicted=len(predicted),
            observed=len(observed),
            tp=tp,
            fp=len(predicted - observed),
            fn=len(observed - predicted),
            precision=tp / len(predicted),
            recall=tp / len(observed),
        )
    pbar.to_csv()
    print(f'[save] {csv_path}')


if __name__ == '__main__':
    main()
