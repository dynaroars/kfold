from autokernel.smartconfig import parse_config
from autokernel.smartconfig import check
from autokernel.smartconfig import plan
from autokernel.smartconfig import diagnose, upgrade
from autokernel.capabilities import recipe_requirements, validate_recipes
from autokernel.history import import_modules
from autokernel.artifacts import inventory, vm_validation
from autokernel.mapping import build_mapping


def test_config_parser_preserves_duplicates_and_disabled_values():
    parsed = parse_config(
        "CONFIG_PARENT=y\nCONFIG_PARENT=n\n# CONFIG_CHILD is not set\n"
    )
    assert parsed.values == {"CONFIG_PARENT": "n", "CONFIG_CHILD": "n"}
    assert list(parsed.duplicates) == ["CONFIG_PARENT"]


def test_config_parser_keeps_unknown_input_lines():
    parsed = parse_config("CONFIG_OK=y\nthis is not kconfig\n")
    assert parsed.unknown_lines == [(2, "this is not kconfig")]


def test_native_fixture_catches_effective_requirement_violation(tmp_path):
    fixture = __import__("pathlib").Path(__file__).parent / "fixtures" / "smartconfig_kernel"
    report = check(
        source=fixture,
        baseline=fixture / "baseline.config",
        candidate=fixture / "candidate.config",
        requirements=fixture / "requirements.json",
        out=tmp_path / "run",
        arch="x86_64",
    )
    assert report["status"] == "violation"
    assert report["candidate"]["violations"]
    assert (tmp_path / "run" / "report.json").exists()


def test_builtin_capability_catalog_is_valid_and_versioned():
    assert validate_recipes() == []
    requirements = recipe_requirements(["wireguard", "overlayfs", "root-storage"])
    assert [r["id"] for r in requirements] == ["wireguard", "overlayfs", "root-storage"]
    assert all(r["origin"] == "user" and r["recipe_version"] == "1" for r in requirements)


def test_plan_blocks_removal_that_breaks_requirement(tmp_path):
    fixture = __import__("pathlib").Path(__file__).parent / "fixtures" / "smartconfig_kernel"
    result = plan(source=fixture, baseline=fixture / "baseline.config",
                  requirements=fixture / "requirements.json", out=tmp_path / "plan",
                  removals=["PARENT"], arch="x86_64")
    assert result["status"] == "blocked"
    assert not (tmp_path / "plan" / "effective.config").exists()
    assert "CONFIG_PARENT" in (tmp_path / "plan" / "requested.config").read_text()


def test_plan_exports_effective_config_when_requirements_pass(tmp_path):
    fixture = __import__("pathlib").Path(__file__).parent / "fixtures" / "smartconfig_kernel"
    result = plan(source=fixture, baseline=fixture / "baseline.config",
                  requirements=fixture / "requirements.json", out=tmp_path / "plan",
                  removals=[], arch="x86_64")
    assert result["status"] == "checked"
    effective = tmp_path / "plan" / "effective.config"
    assert effective.exists()
    assert "CONFIG_CHILD=y" in effective.read_text()


def test_plan_records_history_provenance(tmp_path):
    fixture = __import__("pathlib").Path(__file__).parent / "fixtures" / "smartconfig_kernel"
    history = tmp_path / "history.json"
    history.write_text('{"source": "modules", "source_hash": "abc", "observed_modules": ["x"], "coverage": {"absence_means": "unknown"}}')
    result = plan(source=fixture, baseline=fixture / "baseline.config",
                  requirements=fixture / "requirements.json", out=tmp_path / "plan",
                  removals=[], arch="x86_64", history=history)
    assert result["history"]["source_hash"] == "abc"
    assert result["history"]["absence_means"] == "unknown"


def test_history_import_preserves_unknown_absence_semantics(tmp_path):
    source = tmp_path / "modules.txt"
    source.write_text("overlayfs\nusb-storage.ko\n# comment\n")
    record = import_modules(source)
    assert record["observed_modules"] == ["overlayfs", "usb_storage"]
    assert record["coverage"]["absence_means"] == "unknown"


def test_diagnosis_is_bounded_and_does_not_claim_minimality(tmp_path):
    fixture = __import__("pathlib").Path(__file__).parent / "fixtures" / "smartconfig_kernel"
    result = diagnose(source=fixture, good=fixture / "baseline.config",
                      bad=fixture / "candidate.config", requirements=fixture / "requirements.json",
                      out=tmp_path / "diagnosis", test_command=None, arch="x86_64")
    assert result["status"] == "unknown"
    assert "not globally minimal" in result["claim"]
    assert result["changed_symbols"] == ["CONFIG_PARENT"]


def test_upgrade_reports_effective_delta_and_rechecks_requirements(tmp_path):
    fixture = __import__("pathlib").Path(__file__).parent / "fixtures" / "smartconfig_kernel"
    result = upgrade(old_source=fixture, new_source=fixture,
                     config=fixture / "baseline.config",
                     requirements=fixture / "requirements.json",
                     out=tmp_path / "upgrade", arch="x86_64")
    assert result["status"] == "pass"
    assert result["removed_symbols"] == []
    assert result["changed_effective_values"] == []


def test_artifact_inventory_is_hash_bound(tmp_path):
    fixture = __import__("pathlib").Path(__file__).parent / "fixtures" / "smartconfig_kernel"
    config = tmp_path / "final.config"
    config.write_text("CONFIG_PARENT=y\n")
    result = inventory(fixture, config)
    assert result["config"]["sha256"]
    assert result["kernelrelease"] == "unknown"


def test_vm_validation_reports_missing_qemu_as_skip(tmp_path):
    result = vm_validation(tmp_path / "missing-bzImage", tmp_path / "validation.json")
    assert result["status"] == "skip"
    assert result["cleanup"] == "not_applicable"


def test_target_predicate_skips_nonmatching_requirement(tmp_path):
    fixture = __import__("pathlib").Path(__file__).parent / "fixtures" / "smartconfig_kernel"
    requirements = tmp_path / "requirements.json"
    requirements.write_text('{"requirements": [{"id": "arm-only", "target": {"arch": "arm64"}, "condition": {"symbol": "MISSING", "equals": "y"}}]}')
    result = check(source=fixture, baseline=fixture / "baseline.config", candidate=fixture / "baseline.config", requirements=requirements, out=tmp_path / "run", arch="x86_64")
    assert result["status"] == "pass"
    assert result["findings"][0]["severity"] == "skip"


def test_embedded_recipe_execution_is_rejected(tmp_path):
    fixture = __import__("pathlib").Path(__file__).parent / "fixtures" / "smartconfig_kernel"
    requirements = tmp_path / "requirements.json"
    requirements.write_text('{"requirements": [{"id": "unsafe", "shell": "echo bad", "condition": {"symbol": "PARENT", "equals": "y"}}]}')
    import pytest
    with pytest.raises(ValueError, match="embedded execution"):
        check(source=fixture, baseline=fixture / "baseline.config", candidate=fixture / "baseline.config", requirements=requirements, out=tmp_path / "run", arch="x86_64")


def test_mapping_is_target_scoped_and_explicit_about_introspection():
    fixture = __import__("pathlib").Path(__file__).parent / "fixtures" / "smartconfig_kernel"
    result = build_mapping(fixture, ["overlayfs"])
    assert result["target_identity"]
    assert result["records"][0]["symbols"] == ["CONFIG_OVERLAY_FS"]
    assert result["records"][0]["completeness"] in {"complete", "unknown"}
