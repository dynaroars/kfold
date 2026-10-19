import os

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import pandas as pd

from scenario import helper

# marker per tool, so overlapping points of the two tools stay visible
MARKER = {'tool': 'o', 'kmax': 'x'}


def main():
    args = helper.args.parse_args()
    runs = {}
    for tool in helper.plot.SERIES:
        csv_path = os.path.join(args.csv_dir, f'rq1_{args.target}_{tool}.csv')
        if os.path.isfile(csv_path):
            runs[tool] = pd.read_csv(csv_path)
            print(f'[load] {csv_path}')
    df = pd.concat(runs.values())

    helper.plot.apply()
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
    ax.text(0.04, 0.96, f'{len(df) // len(runs)} configurations\n' + '\n'.join(summary),
            transform=ax.transAxes, va='top')
    ax.legend(loc='lower right')
    fig.tight_layout(pad=0.15)
    out = os.path.join(args.figure_dir, f'rq1_{args.target}.pdf')
    fig.savefig(out)
    plt.close(fig)
    print(f'[save] {out}')


if __name__ == '__main__':
    main()
