#!/usr/bin/env python3
"""Unified Multi-Project Real Build Validation Harness (RQ4).

Validates skbuild presence conditions against actual build graphs across:
1. BusyBox (real compiler build)
2. coreboot (real compiler build on QEMU x86 i440fx)
3. Barebox (real Make evaluation on Sandbox target)
4. Das U-Boot (real Make evaluation on Sandbox target)
"""

import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import time
import z3
from z3.z3util import get_vars

# Set up PYTHONPATH
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))

import helpers.vcommon as CM
import helpers.zsolver as zsolver
import settings
from alg import Run


def get_physical_objects(build_dir, exclude_dirs=("scripts", "tools", ".git", "Documentation")):
    """Find all .o files actually produced by a completed physical build."""
    build_dir = pathlib.Path(build_dir)
    objs = set()
    for root, dirs, files in os.walk(build_dir):
        rel_root = os.path.relpath(root, build_dir)
        if any(rel_root == p or rel_root.startswith(p + os.sep) for p in exclude_dirs):
            continue
        for f in files:
            if f.endswith(".o") and not f.endswith(".mod.o"):
                rel_path = os.path.normpath(os.path.join(rel_root, f))
                if rel_path.startswith("./"):
                    rel_path = rel_path[2:]
                objs.add(rel_path)
    return objs


def extract_compiled_objects_from_make(root_dir, defconfig_target="sandbox_defconfig", extra_env=None, extra_make_args=None):
    root_path = pathlib.Path(root_dir).resolve()
    env = os.environ.copy()
    if extra_env:
        env.update(extra_env)
    extra_make_args = extra_make_args or []

    # 1. Run defconfig (skip if defconfig_target is None: some corpora, e.g. coreboot,
    # already have a correctly-provisioned .config with no `make X_defconfig` convention).
    if defconfig_target:
        subprocess.run(["make", defconfig_target], cwd=root_path, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env)

    # 1b. If a real physical build already populated this tree, its .o files are now
    # up-to-date w.r.t. their sources, so a plain `make -n` would silently skip them
    # and undercount. Touch all sources so every object rule looks stale again.
    # (`make -n -B` is not safe here: kbuild's own .config remake logic misfires under -B.)
    for ext in ("*.c", "*.h", "*.S"):
        for f in root_path.rglob(ext):
            try:
                os.utime(f, None)
            except OSError:
                pass

    # 2. Run dry-run make to collect all compiled object targets
    proc = subprocess.run(["make", "-n"] + extra_make_args, cwd=root_path, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)

    actual_objects = set()
    # Match patterns like '-o path/to/file.o' or 'CC path/to/file.o'
    for line in proc.stdout.splitlines():
        matches = re.findall(r"(?:-o|\s)\s*([a-zA-Z0-9_\-/\.]+\.(?:o|gen\.o|a))", line)
        for m in matches:
            m_path = pathlib.Path(m)
            if not str(m_path).startswith("scripts/"):
                actual_objects.add(str(m_path))
                
    return actual_objects


