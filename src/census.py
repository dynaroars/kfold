"""Construct census and performance metrics tracking for skbuild."""

import collections
import resource
import time
from typing import Dict, Any


class Metrics:
    def __init__(self):
        self.reset()

    def reset(self):
        self.start_time = time.time()
        self.end_time = None
        self.construct_counts = collections.Counter()
        self.construct_categories = {
            # Modeled constructs
            "SetVariable:=": "modeled",
            "SetVariable=": "modeled",
            "SetVariable+=": "modeled",
            "SetVariable?=": "modeled",
            "SetVariable::=": "modeled",
            "ConditionBlock:eq": "modeled",
            "ConditionBlock:ifeq": "modeled",
            "ConditionBlock:ifneq": "modeled",
            "ConditionBlock:ifdef": "modeled",
            "ConditionBlock:ifndef": "modeled",
            "ConditionBlock": "modeled",
            "Include": "modeled",
            "Function:variableref": "modeled",
            "Function:subst": "modeled",
            "Function:patsubst": "modeled",
            "Function:filter": "modeled",
            "Function:filter-out": "modeled",
            "Function:filterout": "modeled",
            "Function:strip": "modeled",
            "Function:findstring": "modeled",
            "Function:sort": "modeled",
            "Function:firstword": "modeled",
            "Function:lastword": "modeled",
            "Function:words": "modeled",
            "Function:word": "modeled",
            "Function:wordlist": "modeled",
            "Function:dir": "modeled",
            "Function:notdir": "modeled",
            "Function:suffix": "modeled",
            "Function:basename": "modeled",
            "Function:addsuffix": "modeled",
            "Function:addprefix": "modeled",
            "Function:if": "modeled",
            "Function:or": "modeled",
            "Function:and": "modeled",
            "Function:foreach": "modeled",
            "Function:call": "modeled",
            "Function:shell": "modeled",
            "Function:error": "modeled",
            "Function:warning": "modeled",
            "Function:info": "modeled",
            "Function:wildcard": "modeled",
            # Correctly out of scope
            "Rule": "out_of_scope",
            "StaticPatternRule": "out_of_scope",
            "Command": "out_of_scope",
            "EmptyDirective": "out_of_scope",
        }
        self.set_var_calls = 0
        self.z3_checks = 0
        self.z3_sat_calls = 0
        self.z3_valid_calls = 0

    def record_construct(self, name: str):
        self.construct_counts[name] += 1

    def summary(self) -> Dict[str, Any]:
        elapsed = (self.end_time or time.time()) - self.start_time
        peak_rss_kib = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss

        by_category = {
            "modeled": {},
            "out_of_scope": {},
            "unsupported": {},
        }

        total_modeled = 0
        total_out_of_scope = 0
        total_unsupported = 0

        for construct, count in sorted(self.construct_counts.items()):
            cat = self.construct_categories.get(construct, "unsupported")
            by_category[cat][construct] = count
            if cat == "modeled":
                total_modeled += count
            elif cat == "out_of_scope":
                total_out_of_scope += count
            else:
                total_unsupported += count

        return {
            "elapsed_seconds": elapsed,
            "peak_rss_kib": peak_rss_kib,
            "z3": {
                "checks": self.z3_checks,
                "is_sat_calls": self.z3_sat_calls,
                "is_valid_calls": self.z3_valid_calls,
            },
            "state_operations": {
                "set_var_calls": self.set_var_calls,
            },
            "construct_census": {
                "totals": {
                    "modeled": total_modeled,
                    "out_of_scope": total_out_of_scope,
                    "unsupported": total_unsupported,
                    "total": sum(self.construct_counts.values()),
                },
                "by_category": by_category,
            },
        }


# Global metrics collector instance
GLOBAL_METRICS = Metrics()
