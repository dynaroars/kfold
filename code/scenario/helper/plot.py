import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

# acmart acmsmall (the paper's class): \textwidth is 395.82 pt, \footnotesize is 8 pt,
# captions are 9 pt; measured with \typeout in a one-page acmart document
TEXT_PT = 395.82
FONT_PT = 8

# one color per tool (categorical slots 1 and 2, validated for color-vision deficiency),
# the reference line, and the recessive grid and axes
SERIES = {'tool': '#2a78d6', 'kmax': '#eb6834'}
LABEL = {'tool': 'Tool', 'kmax': 'Kmax'}
# marker per tool, so overlapping points of the two tools stay visible
MARKER = {'tool': 'o', 'kmax': 'x'}
# display name per target system
SYSTEM = {'busybox': 'BusyBox', 'linux': 'Linux', 'coreboot': 'coreboot'}
MUTED = '#898781'
GRID = '#e1e0d9'
AXIS = '#c3c2b7'


def apply():
    import seaborn as sns

    sns.set_theme(style='whitegrid', font='serif')
    plt.rcParams.update({
        'font.family': 'serif',
        'font.serif': ['Libertinus Serif', 'Linux Libertine O', 'DejaVu Serif'],
        'font.size': FONT_PT,
        'axes.labelsize': FONT_PT,
        'xtick.labelsize': FONT_PT,
        'ytick.labelsize': FONT_PT,
        'legend.fontsize': FONT_PT,
        'grid.color': GRID,
        'grid.linewidth': 0.5,
        'axes.edgecolor': AXIS,
        'axes.linewidth': 0.6,
        'pdf.fonttype': 42,
        'ps.fonttype': 42,
    })


def figsize(width_pt, aspect):
    # width_pt is the on-page width, so LaTeX includes the figure without rescaling
    w = width_pt / 72.27
    return (w, w * aspect)
