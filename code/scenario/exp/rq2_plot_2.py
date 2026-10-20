from scenario.exp.rq2_plot import load, draw
from scenario import helper

# the benchmark of this figure: 0, 100, ..., 2000 conditional blocks, for the tool and
# Kmax; path forking runs up to 12 blocks, in the figure of rq2_plot
SIZES = range(0, 2001, 100)
TOOLS = ['tool', 'kmax']


def main():
    args = helper.args.parse_args()
    draw(args, load(args, SIZES, TOOLS), 'rq2_2')


if __name__ == '__main__':
    main()
