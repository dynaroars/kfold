import random
import json
import math
import os

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import pandas as pd

from scenario.helper import target
from scenario import helper

# the error counts of the paper's metrics, as (CSV column, panel title)
ERRORS = [
    ('fp', 'false positives'),
    ('fn_u', 'missed extracted objects'),
    ('out', 'compiled objects outside U'),
]


def _save(fig, out):
    fig.tight_layout(pad=0.15)
    fig.savefig(out)
    plt.close(fig)
    print(f'[save] {out}')


def _load(args):
    # {(system, tool): (per-configuration rows, {config: {error: [objects]}} or None)}
    runs = {}
    for system in target.VARIABLES:
        for tool in helper.plot.SERIES:
            csv_path = os.path.join(args.csv_dir, f'rq1_{system}_{tool}.csv')
            if not os.path.isfile(csv_path):
                continue
            # rq1_run writes an empty CSV for a target without build trees
            if not open(csv_path).read().strip():
                print(f'[skip] {csv_path}: empty, the target has no build trees')
                continue
            errors_path = os.path.join(args.analysis_dir, tool, f'{system}.rq1.json')
            errors = None
            if os.path.isfile(errors_path):
                with open(errors_path) as f:
                    errors = json.load(f)
            runs[system, tool] = (pd.read_csv(csv_path), errors)
            print(f'[load] {csv_path}')
    return runs


def _summary(runs, out):
    # one row per system and tool, over all its configurations: precision is the share
    # of predicted objects that were compiled, recall the share of compiled objects
    # that were predicted (the paper's overlap TP / |B_c|)
    rows = []
    for (system, tool), (df, _) in runs.items():
        rows.append({'system': helper.plot.SYSTEM[system], 'tool': helper.plot.LABEL[tool],
                     'configs': len(df),
                     'precision': df['tp'].sum() / df['predicted'].sum(),
                     'recall': df['tp'].sum() / df['observed'].sum()})
    summary = pd.DataFrame(rows)
    summary.to_csv(out, index=False)
    print(summary.to_string(index=False))
    print(f'[save] {out}')


def _plot_errors(runs, out):
    # one panel per error count, one marker per configuration; x is the system and the
    # tools sit side by side, spread a little so equal counts stay visible
    systems = list(dict.fromkeys(system for system, _ in runs))
    jitter = random.Random(0)
    fig, axes = plt.subplots(1, len(ERRORS), figsize=helper.plot.figsize(0.98 * helper.plot.TEXT_PT, 0.3))
    for ax, (column, title) in zip(axes, ERRORS):
        for (system, tool), (df, _) in runs.items():
            x = systems.index(system) + (-0.17 if tool == 'tool' else 0.17)
            xs = [x + jitter.uniform(-0.07, 0.07) for _ in range(len(df))]
            ax.scatter(xs, df[column], s=18, marker=helper.plot.MARKER[tool],
                       color=helper.plot.SERIES[tool], linewidth=1, zorder=2,
                       label=helper.plot.LABEL[tool])
        ax.set_title(title, fontsize=helper.plot.FONT_PT)
        ax.set_xticks(range(len(systems)), [helper.plot.SYSTEM[s] for s in systems])
        ax.set_xlim(-0.5, len(systems) - 0.5)
        ax.set_ylim(bottom=-0.05 * max(1, ax.get_ylim()[1]))
        ax.grid(axis='x', visible=False)
    axes[0].set_ylabel('objects per configuration')
    handles, labels = axes[0].get_legend_handles_labels()
    unique = dict(zip(labels, handles))
    axes[-1].legend(unique.values(), unique.keys(), loc='upper left')
    _save(fig, out)


def _plot_time(runs, out):
    # one bar per system and tool: the wall-clock time of the whole-tree analysis, on a
    # log scale since the systems differ by orders of magnitude
    systems = list(dict.fromkeys(system for system, _ in runs))
    # height grows with the systems, so each pair of bars keeps its room
    fig, ax = plt.subplots(figsize=helper.plot.figsize(0.48 * helper.plot.TEXT_PT,
                                                       0.25 + 0.1 * len(systems)))
    for (system, tool), (df, _) in runs.items():
        y = systems.index(system) + (-0.2 if tool == 'tool' else 0.2)
        seconds = df['analyze_seconds'].iloc[0]
        ax.barh(y, seconds, height=0.36, color=helper.plot.SERIES[tool],
                label=helper.plot.LABEL[tool])
        ax.text(seconds, y, f' {seconds:.1f} s', va='center')
    ax.set_xscale('log')
    ax.set_yticks(range(len(systems)), [helper.plot.SYSTEM[s] for s in systems])
    ax.invert_yaxis()
    ax.set_xlim(right=ax.get_xlim()[1] * 8)
    ax.set_xlabel('analysis time (s)')
    ax.grid(axis='y', visible=False)
    handles, labels = ax.get_legend_handles_labels()
    unique = dict(zip(labels, handles))
    # one row above the axes: with seven systems, every corner inside holds a label
    ax.legend(unique.values(), unique.keys(), loc='lower center', bbox_to_anchor=(0.5, 1.0),
              ncol=len(unique), frameon=False)
    _save(fig, out)


