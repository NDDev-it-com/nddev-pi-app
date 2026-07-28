#!/usr/bin/env python3
"""Validate public nddev-pi-app contracts without private inputs."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CURRENT_MODULE_ID = "nddev-pi-app"
CURRENT_PACKAGE = "@earendil-works/pi-coding-agent"
CURRENT_REPOSITORY = "https://github.com/earendil-works/pi"
REQUIRED_VERSION_KEYS = {
    "build_version",
    "nddev_builder_package_version",
    "pi_package_bin",
    "pi_coding_agent_tested",
    "pi_command",
    "pi_node_requires",
    "pi_package_name",
    "pi_product_name",
    "pi_registry_integrity",
    "pi_registry_shasum",
    "pi_registry_tarball",
    "python_requires",
    "runtime_baseline_ref",
    "schema_version",
}
SETUP_IDS = ["nddev-builder"]
PROFILE_IDS = ["full-auto", "safe"]
MANAGED_FILES = [
    "agent/settings.json",
    "agent/AGENTS.md",
    "agent/skills/nddev-builder/SKILL.md",
    "agent/packages/nddev-builder/package.json",
    "agent/packages/nddev-builder/skills/nddev-builder/SKILL.md",
]
NPM_VIEW_ARGV = [
    "view",
    "@earendil-works/pi-coding-agent@0.82.1",
    "dist",
    "--json",
]
NPM_PACK_ARGV = [
    "pack",
    "--json",
    "--ignore-scripts",
    "--pack-destination",
    "<stage>/tarballs",
    "@earendil-works/pi-coding-agent@0.82.1",
]
NPM_LOCAL_INSTALL_ARGV = [
    "install",
    "--global-style",
    "--ignore-scripts",
    "--no-audit",
    "--no-fund",
    "--package-lock=false",
    "--prefix",
    "<stage>/install",
    "<verified-tarball>",
]
NPM_INSTALL_ARGV = NPM_LOCAL_INSTALL_ARGV
PI_REGISTRY_INTEGRITY = "sha512-zbkAhoIuDPMF3pKuja0ajZabrMWU29FUMV9A/XMXT/XC1yXs5xt6t6t13GogQFsDrDqbFP4DkZQO1w8rWRAzYA=="
PI_REGISTRY_SHASUM = "39c00809ff5531b6552b9ecb2c41f4c3529ec988"
PI_REGISTRY_TARBALL_URL = (
    "https://registry.npmjs.org/@earendil-works/pi-coding-agent/-/pi-coding-agent-0.82.1.tgz"
)
INSTALLER_ENV = {
    "HOME": "<stage>/home",
    "npm_config_cache": "<stage>/cache",
    "npm_config_ignore_scripts": "true",
    "npm_config_userconfig": "<stage>/npmrc",
    "XDG_CONFIG_HOME": "<stage>/xdg-config",
    "TMPDIR": "<stage>/tmp",
}
BYTE_VERIFICATION = {
    "metadata_integrity": PI_REGISTRY_INTEGRITY,
    "metadata_shasum": PI_REGISTRY_SHASUM,
    "tarball_integrity": PI_REGISTRY_INTEGRITY,
    "tarball_shasum": PI_REGISTRY_SHASUM,
    "verified_before_extract": True,
}
SUPPORTED_HOSTS = ["macos-arm64", "macos-x64", "ubuntu-glibc-arm64", "ubuntu-glibc-x64"]
PACKAGE_ID_PATTERN = re.compile(r"@[A-Za-z0-9._-]+/pi-coding-agent")
REPOSITORY_PATTERN = re.compile(r"https://github\.com/[A-Za-z0-9._-]+/pi\b")
NDDEV_MODULE_PATTERN = re.compile(r"nddev-[a-z0-9-]+-app")


def load_json(relative: str, errors: list[str]) -> dict | None:
    path = ROOT / relative
    if not path.is_file():
        errors.append(f"missing required contract file: {relative}")
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        errors.append(f"{relative}: unreadable or invalid JSON: {exc}")
        return None
    if not isinstance(value, dict):
        errors.append(f"{relative}: top-level value must be an object")
        return None
    return value


def validate_current_identity_only(errors: list[str]) -> None:
    for path in ROOT.rglob("*"):
        if not path.is_file() or ".git" in path.parts:
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for match in PACKAGE_ID_PATTERN.finditer(content):
            if match.group(0) != CURRENT_PACKAGE:
                errors.append(f"{path.relative_to(ROOT)}: unexpected Pi package identity")
        for match in REPOSITORY_PATTERN.finditer(content):
            if match.group(0) != CURRENT_REPOSITORY:
                errors.append(f"{path.relative_to(ROOT)}: unexpected Pi repository identity")
        for match in NDDEV_MODULE_PATTERN.finditer(content):
            if match.group(0) != CURRENT_MODULE_ID:
                errors.append(f"{path.relative_to(ROOT)}: cross-module id {match.group(0)!r}")


def main() -> int:
    errors: list[str] = []
    version = load_json("build/version.json", errors)
    manifest = load_json("build/manifest.json", errors)
    contract = load_json("config/nddev-contract.json", errors)
    baseline = load_json("references/pi-baseline.json", errors)
    builder_package = load_json("builder/nddev-builder/package.json", errors)

    version_text = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    if version is not None:
        missing = REQUIRED_VERSION_KEYS - set(version)
        if missing:
            errors.append(f"build/version.json: missing required keys {sorted(missing)}")
        if version.get("build_version") != version_text:
            errors.append("VERSION and build/version.json:build_version disagree")
        if version.get("pi_package_name") != CURRENT_PACKAGE:
            errors.append("build/version.json: pi_package_name mismatch")
        if version.get("pi_command") != "pi":
            errors.append("build/version.json: pi_command must be pi")
        if version.get("pi_package_bin") != "dist/cli.js":
            errors.append("build/version.json: pi_package_bin mismatch")
        if version.get("pi_node_requires") != ">=22.19.0":
            errors.append("build/version.json: pi_node_requires mismatch")
        if version.get("python_requires") != ">=3.9":
            errors.append("build/version.json: python_requires must include Python 3.9")
        if version.get("pi_registry_integrity") != PI_REGISTRY_INTEGRITY:
            errors.append("build/version.json: pi_registry_integrity mismatch")
        if version.get("pi_registry_shasum") != PI_REGISTRY_SHASUM:
            errors.append("build/version.json: pi_registry_shasum mismatch")
        if version.get("pi_registry_tarball") != PI_REGISTRY_TARBALL_URL:
            errors.append("build/version.json: pi_registry_tarball mismatch")

    if manifest is not None and version is not None:
        if manifest.get("build_version") != version.get("build_version"):
            errors.append("build/manifest.json:build_version disagrees with build/version.json")
        if manifest.get("setup_ids") != SETUP_IDS:
            errors.append("build/manifest.json: unexpected setup_ids")
        if manifest.get("profile_ids") != PROFILE_IDS:
            errors.append("build/manifest.json: unexpected profile_ids")
        if manifest.get("default_setup_id") != "nddev-builder":
            errors.append("build/manifest.json: default_setup_id mismatch")
        if manifest.get("default_profile_id") != "full-auto":
            errors.append("build/manifest.json: default_profile_id mismatch")
        if manifest.get("managed_files") != [*MANAGED_FILES, "NDDEV-PI-SETUP.json"]:
            errors.append("build/manifest.json: managed_files mismatch")
        projection = manifest.get("builder_projection")
        if not isinstance(projection, dict) or projection.get("default_on") is not True:
            errors.append("build/manifest.json: builder_projection.default_on must be true")
        runtime = manifest.get("runtime_launch")
        if (
            not isinstance(runtime, dict)
            or runtime.get("provider_secret_inheritance") != "child-process-allowlist-only"
        ):
            errors.append("build/manifest.json: launch provider inheritance mismatch")
        software = manifest.get("software")
        if not isinstance(software, dict):
            errors.append("build/manifest.json: software contract is missing")
        else:
            if software.get("package") != CURRENT_PACKAGE or software.get("version") != "0.82.1":
                errors.append("build/manifest.json: software package/version mismatch")
            if (
                software.get("bin") != "dist/cli.js"
                or software.get("node_requirement") != ">=22.19.0"
            ):
                errors.append("build/manifest.json: software bin/node mismatch")
            if software.get("registry_tarball") != PI_REGISTRY_TARBALL_URL:
                errors.append("build/manifest.json: software tarball mismatch")
            if software.get("registry_integrity") != PI_REGISTRY_INTEGRITY:
                errors.append("build/manifest.json: software integrity mismatch")
            if software.get("registry_shasum") != PI_REGISTRY_SHASUM:
                errors.append("build/manifest.json: software shasum mismatch")
            installer = software.get("installer")
            if not isinstance(installer, dict):
                errors.append("build/manifest.json: software installer missing")
            elif installer.get("tool") != "npm":
                errors.append("build/manifest.json: software installer tool mismatch")
            elif (
                installer.get("metadata_argv") != NPM_VIEW_ARGV
                or installer.get("pack_argv") != NPM_PACK_ARGV
                or installer.get("local_install_argv") != NPM_LOCAL_INSTALL_ARGV
                or installer.get("argv") != NPM_LOCAL_INSTALL_ARGV
            ):
                errors.append("build/manifest.json: software installer argv mismatch")
            elif installer.get("trust") is not False:
                errors.append("build/manifest.json: software installer trust must be false")
            elif installer.get("byte_verification") != BYTE_VERIFICATION:
                errors.append("build/manifest.json: software installer verification mismatch")
        compatibility = manifest.get("runtime_compatibility")
        if (
            not isinstance(compatibility, dict)
            or compatibility.get("supported_hosts") != SUPPORTED_HOSTS
        ):
            errors.append("build/manifest.json: supported_hosts mismatch")
        transaction = manifest.get("transaction_policy")
        if not isinstance(transaction, dict):
            errors.append("build/manifest.json: transaction_policy missing")
        elif (
            transaction.get("lock") != "monotonic product and canonical target anchors"
            or transaction.get("read_only_lock_creation") is not False
        ):
            errors.append("build/manifest.json: external lock policy mismatch")
        cleanup_journal = (
            transaction.get("cleanup_journal") if isinstance(transaction, dict) else None
        )
        if (
            not isinstance(cleanup_journal, dict)
            or cleanup_journal.get("pending_flag") != "cleanup_pending"
            or cleanup_journal.get("read_only_repairs") is not False
            or cleanup_journal.get("mutation_drains_before_active_change") is not True
        ):
            errors.append("build/manifest.json: cleanup journal policy mismatch")
        backup_policy = manifest.get("backup_policy")
        if (
            not isinstance(backup_policy, dict)
            or backup_policy.get("full_pool_behavior") != "fail-closed"
        ):
            errors.append("build/manifest.json: backup full-pool policy mismatch")

    if contract is not None:
        if contract.get("contract_version") != 2:
            errors.append("config/nddev-contract.json: contract_version must be 2")
        if contract.get("github_repository") != "NDDev-it-com/nddev-pi-app":
            errors.append("config/nddev-contract.json: unexpected github_repository")
        if contract.get("setup_system", {}).get("setup_ids") != SETUP_IDS:
            errors.append("config/nddev-contract.json: setup ids mismatch")
        if contract.get("setup_system", {}).get("profile_ids") != PROFILE_IDS:
            errors.append("config/nddev-contract.json: profile ids mismatch")
        if contract.get("setup_system", {}).get("default_setup_id") != "nddev-builder":
            errors.append("config/nddev-contract.json: default setup mismatch")
        if contract.get("setup_system", {}).get("default_profile_id") != "full-auto":
            errors.append("config/nddev-contract.json: default profile mismatch")
        if contract.get("managed_state", {}).get("managed_files") != MANAGED_FILES:
            errors.append("config/nddev-contract.json: managed files mismatch")
        compatibility = contract.get("runtime_compatibility")
        if (
            not isinstance(compatibility, dict)
            or compatibility.get("supported_hosts") != SUPPORTED_HOSTS
            or compatibility.get("ubuntu_version_floor") is not None
        ):
            errors.append("config/nddev-contract.json: supported host contract mismatch")
        if contract.get("safety", {}).get("backup_full_pool_behavior") != "fail-closed":
            errors.append("config/nddev-contract.json: backup full-pool policy mismatch")
        if contract.get("software", {}).get("package") != CURRENT_PACKAGE:
            errors.append("config/nddev-contract.json: software package mismatch")
        software = contract.get("software", {})
        if software.get("bin") != "dist/cli.js":
            errors.append("config/nddev-contract.json: software bin mismatch")
        if software.get("node_requirement") != ">=22.19.0":
            errors.append("config/nddev-contract.json: software node requirement mismatch")
        if software.get("registry_shasum") != PI_REGISTRY_SHASUM:
            errors.append("config/nddev-contract.json: software shasum mismatch")
        if software.get("registry_integrity") != PI_REGISTRY_INTEGRITY:
            errors.append("config/nddev-contract.json: software integrity mismatch")
        if software.get("registry_tarball") != PI_REGISTRY_TARBALL_URL:
            errors.append("config/nddev-contract.json: software tarball mismatch")
        installer = software.get("installer")
        if not isinstance(installer, dict) or installer.get("tool") != "npm":
            errors.append("config/nddev-contract.json: software installer tool mismatch")
        elif (
            installer.get("metadata_argv") != NPM_VIEW_ARGV
            or installer.get("pack_argv") != NPM_PACK_ARGV
            or installer.get("local_install_argv") != NPM_LOCAL_INSTALL_ARGV
            or installer.get("argv") != NPM_LOCAL_INSTALL_ARGV
        ):
            errors.append("config/nddev-contract.json: software installer argv mismatch")
        elif installer.get("trust") is not False:
            errors.append("config/nddev-contract.json: software installer trust must be false")
        elif installer.get("env") != INSTALLER_ENV:
            errors.append("config/nddev-contract.json: software installer env mismatch")
        elif installer.get("byte_verification") != BYTE_VERIFICATION:
            errors.append("config/nddev-contract.json: software installer verification mismatch")
        tree_policy = software.get("staged_tree_policy")
        if not isinstance(tree_policy, dict):
            errors.append("config/nddev-contract.json: staged tree policy missing")
        elif tree_policy.get("verified_calibration") != (
            "references/pi-baseline.json:manager_installation.verified_tree_calibration"
        ):
            errors.append("config/nddev-contract.json: tree calibration owner mismatch")
        elif tree_policy.get("max_paths_per_tree") != 25000:
            errors.append("config/nddev-contract.json: tree path limit mismatch")
        elif tree_policy.get("max_logical_bytes_per_tree") != 201326592:
            errors.append("config/nddev-contract.json: tree byte limit mismatch")
        entrypoint_materialization = software.get("entrypoint_materialization")
        if not isinstance(entrypoint_materialization, dict):
            errors.append("config/nddev-contract.json: entrypoint materialization missing")
        elif entrypoint_materialization != {
            "npm_source": "<stage>/install/bin/pi",
            "required_package_target": (
                "<stage>/install/lib/node_modules/@earendil-works/pi-coding-agent/dist/cli.js"
            ),
            "persisted_kind": "private-relative-node-wrapper",
            "persisted_path": ".nddev-pi-software/current/bin/pi",
            "persisted_mode": "0700",
            "persisted_symlink": False,
        }:
            errors.append("config/nddev-contract.json: entrypoint materialization mismatch")
        version_identity = software.get("version_identity")
        if version_identity != {
            "required_package_version": "0.82.1",
            "package_version_source": (
                ".nddev-pi-software/current/install/lib/node_modules/"
                "@earendil-works/pi-coding-agent/package.json"
            ),
            "probe_argv": ["bin/pi", "--version"],
            "expected_probe_output": "0.0.0",
            "package_and_probe_must_both_match": True,
        }:
            errors.append("config/nddev-contract.json: version identity mismatch")
        target_owned = software.get("target_owned")
        if (
            not isinstance(target_owned, dict)
            or target_owned.get("status_executes_target_binary") is not False
        ):
            errors.append("config/nddev-contract.json: software status must be side-effect free")
        coordination = contract.get("safety", {}).get("external_lifecycle_coordination")
        if not isinstance(coordination, dict):
            errors.append("config/nddev-contract.json: external coordination contract missing")
        elif (
            coordination.get("read_only_creates_anchors") is not False
            or coordination.get("mutation_publishes_missing_target_anchor") is not True
            or coordination.get("published_anchors_unlinked_by_lifecycle") is not False
        ):
            errors.append("config/nddev-contract.json: external coordination policy mismatch")
        cleanup = contract.get("safety", {}).get("cleanup_journal")
        if (
            not isinstance(cleanup, dict)
            or cleanup.get("pending_flag") != "cleanup_pending"
            or cleanup.get("read_only_repairs") is not False
            or cleanup.get("mutation_drains_before_active_change") is not True
            or cleanup.get("absolute_paths_in_documents") is not False
        ):
            errors.append("config/nddev-contract.json: cleanup journal policy mismatch")
        marketplace = contract.get("builder_projection", {}).get("marketplace", {})
        if marketplace.get("external_marketplace_published") is not None:
            errors.append("config/nddev-contract.json: external marketplace must remain null")
        if contract.get("builder_projection", {}).get("surfaces") != [
            "settings.skills",
            "settings.packages",
            "package.pi.skills",
            "agent.AGENTS.md",
        ]:
            errors.append("config/nddev-contract.json: builder surfaces mismatch")

    if baseline is not None:
        if version is not None and baseline.get("package", {}).get("version") != version.get(
            "pi_coding_agent_tested"
        ):
            errors.append("references/pi-baseline.json: package version disagrees with version")
        if baseline.get("package", {}).get("name") != CURRENT_PACKAGE:
            errors.append("references/pi-baseline.json: package name mismatch")
        if baseline.get("cli_identity", {}).get("command") != "pi":
            errors.append("references/pi-baseline.json: CLI command must be pi")
        if baseline.get("cli_identity", {}).get("version_probe") != {
            "argv": ["pi", "--version"],
            "expected_stdout": "0.0.0",
            "package_version_source": "package.version",
            "independent_package_identity_required": True,
        }:
            errors.append("references/pi-baseline.json: CLI version probe mismatch")
        package = baseline.get("package", {})
        if package.get("integrity") != PI_REGISTRY_INTEGRITY:
            errors.append("references/pi-baseline.json: package integrity mismatch")
        if package.get("shasum") != PI_REGISTRY_SHASUM:
            errors.append("references/pi-baseline.json: package shasum mismatch")
        if package.get("tarball") != PI_REGISTRY_TARBALL_URL:
            errors.append("references/pi-baseline.json: package tarball mismatch")
        manager_installation = baseline.get("manager_installation", {})
        if manager_installation.get("tool") != "npm":
            errors.append("references/pi-baseline.json: manager installation tool mismatch")
        if (
            manager_installation.get("metadata_argv") != NPM_VIEW_ARGV
            or manager_installation.get("pack_argv") != NPM_PACK_ARGV
            or manager_installation.get("local_install_argv") != NPM_LOCAL_INSTALL_ARGV
            or manager_installation.get("argv") != NPM_LOCAL_INSTALL_ARGV
        ):
            errors.append("references/pi-baseline.json: manager installation argv mismatch")
        if manager_installation.get("trust") is not False:
            errors.append("references/pi-baseline.json: manager installation trust must be false")
        if manager_installation.get("staging_environment") != INSTALLER_ENV:
            errors.append("references/pi-baseline.json: manager staging environment mismatch")
        if manager_installation.get("byte_verification") != BYTE_VERIFICATION:
            errors.append("references/pi-baseline.json: manager byte verification mismatch")
        calibration = manager_installation.get("verified_tree_calibration")
        if calibration != {
            "verified_at": "2026-07-27",
            "npm_version": None,
            "staged_global_tree": {
                "path_count": 20873,
                "logical_file_bytes": 118702032,
            },
            "staged_bin_tree": {
                "path_count": 1,
                "logical_file_bytes": 681,
            },
            "protective_limits": {
                "max_paths_per_tree": 25000,
                "max_logical_bytes_per_tree": 201326592,
            },
        }:
            errors.append("references/pi-baseline.json: tree calibration mismatch")
        lifecycle = manager_installation.get("consumer_lifecycle_scripts", {})
        if (
            lifecycle.get("preinstall") is not None
            or lifecycle.get("install") is not None
            or lifecycle.get("postinstall") is not None
        ):
            errors.append("references/pi-baseline.json: consumer lifecycle scripts must be null")
        permission_model = baseline.get("permission_model", {})
        if permission_model.get("permission_popups") is not False:
            errors.append("references/pi-baseline.json: permission popups must be false")

    setup_ids: list[str] = []
    for setup_dir in sorted((ROOT / "setups").iterdir()):
        if not setup_dir.is_dir():
            continue
        setup = load_json(f"setups/{setup_dir.name}/setup.json", errors)
        settings = load_json(f"setups/{setup_dir.name}/settings.json", errors)
        if setup is not None:
            if setup.get("id") != setup_dir.name:
                errors.append(f"setups/{setup_dir.name}/setup.json: id mismatch")
            if setup.get("managed_files") != MANAGED_FILES:
                errors.append(f"setups/{setup_dir.name}/setup.json: managed_files mismatch")
            if setup.get("builder_projection") != "default-on":
                errors.append(f"setups/{setup_dir.name}/setup.json: builder must be default-on")
            setup_ids.append(setup_dir.name)
        if settings is not None:
            if settings.get("enableSkillCommands") is not True:
                errors.append(f"setups/{setup_dir.name}/settings.json: skills must be enabled")
            if settings.get("enableInstallTelemetry") is not False:
                errors.append(
                    f"setups/{setup_dir.name}/settings.json: install telemetry must be false"
                )
            if settings.get("enableAnalytics") is not False:
                errors.append(f"setups/{setup_dir.name}/settings.json: analytics must be false")
            if settings.get("nddev", {}).get("setup_id") != setup_dir.name:
                errors.append(f"setups/{setup_dir.name}/settings.json: nddev setup id mismatch")

    if setup_ids != SETUP_IDS:
        errors.append(f"setups/: unexpected setup directories {setup_ids}")

    profile_ids: list[str] = []
    profile_defaults: list[str] = []
    for profile_dir in sorted((ROOT / "profiles").iterdir()):
        if not profile_dir.is_dir():
            continue
        profile = load_json(f"profiles/{profile_dir.name}/profile.json", errors)
        if profile is None:
            continue
        if profile.get("id") != profile_dir.name:
            errors.append(f"profiles/{profile_dir.name}/profile.json: id mismatch")
        if profile.get("os_security_boundary") is not False:
            errors.append(f"profiles/{profile_dir.name}/profile.json: false OS boundary required")
        if not isinstance(profile.get("launch_args"), list):
            errors.append(f"profiles/{profile_dir.name}/profile.json: launch_args missing")
        if profile.get("default") is True:
            profile_defaults.append(profile_dir.name)
        profile_ids.append(profile_dir.name)
    if profile_ids != PROFILE_IDS:
        errors.append(f"profiles/: unexpected profile directories {profile_ids}")
    if profile_defaults != ["full-auto"]:
        errors.append("profiles/: full-auto must be the only default profile")

    if builder_package is not None and version is not None:
        if builder_package.get("name") != "nddev-builder":
            errors.append("builder package: name must be nddev-builder")
        if builder_package.get("version") != version.get("nddev_builder_package_version"):
            errors.append("builder package: version disagrees with build/version.json")
        if builder_package.get("pi", {}).get("skills") != ["skills/nddev-builder"]:
            errors.append("builder package: missing pi.skills projection")
    if not (ROOT / "builder/nddev-builder/skills/nddev-builder/SKILL.md").is_file():
        errors.append("missing builder skill source")
    if not (ROOT / "builder/nddev-builder/AGENTS.md").is_file():
        errors.append("missing builder AGENTS source")

    validate_current_identity_only(errors)

    if errors:
        print(f"validate_public_contracts.py: FAIL ({len(errors)} error(s))")
        for error in errors:
            print(f"  - {error}")
        return 1
    print("validate_public_contracts.py: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
