import random
import os

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import pandas as pd

from scenario import helper

# the Linux targets of RQ3
TARGETS = ['linux-i386', 'linux-x86_64', 'linux-arm64', 'linux-arm']
TOOLS = ['tool', 'kmax']
# the measures of each repair, as (CSV column, panel title)
MEASURES = [
    ('changed', 'options changed after olddefconfig'),
    ('seconds', 'repair time (s)'),
]


def _load(args):
    # {(target, tool): rows of rq3_<target>_<tool>.csv}, for the runs that exist
    runs = {}
    for target in TARGETS:
        for tool in TOOLS:
            csv_path = os.path.join(args.csv_dir, f'rq3_{target}_{tool}.csv')
            if os.path.isfile(csv_path):
                runs[target, tool] = pd.read_csv(csv_path)
                print(f'[load] {csv_path}')
    return runs


def _summary(runs, out):
    # one row per target and tool: the repairs that produced a configuration, those after
    # which the object's condition still holds by each tool's conditions, and the medians
    # of the measures over the repairs that produced a configuration
    rows = []
    for (target, tool), df in runs.items():
        ok = df[df['status'] == 'ok']
        rows.append({'system': helper.plot.SYSTEM[target], 'tool': helper.plot.LABEL[tool],
                     'repairs': len(df), 'ok': len(ok),
                     'tool_holds': int(ok['tool_holds'].sum()),
                     'kmax_holds': int(ok['kmax_holds'].sum()),
                     'proposed': ok['proposed'].median(), 'changed': ok['changed'].median(),
                     'seconds': ok['seconds'].median()})
    summary = pd.DataFrame(rows)
    summary.to_csv(out, index=False)
    print(summary.to_string(index=False))
    print(f'[save] {out}')


def _plot(runs, out):
    # one panel per measure, one marker per repair that produced a configuration; x is
    # the target and the tools sit side by side, spread a little so equal values stay visible
    systems = list(dict.fromkeys(target for target, _ in runs))
    jitter = random.Random(0)
    fig, axes = plt.subplots(1, len(MEASURES), figsize=helper.plot.figsize(0.98 * helper.plot.TEXT_PT, 0.3))
    for ax, (column, title) in zip(axes, MEASURES):
        for (target, tool), df in runs.items():
            ok = df[df['status'] == 'ok']
            x = systems.index(target) + (-0.17 if tool == 'tool' else 0.17)
            xs = [x + jitter.uniform(-0.07, 0.07) for _ in range(len(ok))]
            ax.scatter(xs, ok[column], s=12, marker=helper.plot.MARKER[tool],
                       color=helper.plot.SERIES[tool], linewidth=1, zorder=2,
                       label=helper.plot.LABEL[tool])
        ax.set_title(title, fontsize=helper.plot.FONT_PT)
        ax.set_xticks(range(len(systems)), [helper.plot.SYSTEM[s] for s in systems])
        ax.set_xlim(-0.5, len(systems) - 0.5)
        ax.grid(axis='x', visible=False)
    handles, labels = axes[0].get_legend_handles_labels()
    unique = dict(zip(labels, handles))
    axes[-1].legend(unique.values(), unique.keys(), loc='upper left')
    fig.tight_layout(pad=0.15)
    fig.savefig(out)
    plt.close(fig)
    print(f'[save] {out}')


def main():
    args = helper.args.parse_args()
    runs = _load(args)
    helper.plot.apply()
    _summary(runs, os.path.join(args.csv_dir, 'rq3_summary.csv'))
    _plot(runs, os.path.join(args.figure_dir, 'rq3.pdf'))


if __name__ == '__main__':
    main()