def _plot_radar(runs, figure_dir):
    # one radar chart per measure, saved as rq1_radar_<measure>.pdf for a subfigure a
    # third of the text wide, and the legend the three share as rq1_radar_legend.pdf;
    # one spoke per system and one polygon per tool. Precision
    # and recall are pooled over the configurations as in the summary; time runs from 0
    # to the slowest analysis rounded up to 100 s, in four rings
    tools = list(dict.fromkeys(tool for _, tool in runs))
    # a spoke needs every tool, so a system still running for one tool waits
    systems = [system for system in dict.fromkeys(system for system, _ in runs)
               if all((system, tool) in runs for tool in tools)]
    angles = [2 * math.pi * i / len(systems) for i in range(len(systems))]
    top = 100 * math.ceil(max(df['analyze_seconds'].iloc[0] for df, _ in runs.values()) / 100)
    rings = [top * i / 4 for i in range(1, 5)]
    measures = [
        ('precision', lambda df: df['tp'].sum() / df['predicted'].sum(), [0.25, 0.5, 0.75, 1.0],
         ['.25', '.50', '.75', '1']),
        ('recall', lambda df: df['tp'].sum() / df['observed'].sum(), [0.25, 0.5, 0.75, 1.0],
         ['.25', '.50', '.75', '1']),
        ('time', lambda df: df['analyze_seconds'].iloc[0], rings,
         [f'{ring:g} s' for ring in rings]),
    ]
    for name, value, ticks, labels in measures:
        fig, ax = plt.subplots(subplot_kw={'projection': 'polar'},
                               figsize=helper.plot.figsize(0.32 * helper.plot.TEXT_PT, 1.0))
        for tool in tools:
            values = [value(runs[system, tool][0]) for system in systems]
            ax.plot(angles + angles[:1], values + values[:1], color=helper.plot.SERIES[tool],
                    linewidth=1.2, marker=helper.plot.MARKER[tool], markersize=3,
                    label=helper.plot.LABEL[tool])
            ax.fill(angles, values, color=helper.plot.SERIES[tool], alpha=0.12)
        ax.set_theta_offset(math.pi / 2)
        ax.set_theta_direction(-1)
        # two-line names, such as Linux over x86-64, keep the labels inside the narrow figure
        ax.set_xticks(angles, [helper.plot.SYSTEM[s].replace(' ', '\n') for s in systems])
        ax.set_ylim(0, ticks[-1])
        ax.set_yticks(ticks, labels, color=helper.plot.MUTED, fontsize=helper.plot.FONT_PT - 2)
        # the radial labels sit halfway between the first two spokes
        ax.set_rlabel_position(180 / len(systems))
        ax.tick_params(axis='x', pad=0)
        handles, legend = ax.get_legend_handles_labels()
        _save(fig, os.path.join(figure_dir, f'rq1_radar_{name}.pdf'))
    # the shared legend, one row as wide as the text
    fig, ax = plt.subplots(figsize=(helper.plot.TEXT_PT / 72.27, 0.2))
    ax.axis('off')
    ax.legend(handles, legend, loc='center', ncol=len(tools), frameon=False,
              handlelength=1.8, columnspacing=2.0)
    fig.tight_layout(pad=0.05)
    fig.savefig(os.path.join(figure_dir, 'rq1_radar_legend.pdf'))
    plt.close(fig)
    print(f"[save] {os.path.join(figure_dir, 'rq1_radar_legend.pdf')}")


def main():
    args = helper.args.parse_args()
    runs = _load(args)
    helper.plot.apply()
    _summary(runs, os.path.join(args.csv_dir, 'rq1_summary.csv'))
    _plot_errors(runs, os.path.join(args.figure_dir, 'rq1.pdf'))
    _plot_time(runs, os.path.join(args.figure_dir, 'rq1_time.pdf'))
    _plot_radar(runs, args.figure_dir)


if __name__ == '__main__':
    main()
