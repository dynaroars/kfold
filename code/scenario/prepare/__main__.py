import importlib

from scenario.helper.args import parse_args

def main():
    args = parse_args()
    # the module of --target, with - as _: --target=linux-x86_64 runs linux_x86_64.py
    module = args.target.replace('-', '_')
    importlib.import_module(f'scenario.prepare.{module}').prepare(args)

if __name__ == '__main__':
    main()
