import os

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import pandas as pd

from scenario import helper

# marker per tool, so overlapping points of the two tools stay visible
MARKER = {'tool': 'o', 'kmax': 'x'}


def _save(fig, out):
    fig.tight_layout(pad=0.15)
    fig.savefig(out)
    plt.close(fig)
    print(f'[save] {out}')


def _plot_agreement(runs, out):
    df = pd.concat(runs.values())
    fig, ax = plt.subplots(figsize=helper.plot.figsize(0.48 * helper.plot.TEXT_PT, 1.0))
    # one marker per configuration and tool; markers on the dashed diagonal are exact agreement
    low = 0.95 * min(df['observed'].min(), df['predicted'].min())
    high = 1.05 * max(df['observed'].max(), df['predicted'].max())
    ax.plot([low, high], [low, high], linestyle='--', linewidth=1,
            color=helper.plot.MUTED, zorder=1)
    summary = []
    for tool, run in runs.items():
        ax.scatter(run['observed'], run['predicted'], s=24, marker=MARKER[tool],
                   color=helper.plot.SERIES[tool], linewidth=1, zorder=2,
                   label=helper.plot.LABEL[tool])
        summary.append(f'{helper.plot.LABEL[tool]}: precision '
                       f'{run["tp"].sum() / run["predicted"].sum():.3f}, overlap '
                       f'{run["tp"].sum() / run["observed"].sum():.3f}')
    ax.set_xlim(low, high)
    ax.set_ylim(low, high)
    ax.set_aspect('equal')
    ax.set_xlabel('compiled objects')
    ax.set_ylabel('predicted objects')
    # white box, so the diagonal passes behind the text
    n = len(df) // len(runs)
    ax.text(0.04, 0.96, f'{n} configuration{"s" * (n > 1)}\n' + '\n'.join(summary),
            transform=ax.transAxes, va='top', zorder=3,
            bbox={'facecolor': 'white', 'edgecolor': 'none', 'pad': 1.5})
    ax.legend(loc='lower right')
    _save(fig, out)


def _plot_time(runs, out):
    # one bar per tool: the wall-clock time of its whole-tree analysis
    tools = list(runs)
    seconds = [runs[tool]['analyze_seconds'].iloc[0] for tool in tools]
    fig, ax = plt.subplots(figsize=helper.plot.figsize(0.48 * helper.plot.TEXT_PT, 0.35))
    ax.barh(range(len(tools)), seconds, height=0.5,
            color=[helper.plot.SERIES[tool] for tool in tools])
    for y, s in enumerate(seconds):
        ax.text(s, y, f' {s:.1f} s', va='center')
    ax.set_yticks(range(len(tools)), [helper.plot.LABEL[tool] for tool in tools])
    ax.invert_yaxis()
    ax.set_xlim(0, 1.25 * max(seconds))
    ax.set_xlabel('analysis time (s)')
    ax.grid(axis='y', visible=False)
    _save(fig, out)


def main():
    args = helper.args.parse_args()
    runs = {}
    for tool in helper.plot.SERIES:
        csv_path = os.path.join(args.csv_dir, f'rq1_{args.target}_{tool}.csv')
        if os.path.isfile(csv_path):
            runs[tool] = pd.read_csv(csv_path)
            print(f'[load] {csv_path}')

    helper.plot.apply()
    _plot_agreement(runs, os.path.join(args.figure_dir, f'rq1_{args.target}.pdf'))
    _plot_time(runs, os.path.join(args.figure_dir, f'rq1_time_{args.target}.pdf'))


if __name__ == '__main__':
    main()
