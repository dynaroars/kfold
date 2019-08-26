import pdb

import helpers.vcommon as CM
import settings
mlog = CM.getLogger(__name__, settings.logger_level)

DBG = pdb.set_trace


class Miscs:
    @classmethod
    def get_workload(cls, tasks, n_cpus):
        """
        sage: from helpers.miscs import Miscs

        >>> wls = Miscs.get_workload(range(12),7); [len(wl) for wl in wls]
        [1, 1, 2, 2, 2, 2, 2]

        >>> wls = Miscs.get_workload(range(12),5); [len(wl) for wl in wls]
        [2, 2, 2, 3, 3]

        >>> wls = Miscs.get_workload(range(20),7); [len(wl) for wl in wls]
        [2, 3, 3, 3, 3, 3, 3]

        >>> wls = Miscs.get_workload(range(20),20); [len(wl) for wl in wls]
        [1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1]

        >>> wls = Miscs.get_workload(range(12),7); [len(wl) for wl in wls]
        [1, 1, 2, 2, 2, 2, 2]

        >>> wls = Miscs.get_workload(range(146), 20); [len(wl) for wl in wls]
            [7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 8, 8, 8, 8, 8, 8]
        """
        assert len(tasks) >= 1, tasks
        assert n_cpus >= 1, n_cpus

        wloads = {}
        for i, task in enumerate(tasks):
            cpu_id = i % n_cpus
            if cpu_id not in wloads:
                wloads[cpu_id] = []
            wloads[cpu_id].append(task)

        wloads = [wl for wl in sorted(wloads.values(), key=lambda wl: len(wl))]
        return wloads

    @classmethod
    def run_mp(cls, taskname, tasks, f, do_mp):
        """
        Run wprocess on tasks in parallel
        """
        def wprocess(mytasks, myQ):
            rs = f(mytasks)
            if myQ is None:
                return rs
            else:
                myQ.put(rs)

        if do_mp and len(tasks) >= 2:
            from multiprocessing import (Process, Queue, cpu_count)
            Q = Queue()
            n_cpus = cpu_count()

            wloads = cls.get_workload(tasks, n_cpus=n_cpus)

            mlog.debug("{}:running {} jobs using {} threads: {}".format(
                taskname, len(tasks), len(wloads), list(map(len, wloads))))

            workers = [Process(target=wprocess, args=(wl, Q)) for wl in wloads]

            for w in workers:
                w.start()
            wrs = []
            for _ in workers:
                wrs.extend(Q.get())
        else:
            wrs = wprocess(tasks, myQ=None)

        return wrs

    # @classmethod
    # def getWorkloads(cls, tasks, maxProcessces, chunksiz):
    #     """
    #     >>> wls = Miscs.getWorkloads(range(12),7,1); wls
    #     [[0, 1], [2, 3], [4, 5], [6, 7], [8, 9], [10, 11]]

    #     >>> wls = Miscs.getWorkloads(range(12),5,2); wls
    #     [[0, 1], [2, 3], [4, 5], [6, 7], [8, 9, 10, 11]]

    #     >>> wls = Miscs.getWorkloads(range(20),7,2); wls
    #     [[0, 1, 2], [3, 4, 5], [6, 7, 8], [9, 10, 11], [12, 13, 14], [15, 16, 17], [18, 19]]

    #     >>> wls = Miscs.getWorkloads(range(20),20,2); wls
    #     [[0, 1], [2, 3], [4, 5], [6, 7], [8, 9], [10, 11], [12, 13], [14, 15], [16, 17], [18, 19]]

    #     """
    #     assert len(tasks) >= 1, tasks
    #     assert maxProcessces >= 1, maxProcessces
    #     assert chunksiz >= 1, chunksiz

    #     # determine # of processes
    #     ntasks = len(tasks)
    #     nprocesses = int(round(ntasks/float(chunksiz)))
    #     if nprocesses > maxProcessces:
    #         nprocesses = maxProcessces

    #     # determine workloads
    #     cs = int(round(ntasks/float(nprocesses)))
    #     wloads = []
    #     for i in range(nprocesses):
    #         s = i*cs
    #         e = s+cs if i < nprocesses-1 else ntasks
    #         wl = tasks[s:e]
    #         if wl:  # could be 0, e.g., getWorkloads(range(12),7,1)
    #             wloads.append(wl)

    #     return wloads

    # @classmethod
    # def runMP(cls, taskname, tasks, wprocess, chunksiz, doMP):
    #     """
    #     Run wprocess on tasks in parallel
    #     """
    #     if doMP:
    #         from multiprocessing import (Process, Queue, cpu_count)
    #         Q = Queue()
    #         wloads = cls.getWorkloads(
    #             tasks, maxProcessces=cpu_count(), chunksiz=chunksiz)

    #         # mlog.debug("workloads '{}' {}: {}"
    #         #            .format(taskname, len(wloads), map(len,wloads)))

    #         workers = [Process(target=wprocess, args=(wl, Q)) for wl in wloads]

    #         for w in workers:
    #             w.start()
    #         wrs = []
    #         for _ in workers:
    #             wrs.extend(Q.get())
    #     else:
    #         wrs = wprocess(tasks, Q=None)

    #     return wrs
