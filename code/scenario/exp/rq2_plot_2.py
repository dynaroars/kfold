import os

from scenario.exp.rq2_plot import load, draw, plot
from scenario import helper

# the source characteristics compared between the tool and Kmax, as (--target, sizes,
# x-axis label); path forking runs on length only, in the figure of rq2_plot
STRUCTURES = [
    ('length', range(20, 201, 20), 'conditional blocks'),
    ('nested', range(2, 21, 2), 'nesting depth of 100 blocks'),
    ('value', range(20, 201, 20), 'value-choosing blocks'),
    ('directory', range(20, 201, 20), 'conditional subdirectories'),
    ('depth', range(20, 201, 20), 'directory depth'),
    ('composite', range(20, 201, 20), 'composite objects'),
]
TOOLS = ['tool', 'kmax']


def main():
    args = helper.args.parse_args()
    for structure, sizes, xlabel in STRUCTURES:
        runs = load(args, structure, sizes, TOOLS)
        if not runs:
            continue
        draw(args, runs, f'rq2_{structure}', xlabel)
        # composite objects test accuracy as well: the objects a tool reports that the
        # tree does not build, such as a composite in place of its members
        if structure == 'composite':
            plot(runs, 'extra', 'objects not built', 'linear',
                 os.path.join(args.figure_dir, 'rq2_composite_extra.pdf'), xlabel)


if __name__ == '__main__':
    main()
