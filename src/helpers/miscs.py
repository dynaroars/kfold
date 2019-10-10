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
            wloads.setdefault(cpu_id, []).append(task)

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
            # mlog.debug("{}:running {} jobs using {} threads: {}".format(
            #     taskname, len(tasks), len(wloads), list(map(len, wloads))))

            workers = [Process(target=wprocess, args=(wl, Q)) for wl in wloads]

            for w in workers:
                w.start()

            wrs = [x for _ in workers for x in Q.get()]
        else:
            wrs = wprocess(tasks, myQ=None)

        return wrs
