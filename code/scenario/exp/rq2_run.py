import multiprocessing
import resource
import signal
import queue
import time
import os

from scenario.helper import kmax
from tool.analyze import analyze
from baseline.icsme import fork
from scenario import helper


def _measure(tool, path, memory_gb, results):
    # one analysis in a fresh process, so its peak memory is its own; a session of its
    # own lets the parent kill Kmax's kmaxall and kmax processes with it
    os.setsid()
    limit = memory_gb * 2 ** 30
    resource.setrlimit(resource.RLIMIT_AS, (limit, limit))
    paths = None
    start = time.perf_counter()
    try:
        if tool == 'tool':
            conditions = analyze(path, {})
        elif tool == 'kmax':
            conditions = kmax.analyze(path, {}, None)
        else:
            conditions, paths = fork.analyze(path, {})
    except MemoryError:
        results.put({'status': 'memout'})
        return
    seconds = time.perf_counter() - start
    # ru_maxrss is in KiB on Linux; Kmax's work runs in child processes
    kib = max(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
              resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss)
    results.put({'status': 'ok', 'seconds': seconds, 'memory_mb': kib / 1024,
                 'objects': len(conditions), 'paths': paths})


def run(args, prefix, csv_path, expected):
    # measure --tool on every tree <target_dir>/<prefix><n> that prepare wrote, with n up
    # to --n_ifeq, such as synthetic_1 to synthetic_20 and synthetic_0, _100, ..., _2000;
    # expected(n) is the number of objects the tree of n has
    sizes = sorted(int(d[len(prefix):]) for d in os.listdir(args.target_dir)
                   if d.startswith(prefix) and d[len(prefix):].isdigit()
                   and int(d[len(prefix):]) <= args.n_ifeq
                   and os.path.isdir(os.path.join(args.target_dir, d, 'src')))
    pbar = helper.progress_bar.create(total=len(sizes), unit='run',
                                      desc=f'run.{prefix}{args.tool}', csv_path=csv_path)
    # spawn starts each analysis from a fresh interpreter, without this process's memory
    context = multiprocessing.get_context('spawn')
    for n_ifeq in sizes:
        path = os.path.join(args.target_dir, f'{prefix}{n_ifeq}', 'src')
        results = context.Queue()
        process = context.Process(target=_measure, args=(args.tool, path, args.memory_gb, results))
        process.start()
        process.join(args.timeout)
        if process.is_alive():
            os.killpg(process.pid, signal.SIGKILL)
            process.join()
            result = {'status': 'timeout'}
        else:
            try:
                result = results.get(timeout=1)
            except queue.Empty:
                result = {'status': f'exit {process.exitcode}'}
        # every row has every column
        row = {'seconds': None, 'memory_mb': None, 'objects': None, 'paths': None, **result}
        pbar.step(n_ifeq=n_ifeq, expected=expected(n_ifeq), **row)
        # a larger n_ifeq runs at least as long and takes at least as much memory
        if row['status'] != 'ok':
            break
    pbar.to_csv()
    print(f'[save] {csv_path}')


def main():
    args = helper.args.parse_args()
    # the expected objects are bench/file_1.o ... file_<n>.o
    run(args, 'synthetic_', os.path.join(args.csv_dir, f'rq2_{args.tool}.csv'), lambda n: n)

if __name__ == '__main__':
    main()
