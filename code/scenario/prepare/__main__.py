from scenario.helper.args import parse_args
from . import busybox

def main():
    args = parse_args()
    eval(args.target).prepare(args)

if __name__ == '__main__':
    main()
