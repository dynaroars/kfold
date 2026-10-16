"""Helpers for evaluating kfold object conditions against builds.

The object extraction itself is src/objects.py; this module adds the
physical-inventory and comparison helpers used by the evaluation scripts.
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))
from objects import *  # noqa: E402,F401,F403
from objects import (config_values, object_conditions, predicted_objects,  # noqa: E402,F401
                     target_path, builtin_guards, rule_closure)


def physical_objects(archive):
    archive = pathlib.Path(archive)
    return {str(p.relative_to(archive)) for p in archive.rglob("*.o")
            if not p.name.endswith(".mod.o")}



def compare(predicted, physical, universe):
    tp = predicted & physical
    fp = predicted - physical
    fn_u = (physical & universe) - predicted
    outside = physical - universe
    pct = lambda a, b: round(100.0 * a / b, 1) if b else None
    return {
        "universe": len(universe), "predicted": len(predicted),
        "physical": len(physical), "tp": len(tp), "fp": len(fp),
        "fn_within_universe": len(fn_u), "outside_universe": len(outside),
        "precision_pct": pct(len(tp), len(predicted)),
        "recall_within_universe_pct": pct(len(tp), len(tp) + len(fn_u)),
        "overlap_pct": pct(len(tp), len(physical)),
        "fp_paths": sorted(fp), "fn_within_universe_paths": sorted(fn_u),
        "outside_universe_paths": sorted(outside),
    }