def validate_corpus_build(corpus_name, root_dir, defconfig_target, extra_env=None, extra_make_args=None):
    root_path = pathlib.Path(root_dir).resolve()
    env = os.environ.copy()
    if extra_env:
        env.update(extra_env)
    print(f"\n=======================================================")
    print(f"Validating Ground Truth Build Predictions: {corpus_name}")
    print(f"=======================================================")

    runner = Run(root_path)
    tmpdir = runner.go()

    kbuilds = getattr(runner, 'all_kbuilds', getattr(runner, 'kbuilds', []))
    main_dir = getattr(runner, 'maindir', getattr(runner, 'main_dir', root_path))
    mysettings = getattr(runner, 'mysettings', None)

    # 1. Extract symbolic predictions
    target_objects = {}
    for kb in kbuilds:
        state = kb.state
        parent = kb.makefile.parent
        for v in state.target_files:
            if mysettings and v.name in mysettings.target_vars:
                continue
            # Some Kbuild dialects (e.g. coreboot's stage-based Makefile.inc:
            # `ramstage-y += cr50.c`) list source files directly rather than the
            # compiled .o, unlike Linux/Barebox/U-Boot's `obj-y += foo.o`
            # convention, AND compile the same source separately per build stage
            # (build/bootblock/..., build/romstage/..., build/ramstage/..., each
            # its own physical .o), unlike a single-output obj-y model. Derive the
            # stage from the variable name (e.g. "ramstage-y" -> "ramstage") and
            # prefix the physical path with build/<stage>/ instead of src/ to
            # match physical build output and GNU Make's -n trace.
            stage = v.name.split('-')[0] if '-' in v.name else None
            is_stage_var = stage in ("bootblock", "romstage", "ramstage", "postcar", "verstage", "smm", "decompressor")
            for word, wcond in v.valconds.items():
                if not isinstance(word, str):
                    continue
                if word.endswith(('.c', '.C', '.S', '.s')):
                    norm_word = str(pathlib.Path(word).with_suffix('.o'))
                elif word.endswith(('.o', '.a')):
                    norm_word = word
                else:
                    continue
                try:
                    src_rel = (parent / norm_word).relative_to(main_dir)
                except ValueError:
                    src_rel = pathlib.Path(norm_word)
                if is_stage_var:
                    parts = src_rel.parts
                    if parts and parts[0] == "src":
                        parts = parts[1:]
                    rel = str(pathlib.Path("build") / stage / pathlib.Path(*parts)) if parts else str(pathlib.Path("build") / stage / norm_word)
                else:
                    rel = str(src_rel)
                target_objects[rel] = wcond

    # 2. Read concrete .config generated by defconfig (skip regeneration if
    # defconfig_target is None: the corpus already has a correctly-provisioned .config).
    config_file = root_path / ".config"
    if defconfig_target:
        subprocess.run(["make", defconfig_target], cwd=root_path, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env)

    config_values = {}
    if config_file.exists():
        for line in config_file.read_text(errors='ignore').splitlines():
            line = line.strip()
            if line.startswith("CONFIG_") and "=" in line:
                sym, value = line.split("=", 1)
                config_values[sym] = value

    # 3. Evaluate symbolic presence conditions under concrete active_configs
    zs = zsolver.ZSolver(runner.mysettings)
    solver = z3.Solver()
    
    # Discover symbols from the formulas themselves. Most CONFIG_* references
    # do not appear as Make variable names in state.states.
    eval_model_dict = {}
    target_variables = {}
    for obj, condition in target_objects.items():
        if not isinstance(condition, z3.ExprRef):
            continue
        variables = get_vars(condition)
        target_variables[obj] = variables
        for variable in variables:
            name = str(variable)
            if name.startswith("CONFIG_") and variable not in eval_model_dict:
                zvar, optD = zs.get_sort(name)
                eval_model_dict[zvar] = optD.get(config_values.get(name, ""), optD[""])

    predicted_present = set()
    for obj, cond in target_objects.items():
        if cond is zsolver.T or cond is True:
            predicted_present.add(obj)
        elif isinstance(cond, z3.ExprRef):
            # Substitute concrete values
            substs = [(variable, eval_model_dict[variable]) for variable in target_variables[obj]
                      if variable in eval_model_dict]
            val_expr = z3.substitute(cond, substs)
            val_simp = zsolver.simplify(val_expr)
            if z3.is_true(val_simp) or str(val_simp) == "y":
                predicted_present.add(obj)

    # 4. Extract actual compiled objects (GNU Make dry-run "soft build")
    actual_compiled = extract_compiled_objects_from_make(root_path, defconfig_target, extra_env=extra_env, extra_make_args=extra_make_args)

    # 4b. Physical .o objects actually produced by a real `make -jN` compile
    physical_objs = get_physical_objects(root_path)
    ROOT_DIR = pathlib.Path(__file__).resolve().parent.parent
    evidence_dir = ROOT_DIR / "evidence" / "physical_builds" / corpus_name.replace(" ", "_").replace("(", "").replace(")", "")
    if physical_objs:
        if evidence_dir.exists():
            shutil.rmtree(evidence_dir)
        evidence_dir.mkdir(parents=True, exist_ok=True)
        for rel in physical_objs:
            src = root_path / rel
            dst = evidence_dir / rel
            try:
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
            except OSError:
                pass
        print(f"[+] Archived {len(physical_objs)} physical .o artifacts to {evidence_dir}")

    # 5. Reconcile TP, FP, FN, TN (kfold prediction vs GNU Make dry-run)
    tp = predicted_present & actual_compiled
    fp = predicted_present - actual_compiled
    fn = actual_compiled - predicted_present

    # Filter FN/FP to relevant analyzed directories
    analyzed_parents = {str(kb.makefile.parent.relative_to(main_dir)) for kb in kbuilds if kb.makefile.parent != main_dir}
    filtered_fn = {f for f in fn if any(f.startswith(p + "/") for p in analyzed_parents)}
    filtered_fp = {f for f in fp if not f.startswith("scripts/")}

    precision = len(tp) / max(1, len(tp) + len(filtered_fp)) * 100.0
    recall = len(tp) / max(1, len(tp) + len(filtered_fn)) * 100.0

    print(f"Results for {corpus_name} ({defconfig_target}):")
    print(f"  Predicted Active: {len(predicted_present)}")
    print(f"  Actual Compiled in Scope: {len(tp | filtered_fn)}")
    print(f"  True Positives (TP): {len(tp)}")
    print(f"  False Positives (FP): {len(filtered_fp)}")
    print(f"  False Negatives (FN): {len(filtered_fn)}")
    print(f"  Precision: {precision:.1f}%")
    print(f"  Recall:    {recall:.1f}%")

    result = {
        "corpus": corpus_name,
        "config_target": defconfig_target,
        "total_symbolic_targets": len(target_objects),
        "predicted_present": len(predicted_present),
        "kfold_vs_gmake_dryrun": {
            "tp": len(tp), "fp": len(filtered_fp), "fn": len(filtered_fn),
            "precision_pct": round(precision, 1), "recall_pct": round(recall, 1),
        },
        "sample_fp": list(filtered_fp)[:5],
        "sample_fn": list(filtered_fn)[:5],
        # Backwards-compatible top-level fields (kfold vs GNU Make dry-run)
        "tp": len(tp), "fp": len(filtered_fp), "fn": len(filtered_fn),
        "precision_pct": round(precision, 1), "recall_pct": round(recall, 1),
    }

    # 6. kfold vs physical, and GNU Make dry-run vs physical (only when a real build happened)
    if physical_objs:
        relevant_phys = {f for f in physical_objs if any(f.startswith(p + "/") for p in analyzed_parents) or f in target_objects}

        tp_kp = predicted_present & physical_objs
        fp_kp = predicted_present - physical_objs
        fn_kp = relevant_phys - predicted_present
        prec_kp = len(tp_kp) / max(1, len(tp_kp) + len(fp_kp)) * 100.0
        rec_kp = len(tp_kp) / max(1, len(tp_kp) + len(fn_kp)) * 100.0 if relevant_phys else 0.0

        tp_mp = actual_compiled & physical_objs
        fp_mp = actual_compiled - physical_objs
        fn_mp = relevant_phys - actual_compiled
        prec_mp = len(tp_mp) / max(1, len(tp_mp) + len(fp_mp)) * 100.0
        rec_mp = len(tp_mp) / max(1, len(tp_mp) + len(fn_mp)) * 100.0 if relevant_phys else 0.0

        print(f"  [Physical] .o objects on disk: {len(physical_objs)}")
        print(f"  kfold vs Physical:    Prec={prec_kp:.1f}%, Rec={rec_kp:.1f}% (TP={len(tp_kp)}, FP={len(fp_kp)}, FN={len(fn_kp)})")
        print(f"  GNU Make(-n) vs Phys: Prec={prec_mp:.1f}%, Rec={rec_mp:.1f}% (TP={len(tp_mp)}, FP={len(fp_mp)}, FN={len(fn_mp)})")

        result["physical_objects"] = len(physical_objs)
        result["kfold_vs_physical"] = {
            "tp": len(tp_kp), "fp": len(fp_kp), "fn": len(fn_kp),
            "precision_pct": round(prec_kp, 1), "recall_pct": round(rec_kp, 1),
        }
        result["gmake_dryrun_vs_physical"] = {
            "tp": len(tp_mp), "fp": len(fp_mp), "fn": len(fn_mp),
            "precision_pct": round(prec_mp, 1), "recall_pct": round(rec_mp, 1),
        }

    return result


