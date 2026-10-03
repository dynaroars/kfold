#!/usr/bin/env python3
"""Generate manuscript table bodies from the September 2026 rerun results."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RESULTS = ROOT / 'results'
TABLES = ROOT / 'paper' / 'tables'


def read(filename):
    return json.loads((RESULTS / filename).read_text())


def make_table(rows):
    header = [r'\begin{tabular}{lrrrrrrr}', r'\toprule',
              'Configuration & Pred. & TP & FP & $FN_U$ & $O$ & Prec. & Overlap ' + '\\\\',
              r'\midrule']
    body = [' & '.join(map(str, row)) + ' ' + '\\\\' for row in rows]
    return '\n'.join(header + body + [r'\bottomrule', r'\end{tabular}']) + '\n'


def main():
    TABLES.mkdir(parents=True, exist_ok=True)
    linux = read('linux_four_profile_revalidation_20260924.json')
    nonlinux = read('archived_build_revalidation_20260924.json')
    linux_rows = []
    labels = {'tinyconfig': r'\texttt{tinyconfig} (i386)',
              'defconfig': r'\texttt{defconfig} (x86-64)',
              'debian': 'Debian (x86-64)',
              'allmodconfig': r'\texttt{allmodconfig} (x86-64)'}
    for name, label in labels.items():
        p = linux['profiles'][name]['physical']
        linux_rows.append((label, f"{p['predicted']:,}", f"{p['tp']:,}",
                           f"{p['fp']:,}", f"{p['fn_within_universe']:,}",
                           f"{p['outside_universe']:,}",
                           f"{p['precision_pct']:.1f}\\%",
                           f"{p['observed_physical_overlap_pct']:.1f}\\%"))
    (TABLES / 'tab_linux_physical.tex').write_text(make_table(linux_rows))

    labels = {'BusyBox': r'BusyBox \texttt{defconfig}',
              'coreboot': 'coreboot QEMU i440fx',
              'Barebox': r'Barebox \texttt{sandbox\_defconfig}',
              'Das U-Boot': r'Das U-Boot \texttt{sandbox\_defconfig}'}
    rows = []
    for p in nonlinux:
        tp, pred, physical = p['true_positive'], p['predicted'], p['physical']
        rows.append((labels[p['subject']], f'{pred:,}', f'{tp:,}',
                     f"{p['false_positive']:,}",
                     f"{p['missing_within_universe']:,}",
                     f"{p['physical_outside_universe']:,}",
                     f'{100*tp/pred:.1f}\\%', f'{100*tp/physical:.1f}\\%'))
    (TABLES / 'tab_nonlinux_physical.tex').write_text(make_table(rows))

    corpora = read('all_corpora_results.json')
    rows = [(p['name'], p['makefiles_count'], p['objects_count'],
             f"{p['wall_time']:.2f}") for p in corpora]
    rows.append(('Linux v6.6 (x86)', linux['makefile_instances'],
                 linux['profiles']['tinyconfig']['physical']['target_universe'],
                 f"{linux['analysis_time_s']:.2f}"))
    lines = [r'\begin{tabular}{lrrr}', r'\toprule',
             'Subject & Makefile instances & Target records/paths & Wall time (s) ' + '\\\\',
             r'\midrule']
    lines += [' & '.join(map(str, row)) + ' ' + '\\\\' for row in rows]
    lines += [r'\bottomrule', r'\end{tabular}']
    (TABLES / 'tab_corpus.tex').write_text('\n'.join(lines) + '\n')
    (TABLES / 'tab_build_validation.tex').write_text(
        '% Superseded by tab_linux_physical.tex and tab_nonlinux_physical.tex.\n')


if __name__ == '__main__':
    main()
