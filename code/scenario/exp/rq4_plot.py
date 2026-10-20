import os

import pandas as pd

from scenario.exp.rq2_plot import plot, legend
from scenario import helper

# the structures of RQ4, as (--target, x-axis label); the analysis time of each is one
# figure, on a linear scale so the two tools can be compared at each size
STRUCTURES = [
    ('nested', 'nesting depth of 100 blocks'),
    ('value', 'value-choosing blocks'),
    ('directory', 'conditional subdirectories'),
]
TOOLS = ['tool', 'kmax']


def main():
    args = helper.args.parse_args()
    helper.plot.apply()
    for structure, xlabel in STRUCTURES:
        runs = {}
        for tool in TOOLS:
            csv_path = os.path.join(args.csv_dir, f'rq4_{structure}_{tool}.csv')
            if os.path.isfile(csv_path):
                runs[tool] = pd.read_csv(csv_path)
                print(f'[load] {csv_path}')
        if runs:
            handles, labels = plot(runs, 'seconds', 'analysis time (s)', 'linear',
                                   os.path.join(args.figure_dir, f'rq4_{structure}.pdf'), xlabel)
    legend(handles, labels, os.path.join(args.figure_dir, 'rq4_legend.pdf'))


if __name__ == '__main__':
    main()