def main():
    home = str(pathlib.Path.home())
    coreboot_env = {"PATH": f"{home}/.local/bin:" + os.environ.get("PATH", "")}
    coreboot_make_args = ["TOOLCFLAGS=-Wall -Wextra -Wshadow"]

    benchmarks = [
        # (name, root_dir, defconfig_target, extra_env, extra_make_args)
        ("Barebox (Sandbox)", "results/workspaces/barebox/source/barebox-2024.01.0", "sandbox_defconfig", None, None),
        ("Das U-Boot (Sandbox)", "results/workspaces/uboot/source/u-boot-2024.01", "sandbox_defconfig", None, None),
        # BusyBox and coreboot already have a correctly-provisioned .config from their
        # own physical build (no `make X_defconfig` convention to re-run here).
        ("BusyBox", "results/workspaces/busybox/source/busybox-1.36.1", None, None, None),
        ("coreboot (QEMU i440fx)", "results/workspaces/coreboot/source/coreboot-4.22.01/source/coreboot-4.22.01", None, coreboot_env, coreboot_make_args),
    ]

    results = []
    for name, path, cfg, extra_env, extra_make_args in benchmarks:
        if os.path.exists(path):
            r = validate_corpus_build(name, path, cfg, extra_env=extra_env, extra_make_args=extra_make_args)
            results.append(r)

    print("\n\n" + "="*80)
    print("REAL BUILD VALIDATION BENCHMARK RESULTS")
    print("="*80)
    print(json.dumps(results, indent=2))

    with open("results/sandbox_build_validations.json", "w") as f:
        json.dump(results, f, indent=2)


if __name__ == "__main__":
    main()
