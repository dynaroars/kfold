#!/usr/bin/env python3
"""Ablation of kfold's design elements against the physical builds.

Runs tools/evaluate_physical.py once per subject and variant:

  no_includes        include directives are not spliced (KFOLD_NO_INCLUDES)
  no_rules           no rule-prerequisite closure (KFOLD_NO_RULES)
  no_link_semantics  built-in composite containers and need-builtin ignored
                     (KFOLD_NO_LINK_SEMANTICS)
  original_settings  the entry-point settings used before this study
                     (results/ablation_settings/*.ini, via KFOLD_SETTINGS_FILE)

The "no composite members" variant is the ``targets`` column of the main
results/physical_validation.json. Writes results/ablation.json.
"""
import json
import os
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
SETTINGS = {
    "Linux": "linux_skbuild.ini",
    "Das U-Boot": "uboot_skbuild.ini",
    "Barebox": "barebox_skbuild.ini",
    "coreboot": "coreboot_skbuild.ini",
}


def run(subject, env_extra, out):
    env = dict(os.environ, **env_extra)
    subprocess.run([sys.executable, str(ROOT / "tools" / "evaluate_physical.py"),
                    "--subjects", subject, "--out", str(out)],
                   env=env, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return json.loads(out.read_text())[0]


def summary(entry):
    return {p: {k: v["members"][k] for k in (
                "universe", "predicted", "tp", "fp", "fn_within_universe",
                "outside_universe", "precision_pct", "overlap_pct")}
            for p, v in entry["profiles"].items()}


def main():
    results = {}
    tmp = ROOT / "results" / "ablation_tmp.json"
    for subject, ini in SETTINGS.items():
        results[subject] = {}
        variants = {
            "no_includes": {"KFOLD_NO_INCLUDES": "1"},
            "no_rules": {"KFOLD_NO_RULES": "1"},
            "no_link_semantics": {"KFOLD_NO_LINK_SEMANTICS": "1"},
            "original_settings": {"KFOLD_SETTINGS_FILE":
                                  str(ROOT / "results" / "ablation_settings" / ini)},
        }
        for name, env in variants.items():
            entry = run(subject, env, tmp)
            results[subject][name] = {"makefile_instances": entry["makefile_instances"],
                                      "profiles": summary(entry)}
            print(subject, name, json.dumps(results[subject][name]), flush=True)
    tmp.unlink(missing_ok=True)
    (ROOT / "results" / "ablation.json").write_text(json.dumps(results, indent=1))
    print("wrote results/ablation.json")


if __name__ == "__main__":
    main()
