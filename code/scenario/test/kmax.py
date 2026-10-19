import os

from scenario.helper.args import parse_args
from scenario.helper import kmax, target
from tool.save import save


def main():
    args = parse_args()
    path = os.path.join(args.target_dir, args.target, 'src')
    conditions = kmax.analyze(path, target.VARIABLES[args.target], target.KMAXALL[args.target])
    out_dir = os.path.join(args.analysis_dir, 'kmax')
    os.makedirs(out_dir, exist_ok=True)
    save(conditions, os.path.join(out_dir, f'{args.target}.smt2'))


if __name__ == '__main__':
    main()
