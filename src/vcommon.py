import tempfile
import os.path
import itertools
import subprocess as sp
import operator
import inspect

import logging


def pause(s=None):
    input("Press any key to continue ..." if s is None else s)


def whoami():
    return inspect.stack()[1][3]


def vcmd(cmd, inp=None, shell=True):
    proc = sp.Popen(cmd, shell=shell, stdin=sp.PIPE,
                    stdout=sp.PIPE, stderr=sp.PIPE)
    return proc.communicate(input=inp)


def vload(filename, mode='rb'):
    import pickle
    with open(filename, mode) as fh:
        pickler = pickle.Unpickler(fh)
        sobj = pickler.load()
    return sobj


def vsave(filename, sobj, mode='wb'):
    import pickle
    with open(filename, mode) as fh:
        pickler = pickle.Pickler(fh, -1)
        pickler.dump(sobj)


def vread(filename):
    with open(filename, 'r') as fh:
        return fh.read()


def iread(filename):
    """ return a generator """
    with open(filename, 'r') as fh:
        for line in fh:
            yield line


def strip_contents(lines, strip_c='#'):
    lines = (l.strip() for l in lines)
    lines = (l for l in lines if l)
    if strip_c:
        lines = (l for l in lines if not l.startswith(strip_c))
    return lines


def iread_strip(filename, strip_c='#'):
    """
    like iread but also strip out comments and empty line
    """
    return strip_contents(iread(filename), strip_c)


def getpath(f): return os.path.realpath(os.path.expanduser(f))


def file_basename(filename): return os.path.splitext(filename)[0]


def iflatten(l): return itertools.chain.from_iterable(l)  # return a generator

# log utils


def getLogger(name, level):
    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG)
    ch = logging.StreamHandler()
    ch.setLevel(level)
    formatter = logging.Formatter("%(name)s:%(levelname)s:%(message)s")
    ch.setFormatter(formatter)
    logger.addHandler(ch)
    return logger


def getLogLevel(level):
    assert level in set(range(5))

    if level == 0:
        return logging.CRITICAL
    elif level == 1:
        return logging.ERROR
    elif level == 2:
        return logging.WARNING
    elif level == 3:
        return logging.INFO
    else:
        return logging.DEBUG


class Miscs:
    @classmethod
    def getWorkloads(cls, tasks, maxProcessces, chunksiz):
        """
        >>> wls = Miscs.getWorkloads(range(12),7,1); wls
        [[0, 1], [2, 3], [4, 5], [6, 7], [8, 9], [10, 11]]


        >>> wls = Miscs.getWorkloads(range(12),5,2); wls
        [[0, 1], [2, 3], [4, 5], [6, 7], [8, 9, 10, 11]]

        >>> wls = Miscs.getWorkloads(range(20),7,2); wls
        [[0, 1, 2], [3, 4, 5], [6, 7, 8], [9, 10, 11], [12, 13, 14], [15, 16, 17], [18, 19]]


        >>> wls = Miscs.getWorkloads(range(20),20,2); wls
        [[0, 1], [2, 3], [4, 5], [6, 7], [8, 9], [10, 11], [12, 13], [14, 15], [16, 17], [18, 19]]

        """
        assert len(tasks) >= 1, tasks
        assert maxProcessces >= 1, maxProcessces
        assert chunksiz >= 1, chunksiz

        # determine # of processes
        ntasks = len(tasks)
        nprocesses = int(round(ntasks/float(chunksiz)))
        if nprocesses > maxProcessces:
            nprocesses = maxProcessces

        # determine workloads
        cs = int(round(ntasks/float(nprocesses)))
        wloads = []
        for i in range(nprocesses):
            s = i*cs
            e = s+cs if i < nprocesses-1 else ntasks
            wl = tasks[s:e]
            if wl:  # could be 0, e.g., getWorkloads(range(12),7,1)
                wloads.append(wl)

        return wloads

    @classmethod
    def runMP(cls, taskname, tasks, wprocess, chunksiz, doMP):
        """
        Run wprocess on tasks in parallel
        """
        if doMP:
            from multiprocessing import (Process, Queue, cpu_count)
            Q = Queue()
            wloads = cls.getWorkloads(
                tasks, maxProcessces=cpu_count(), chunksiz=chunksiz)

            # mlog.debug("workloads '{}' {}: {}"
            #            .format(taskname, len(wloads), map(len,wloads)))

            workers = [Process(target=wprocess, args=(wl, Q)) for wl in wloads]

            for w in workers:
                w.start()
            wrs = []
            for _ in workers:
                wrs.extend(Q.get())
        else:
            wrs = wprocess(tasks, Q=None)

        return wrs
