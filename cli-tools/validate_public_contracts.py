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
    "pi_coding_agent_tested",
    "pi_command",
    "pi_node_requires",
    "pi_package_name",
    "pi_product_name",
    "python_requires",
    "runtime_baseline_ref",
    "schema_version",
}
SETUP_IDS = ["balanced", "full-auto", "safe"]
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

    if manifest is not None and version is not None:
        if manifest.get("build_version") != version.get("build_version"):
            errors.append("build/manifest.json:build_version disagrees with build/version.json")
        if manifest.get("setup_ids") != SETUP_IDS:
            errors.append("build/manifest.json: unexpected setup_ids")
        projection = manifest.get("builder_projection")
        if not isinstance(projection, dict) or projection.get("default_on") is not True:
            errors.append("build/manifest.json: builder_projection.default_on must be true")
        runtime = manifest.get("runtime_launch")
        if not isinstance(runtime, dict) or runtime.get("provider_secret_inheritance") is not False:
            errors.append("build/manifest.json: launch must not inherit provider secrets")

    if contract is not None:
        if contract.get("contract_version") != 2:
            errors.append("config/nddev-contract.json: contract_version must be 2")
        if contract.get("github_repository") != "NDDev-it-com/nddev-pi-app":
            errors.append("config/nddev-contract.json: unexpected github_repository")
        if "skeleton" in contract:
            errors.append("config/nddev-contract.json: skeleton must be removed")
        if contract.get("setup_system", {}).get("setup_ids") != SETUP_IDS:
            errors.append("config/nddev-contract.json: setup ids mismatch")
        if contract.get("software", {}).get("package") != CURRENT_PACKAGE:
            errors.append("config/nddev-contract.json: software package mismatch")
        marketplace = contract.get("builder_projection", {}).get("marketplace", {})
        if marketplace.get("external_marketplace_published") is not None:
            errors.append("config/nddev-contract.json: external marketplace must remain null")
        if contract.get("builder_projection", {}).get("surfaces") != [
            "settings.skills",
            "package.skills",
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
            if setup.get("managed_files") != ["agent/settings.json"]:
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

    if builder_package is not None and version is not None:
        if builder_package.get("name") != "nddev-builder":
            errors.append("builder package: name must be nddev-builder")
        if builder_package.get("version") != version.get("nddev_builder_package_version"):
            errors.append("builder package: version disagrees with build/version.json")
        if builder_package.get("pi", {}).get("skills") != ["skills/nddev-builder"]:
            errors.append("builder package: missing pi.skills projection")
    if not (ROOT / "builder/nddev-builder/skills/nddev-builder/SKILL.md").is_file():
        errors.append("missing builder skill source")

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
