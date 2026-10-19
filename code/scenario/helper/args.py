import argparse
import os

def maybe_mkdir(args):
    for d in [args.figure_dir, args.analysis_dir, args.target_dir, args.csv_dir]:
        os.makedirs(d, exist_ok=True)

def parse_args():
    parser = argparse.ArgumentParser()

    parser.add_argument('--target', type=str, default='busybox')
    parser.add_argument('--n_build', type=int, default=10)

    parser.add_argument('--figure_dir', type=str, default='../paper/figure/result')
    parser.add_argument('--analysis_dir', type=str, default='data/analysis')
    parser.add_argument('--target_dir', type=str, default='data/target')
    parser.add_argument('--csv_dir', type=str, default='data/csv')

    args = parser.parse_args()
    maybe_mkdir(args)
    return args
