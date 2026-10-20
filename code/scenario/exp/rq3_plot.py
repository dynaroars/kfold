import math
import os

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import pandas as pd

from scenario import helper

# the Linux targets of RQ3
TARGETS = ['linux-i386', 'linux-x86_64', 'linux-arm64', 'linux-arm']
TOOLS = ['tool', 'kmax']
# the repairs drawn per build, as in rq3_run
OBJECTS = 10


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
    # which the object's condition still holds by each tool's conditions, those whose
    # object Kbuild compiled or selected in the copy of the build, and the medians
    # of the measures over the repairs that produced a configuration
    rows = []
    for (target, tool), df in runs.items():
        ok = df[df['status'] == 'ok']
        # compile: the object compiled in the copy of the build, or Kbuild selected it and
        # its source failed to compile; runs before the compile check have no such column
        compile = ok['compile'] if 'compile' in ok else pd.Series(dtype=object)
        rows.append({'system': helper.plot.SYSTEM[target], 'tool': helper.plot.LABEL[tool],
                     'repairs': len(df), 'ok': len(ok),
                     'tool_holds': int(ok['tool_holds'].sum()),
                     'kmax_holds': int(ok['kmax_holds'].sum()),
                     'compiled': int((compile == 'compiled').sum()),
                     'selected': int(compile.isin(['compiled', 'compile error']).sum()),
                     'proposed': ok['proposed'].median(), 'changed': ok['changed'].median(),
                     'seconds': ok['seconds'].median()})
    summary = pd.DataFrame(rows)
    summary.to_csv(out, index=False)
    print(summary.to_string(index=False))
    print(f'[save] {out}')


def _boxplot(runs, out):
    # one box per target and tool of the options changed after olddefconfig, over the
    # repairs whose object Kbuild compiled or selected in the copy of the build, with
    # their number below the box; on a log scale, as the changes span 1 to hundreds
    systems = list(dict.fromkeys(target for target, _ in runs))
    fig, ax = plt.subplots(figsize=helper.plot.figsize(0.48 * helper.plot.TEXT_PT, 0.75))
    for (target, tool), df in runs.items():
        if 'compile' not in df:
            continue
        selected = df[df['compile'].isin(['compiled', 'compile error'])]['changed']
        x = systems.index(target) + (-0.18 if tool == 'tool' else 0.18)
        if len(selected):
            ax.boxplot([selected], positions=[x], widths=0.3, patch_artist=True,
                       boxprops={'facecolor': helper.plot.SERIES[tool], 'alpha': 0.35,
                                 'edgecolor': helper.plot.SERIES[tool]},
                       medianprops={'color': helper.plot.SERIES[tool]},
                       whiskerprops={'color': helper.plot.SERIES[tool]},
                       capprops={'color': helper.plot.SERIES[tool]},
                       flierprops={'markeredgecolor': helper.plot.SERIES[tool], 'markersize': 3})
        ax.text(x, 0.02, f'{len(selected)}', transform=ax.get_xaxis_transform(), ha='center',
                fontsize=helper.plot.FONT_PT - 2, color=helper.plot.MUTED)
    ax.set_yscale('log')
    ax.set_xticks(range(len(systems)), [helper.plot.SYSTEM[s] for s in systems])
    ax.set_xlim(-0.5, len(systems) - 0.5)
    ax.set_ylabel('options changed')
    ax.grid(axis='x', visible=False)
    handles = [plt.Rectangle((0, 0), 1, 1, facecolor=helper.plot.SERIES[tool], alpha=0.35,
                             edgecolor=helper.plot.SERIES[tool]) for tool in TOOLS]
    ax.legend(handles, [helper.plot.LABEL[tool] for tool in TOOLS], loc='upper left')
    fig.tight_layout(pad=0.15)
    fig.savefig(out)
    plt.close(fig)
    print(f'[save] {out}')


def _radar(runs, out):
    # one spoke per build that both tools have repaired completely, all OBJECTS repairs
    # without an error, and one polygon per tool at the median repair time of the build;
    # the radius is log10 of seconds, as the tools differ by four orders of magnitude
    builds = []
    for target in TARGETS:
        if not all((target, tool) in runs for tool in TOOLS):
            continue
        finished = [runs[target, tool][runs[target, tool]['status'] != 'error'].groupby('build').size()
                    for tool in TOOLS]
        builds += [(target, build) for build in finished[0].index
                   if all(f.get(build, 0) == OBJECTS for f in finished)]
    angles = [2 * math.pi * i / len(builds) for i in range(len(builds))]
    ticks = [-3, -2, -1, 0, 1, 2]
    fig, ax = plt.subplots(subplot_kw={'projection': 'polar'},
                           figsize=helper.plot.figsize(0.48 * helper.plot.TEXT_PT, 1.0))
    for tool in TOOLS:
        values = []
        for target, build in builds:
            df = runs[target, tool]
            values.append(math.log10(df[(df['build'] == build) & (df['status'] != 'error')]['seconds'].median()))
        ax.plot(angles + angles[:1], values + values[:1], color=helper.plot.SERIES[tool],
                linewidth=1.2, marker=helper.plot.MARKER[tool], markersize=3,
                label=helper.plot.LABEL[tool])
        ax.fill(angles, values, color=helper.plot.SERIES[tool], alpha=0.12)
    ax.set_theta_offset(math.pi / 2)
    ax.set_theta_direction(-1)
    ax.set_xticks(angles, [f'{helper.plot.SYSTEM[target][len("Linux "):]}\n{build}' for target, build in builds])
    ax.set_ylim(ticks[0], ticks[-1])
    ax.set_yticks(ticks, ['1 ms', '10 ms', '0.1 s', '1 s', '10 s', '100 s'],
                  color=helper.plot.MUTED, fontsize=helper.plot.FONT_PT - 2)
    ax.set_rlabel_position(180 / len(builds))
    ax.tick_params(axis='x', pad=2)
    handles, labels = ax.get_legend_handles_labels()
    fig.legend(handles, labels, loc='lower center', ncol=len(TOOLS), frameon=False)
    fig.tight_layout(pad=0.15, rect=(0, 0.07, 1, 1))
    fig.savefig(out)
    plt.close(fig)
    print(f'[save] {out}')


def main():
    args = helper.args.parse_args()
    runs = _load(args)
    helper.plot.apply()
    _summary(runs, os.path.join(args.csv_dir, 'rq3_summary.csv'))
    _boxplot(runs, os.path.join(args.figure_dir, 'rq3_changed.pdf'))
    _radar(runs, os.path.join(args.figure_dir, 'rq3_time.pdf'))


if __name__ == '__main__':
    main()
