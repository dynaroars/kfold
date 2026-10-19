import os

from scenario.helper.args import parse_args
from scenario.helper import progress_bar, target
from tool.analyze import analyze
from tool.save import save


def main():
    args = parse_args()
    path = os.path.join(args.target_dir, args.target, 'src')
    conditions = analyze(path, target.VARIABLES[args.target],
                         progress_bar.create_growing('dir', f'test.tool.{args.target}'))
    save(conditions, os.path.join(args.analysis_dir, args.tool, f'{args.target}.smt2'))


if __name__ == '__main__':
    main()
