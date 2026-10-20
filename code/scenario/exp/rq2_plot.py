import os

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import pandas as pd

from scenario import helper

# the source characteristics compared between the tool and Kmax, as (--target, sizes,
# x-axis label)
STRUCTURES = [
    ('length', range(20, 201, 20), 'conditional blocks'),
    ('nested', range(2, 21, 2), 'nesting depth of 100 blocks'),
    ('value', range(20, 201, 20), 'value-choosing blocks'),
    ('directory', range(20, 201, 20), 'conditional subdirectories'),
    ('depth', range(20, 201, 20), 'directory depth'),
    ('composite', range(20, 201, 20), 'composite objects'),
    ('exported', range(20, 201, 20), 'blocks naming $(BITS)'),
    ('computed', range(20, 201, 20), 'conditional lists'),
]
TOOLS = ['tool', 'kmax']
# the measures of each run, as (CSV column, y-axis label, file name suffix)
MEASURES = [
    ('seconds', 'time (s)', 'time'),
    ('memory_mb', 'memory (MB)', 'memory'),
]


def _load(args, structure, sizes):
    # {tool: rows of rq2_<structure>_<tool>.csv with n_ifeq in sizes}, for the tools that
    # have such rows
    runs = {}
    for tool in TOOLS:
        csv_path = os.path.join(args.csv_dir, f'rq2_{structure}_{tool}.csv')
        if os.path.isfile(csv_path):
            df = pd.read_csv(csv_path)
            df = df[df['n_ifeq'].isin(sizes)]
            if len(df):
                runs[tool] = df
                print(f'[load] {csv_path}')
    return runs


def _plot(runs, column, ylabel, xlabel, out):
    # one line per tool over the runs that finished, a third of the text wide for a
    # figure of the six characteristics, on a linear scale so where the tools cross shows;
    # a run that timed out or ran out of memory gets a marker at the top above its n_ifeq
    fig, ax = plt.subplots(figsize=helper.plot.figsize(0.32 * helper.plot.TEXT_PT, 0.7))
    for tool, df in runs.items():
        ok = df[df['status'] == 'ok']
        ax.plot(ok['n_ifeq'], ok[column], color=helper.plot.SERIES[tool],
                marker=helper.plot.MARKER[tool], markersize=3, linewidth=1.2,
                label=helper.plot.LABEL[tool])
    # the axes fit the points, with headroom above the highest for those markers
    bottom, top = ax.get_ylim()
    top += 0.05 * (top - bottom)
    for tool, df in runs.items():
        failed = df[df['status'] != 'ok']
        ax.scatter(failed['n_ifeq'], [top] * len(failed), color=helper.plot.SERIES[tool],
                   marker=helper.plot.MARKER[tool], s=18, clip_on=False, zorder=3)
    ax.set_ylim(bottom, top)
    ax.set_xlabel(xlabel)
    ax.set_ylabel(ylabel)
    ax.grid(axis='x', visible=False)
    _save(fig, out)
    return ax.get_legend_handles_labels()


def _legend(handles, labels, out):
    # the legend the figures share, one row as wide as the text
    fig, ax = plt.subplots(figsize=(helper.plot.TEXT_PT / 72.27, 0.2))
    ax.axis('off')
    ax.legend(handles, labels, loc='center', ncol=len(labels), frameon=False,
              handlelength=1.8, columnspacing=2.0)
    _save(fig, out)


def _save(fig, out):
    fig.tight_layout(pad=0.15)
    fig.savefig(out)
    plt.close(fig)
    print(f'[save] {out}')


def _accuracy(structure, tool, df):
    # one summary row at the largest size: precision is the share of reported objects
    # whose condition is equivalent to the truth in every configuration, recall the share
    # of built objects with such a condition; constant tells whether both are the same at
    # every size
    ok = df[df['status'] == 'ok']
    precision = ok['equivalent'] / ok['objects']
    recall = ok['equivalent'] / ok['expected']
    last = ok.iloc[-1]
    return {'structure': structure, 'tool': helper.plot.LABEL[tool], 'n_ifeq': last['n_ifeq'],
            'objects': last['objects'], 'expected': last['expected'], 'missing': last['missing'],
            'extra': last['extra'], 'equivalent': last['equivalent'],
            'different': last['different'], 'precision': precision.iloc[-1],
            'recall': recall.iloc[-1],
            'constant': precision.nunique() == 1 and recall.nunique() == 1}


def main():
    args = helper.args.parse_args()
    helper.plot.apply()
    rows = []
    for structure, sizes, xlabel in STRUCTURES:
        runs = _load(args, structure, sizes)
        if not runs:
            continue
        for column, ylabel, suffix in MEASURES:
            handles, labels = _plot(runs, column, ylabel, xlabel,
                                    os.path.join(args.figure_dir, f'rq2_{structure}_{suffix}.pdf'))
        # runs made before the comparison with the truth have no equivalent column
        rows += [_accuracy(structure, tool, df) for tool, df in runs.items() if 'equivalent' in df]
    _legend(handles, labels, os.path.join(args.figure_dir, 'rq2_legend.pdf'))
    summary = pd.DataFrame(rows)
    out = os.path.join(args.csv_dir, 'rq2_summary.csv')
    summary.to_csv(out, index=False)
    print(summary.to_string(index=False))
    print(f'[save] {out}')


if __name__ == '__main__':
    main()
