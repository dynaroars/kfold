import os

from scenario.exp.rq2_run import run
from scenario.prepare import nested
from scenario import helper

# the objects of the tree of n, per structure (--target)
EXPECTED = {
    'nested': lambda n: nested.BLOCKS * n,
    'value': lambda n: 2 * n,
    'directory': lambda n: n,
}


def main():
    args = helper.args.parse_args()
    # the trees <target_dir>/<structure>-<n> of --target, measured as in RQ2
    run(args, f'{args.target}-', os.path.join(args.csv_dir, f'rq4_{args.target}_{args.tool}.csv'),
        EXPECTED[args.target])


if __name__ == '__main__':
    main()
