import multiprocessing
import importlib
import resource
import signal
import queue
import time
import os

from scenario.helper import kmax
from tool.analyze import analyze
from tool.execute import implied
from baseline.icsme import fork
from scenario import helper


def _accuracy(conditions, truth):
    # the objects compared with the tree's build conditions by construction: missing and
    # extra objects, and, of the objects in both, those whose conditions are equivalent
    # in every configuration and those whose conditions differ in some
    both = conditions.keys() & truth.keys()
    equivalent = sum(implied(conditions[obj], truth[obj]) and implied(truth[obj], conditions[obj])
                     for obj in both)
    return {'objects': len(conditions), 'expected': len(truth),
            'missing': len(truth.keys() - conditions.keys()),
            'extra': len(conditions.keys() - truth.keys()),
            'equivalent': equivalent, 'different': len(both) - equivalent}


def _measure(tool, path, memory_gb, structure, n_ifeq, results):
    # one analysis in a fresh process, so its peak memory is its own; a session of its
    # own lets the parent kill Kmax's kmaxall and kmax processes with it. The formulas
    # stay in this process, so it also compares them with the truth of `structure`
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
    # after the clock stops, so the comparison is not part of the time
    truth = importlib.import_module(f'scenario.prepare.{structure}').truth(n_ifeq)
    results.put({'status': 'ok', 'seconds': seconds, 'memory_mb': kib / 1024, 'paths': paths,
                 **_accuracy(conditions, truth)})


def run(args, structure, csv_path):
    # measure --tool on every tree <target_dir>/<structure>-<n> that prepare wrote, with n
    # up to --n_ifeq, such as length-1 to length-20 and length-20, -40, ..., -200
    prefix = f'{structure}-'
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
        process = context.Process(target=_measure, args=(args.tool, path, args.memory_gb,
                                                         structure, n_ifeq, results))
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
        row = {'seconds': None, 'memory_mb': None, 'paths': None, 'objects': None,
               'expected': None, 'missing': None, 'extra': None, 'equivalent': None,
               'different': None, **result}
        pbar.step(n_ifeq=n_ifeq, **row)
        # the rows so far, so an interrupted run keeps the sizes it finished
        pbar.save_csv()
        # a larger n_ifeq runs at least as long and takes at least as much memory
        if row['status'] != 'ok':
            break
    pbar.to_csv()
    print(f'[save] {csv_path}')


def main():
    args = helper.args.parse_args()
    # the trees <target_dir>/<structure>-<n> of --target, compared with the truth() of
    # scenario/prepare/<structure>.py
    run(args, args.target, os.path.join(args.csv_dir, f'rq2_{args.target}_{args.tool}.csv'))

if __name__ == '__main__':
    main()
