import os

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import pandas as pd

from scenario import helper

# the measures of each run, as (CSV column, y-axis label, y scale, file name suffix); time
# spans orders of magnitude, and memory varies a few MB above the interpreter's own
MEASURES = [
    ('seconds', 'analysis time (s)', 'log', 'time'),
    ('memory_mb', 'peak memory (MB)', 'linear', 'memory'),
]
# the benchmark of this figure: Makefiles of 1 to 20 conditional blocks, for every tool,
# path forking included
SIZES = range(1, 21)


def load(args, structure, sizes, tools):
    # {tool: rows of rq2_<structure>_<tool>.csv with n_ifeq in sizes}, for the tools that
    # have such rows
    runs = {}
    for tool in tools:
        csv_path = os.path.join(args.csv_dir, f'rq2_{structure}_{tool}.csv')
        if os.path.isfile(csv_path):
            df = pd.read_csv(csv_path)
            df = df[df['n_ifeq'].isin(sizes)]
            if len(df):
                runs[tool] = df
                print(f'[load] {csv_path}')
    return runs


def plot(runs, column, ylabel, scale, out, xlabel='conditional blocks'):
    # one line per tool over the runs that finished; a run that timed out or ran out of
    # memory gets a marker at the top of the axes above its n_ifeq
    fig, ax = plt.subplots(figsize=helper.plot.figsize(0.48 * helper.plot.TEXT_PT, 0.7))
    ax.set_yscale(scale)
    for tool, df in runs.items():
        ok = df[df['status'] == 'ok']
        ax.plot(ok['n_ifeq'], ok[column], color=helper.plot.SERIES[tool],
                marker=helper.plot.MARKER[tool], markersize=3, linewidth=1.2,
                label=helper.plot.LABEL[tool])
    # the axes fit the points, with headroom above the highest, where the markers of
    # failed runs go
    bottom, top = ax.get_ylim()
    top = top * 2 if scale == 'log' else top + 0.05 * (top - bottom)
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


def _save(fig, out):
    fig.tight_layout(pad=0.15)
    fig.savefig(out)
    plt.close(fig)
    print(f'[save] {out}')


def draw(args, runs, prefix, xlabel='conditional blocks'):
    # <prefix>_time.pdf, <prefix>_memory.pdf, and the legend they share, <prefix>_legend.pdf
    helper.plot.apply()
    for column, ylabel, scale, suffix in MEASURES:
        handles, labels = plot(runs, column, ylabel, scale,
                               os.path.join(args.figure_dir, f'{prefix}_{suffix}.pdf'), xlabel)
    legend(handles, labels, os.path.join(args.figure_dir, f'{prefix}_legend.pdf'))


def legend(handles, labels, out):
    # one row as wide as the text
    fig, ax = plt.subplots(figsize=(helper.plot.TEXT_PT / 72.27, 0.2))
    ax.axis('off')
    ax.legend(handles, labels, loc='center', ncol=len(labels), frameon=False,
              handlelength=1.8, columnspacing=2.0)
    _save(fig, out)


def main():
    args = helper.args.parse_args()
    draw(args, load(args, 'length', SIZES, helper.plot.SERIES), 'rq2_forking')


if __name__ == '__main__':
    main()
