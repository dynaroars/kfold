import os

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import pandas as pd

from scenario import helper


def main():
    args = helper.args.parse_args()
    csv_path = os.path.join(args.csv_dir, f'rq1_{args.target}.csv')
    df = pd.read_csv(csv_path)
    print(f'[load] {csv_path}')

    helper.plot.apply()
    fig, ax = plt.subplots(figsize=helper.plot.figsize(0.48 * helper.plot.TEXT_PT, 1.0))
    # one marker per configuration; markers on the dashed diagonal are exact agreement
    low = 0.95 * min(df['observed'].min(), df['predicted'].min())
    high = 1.05 * max(df['observed'].max(), df['predicted'].max())
    ax.plot([low, high], [low, high], linestyle='--', linewidth=1,
            color=helper.plot.MUTED, zorder=1)
    ax.scatter(df['observed'], df['predicted'], s=24, color=helper.plot.SERIES,
               edgecolor='white', linewidth=0.8, zorder=2)
    ax.set_xlim(low, high)
    ax.set_ylim(low, high)
    ax.set_aspect('equal')
    ax.set_xlabel('compiled objects')
    ax.set_ylabel('predicted objects')
    ax.text(0.04, 0.96,
            f'{len(df)} configurations\n'
            f'precision {df["tp"].sum() / df["predicted"].sum():.3f}\n'
            f'recall {df["tp"].sum() / df["observed"].sum():.3f}',
            transform=ax.transAxes, va='top')
    fig.tight_layout(pad=0.15)
    out = os.path.join(args.figure_dir, f'rq1_{args.target}.pdf')
    fig.savefig(out)
    plt.close(fig)
    print(f'[save] {out}')


if __name__ == '__main__':
    main()
