#!/usr/bin/env python3
"""Validate public nddev-pi-app contracts without private inputs."""

from __future__ import annotations

import importlib.util
import contextlib
import io
import json
import os
import re
import stat
import sys
import tempfile
from pathlib import Path

sys.dont_write_bytecode = True

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
LAUNCH_WORKSPACE_REQUIREMENTS = [
    "absolute",
    "existing-directory",
    "final-component-not-symlink",
    "accessible",
]
LAUNCH_BLOCKED_SCOPE_OVERRIDES = [
    "--workspace",
    "--project",
    "--project-dir",
    "--project-directory",
    "--cwd",
    "--workdir",
    "--working-directory",
    "--directory",
    "--dir",
    "-C",
]
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


def validate_npm_json_output_bound(errors: list[str]) -> None:
    manager = ROOT / "cli-tools" / "nddev_pi.py"
    try:
        content = manager.read_text(encoding="utf-8")
    except OSError as exc:
        errors.append(f"cli-tools/nddev_pi.py: cannot read manager source: {exc}")
        return
    if "NPM_JSON_OUTPUT_MAX_BYTES = 1024 * 1024" not in content:
        errors.append("cli-tools/nddev_pi.py: missing bounded npm JSON output limit")
    if "max_bytes=NPM_JSON_OUTPUT_MAX_BYTES" not in content:
        errors.append("cli-tools/nddev_pi.py: npm JSON parser must use the npm output limit")
    if "truncate=False" not in content:
        errors.append("cli-tools/nddev_pi.py: npm JSON parser must fail instead of truncating")


def validate_cold_read_coordination(errors: list[str]) -> None:
    manager = ROOT / "cli-tools" / "nddev_pi.py"
    try:
        content = manager.read_text(encoding="utf-8")
    except OSError as exc:
        errors.append(f"cli-tools/nddev_pi.py: cannot read manager source: {exc}")
        return
    required_fragments = [
        "LOCK_NAMESPACE_SCAN_ENTRY_LIMIT",
        "cold_product_namespace_snapshot",
        "product publication alias exists without product coordination anchor",
        "target anchor exists without product coordination anchor",
        "RetryColdInspection",
        "product coordination changed during cold read",
        "return read_only_target(target, build)",
    ]
    for fragment in required_fragments:
        if fragment not in content:
            errors.append(f"cli-tools/nddev_pi.py: missing cold-read guard {fragment!r}")


def validate_software_rollback_identity(errors: list[str]) -> None:
    manager = ROOT / "cli-tools" / "nddev_pi.py"
    try:
        content = manager.read_text(encoding="utf-8")
    except OSError as exc:
        errors.append(f"cli-tools/nddev_pi.py: cannot read manager source: {exc}")
        return
    required_fragments = [
        "cleanup_replacement",
        "prepare_cleanup_intent",
        "move_cleanup_sources_to_tombstones",
        "restore_cleanup_entries_from_tombstones",
        "desired_software_state_is_current",
        "software.current.rename.after",
        "software.entrypoint.rename.after",
        "software.stamp.rename.after",
    ]
    for fragment in required_fragments:
        if fragment not in content:
            errors.append(f"cli-tools/nddev_pi.py: missing software rollback guard {fragment!r}")
    forbidden_fragments = ["def snapshot_software_file", "def restore_software_file"]
    for fragment in forbidden_fragments:
        if fragment in content:
            errors.append(f"cli-tools/nddev_pi.py: stale byte-copy rollback helper {fragment!r}")


def validate_external_anchor_recovery(errors: list[str]) -> None:
    manager = ROOT / "cli-tools" / "nddev_pi.py"
    try:
        content = manager.read_text(encoding="utf-8")
    except OSError as exc:
        errors.append(f"cli-tools/nddev_pi.py: cannot read manager source: {exc}")
        return
    required_fragments = [
        "anchor_stage_paths",
        "validate_anchor_stage",
        "validate_anchor_stage_binding",
        "external lock pre-publication stage exists without final anchor",
        "external lock pre-publication stage requires exclusive recovery",
        "lock.{expected['kind']}.stage.final.visible",
        "lock.{expected['kind']}.stage.unlink",
        "external lock pre-publication stage binding mismatch",
        "parent_metadata_before_temp = directory_metadata(parent, \"external lock parent\")",
        "restore_directory_metadata(\n                parent,",
        "system_root_metadata = directory_metadata(",
        "restore_directory_metadata(\n                        bootstrap_system_temp_root()",
    ]
    for fragment in required_fragments:
        if fragment not in content:
            errors.append(f"cli-tools/nddev_pi.py: missing anchor recovery guard {fragment!r}")
    forbidden_fragments = [
        "external lock pre-publication stage state is ambiguous",
        "if len(stages) > 1:",
    ]
    for fragment in forbidden_fragments:
        if fragment in content:
            errors.append(f"cli-tools/nddev_pi.py: stale single-stage recovery guard {fragment!r}")


def validate_external_anchor_behavior(errors: list[str]) -> None:
    manager = ROOT / "cli-tools" / "nddev_pi.py"
    name = "nddev_pi_public_validator_anchor"
    try:
        spec = importlib.util.spec_from_file_location(name, manager)
        if spec is None or spec.loader is None:
            errors.append("cli-tools/nddev_pi.py: cannot load manager module spec")
            return
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory(prefix="nddev-pi-public-anchor.") as tmp:
            parent = Path(tmp) / "locks"
            parent.mkdir(mode=module.OWNER_DIRECTORY_MODE)
            final = parent / "global.lock"
            binding = module.anchor_binding("product")
            content = module.canonical_json(binding)
            stages: list[Path] = []
            for suffix in ("000001.aaa", "000002.bbb", "000003.ccc"):
                stage = parent / f"{module.LOCK_TEMP_PREFIX}{suffix}.tmp"
                descriptor = os.open(
                    stage, os.O_WRONLY | os.O_CREAT | os.O_EXCL, module.OWNER_FILE_MODE
                )
                try:
                    os.write(descriptor, content)
                    os.fsync(descriptor)
                finally:
                    os.close(descriptor)
                stages.append(stage)
            try:
                module.ensure_anchor(final, binding, exclusive=False, create=False, recover_alias=False)
            except module.PiSetupError as exc:
                if "pre-publication stage exists without final anchor" not in str(exc):
                    errors.append(f"cli-tools/nddev_pi.py: unexpected read-only stage error: {exc}")
                    return
            else:
                errors.append("cli-tools/nddev_pi.py: read-only accepted pre-publication stages")
                return
            stage_snapshots = [
                (stage.name, stage.lstat().st_ino, stage.lstat().st_mtime_ns, stage.read_bytes())
                for stage in stages
            ]
            if len(stage_snapshots) != 3:
                errors.append("cli-tools/nddev_pi.py: read-only mutated pre-publication stages")
                return
            lock = module.ensure_anchor(final, binding, exclusive=True, create=True, recover_alias=True)
            try:
                final_info = final.lstat()
                if stat.S_IMODE(final_info.st_mode) != module.OWNER_FILE_MODE:
                    errors.append("cli-tools/nddev_pi.py: recovered anchor mode is not 0600")
                if final_info.st_nlink != 1:
                    errors.append("cli-tools/nddev_pi.py: recovered anchor has publication aliases")
                if final.read_bytes() != content:
                    errors.append("cli-tools/nddev_pi.py: recovered anchor binding changed")
                if any(stage.exists() for stage in stages):
                    errors.append("cli-tools/nddev_pi.py: exclusive recovery left stage residue")
            finally:
                module.close_external_lock(lock)
        with tempfile.TemporaryDirectory(prefix="nddev-pi-public-anchor-mismatch.") as tmp:
            parent = Path(tmp) / "locks"
            parent.mkdir(mode=module.OWNER_DIRECTORY_MODE)
            final = parent / "global.lock"
            binding = module.anchor_binding("product")
            target_binding = module.anchor_binding("target", Path(tmp) / "target")
            stages = []
            for suffix, stage_binding in (
                ("000004.ddd", binding),
                ("000005.eee", target_binding),
            ):
                stage = parent / f"{module.LOCK_TEMP_PREFIX}{suffix}.tmp"
                descriptor = os.open(
                    stage, os.O_WRONLY | os.O_CREAT | os.O_EXCL, module.OWNER_FILE_MODE
                )
                try:
                    os.write(descriptor, module.canonical_json(stage_binding))
                    os.fsync(descriptor)
                finally:
                    os.close(descriptor)
                stages.append(stage)
            before = [
                (stage.name, stage.lstat().st_ino, stage.lstat().st_mtime_ns, stage.read_bytes())
                for stage in stages
            ]
            try:
                module.ensure_anchor(final, binding, exclusive=True, create=True, recover_alias=True)
            except module.PiSetupError as exc:
                if "pre-publication stage binding mismatch" not in str(exc):
                    errors.append(f"cli-tools/nddev_pi.py: unexpected mismatched stage error: {exc}")
                    return
            else:
                errors.append("cli-tools/nddev_pi.py: mismatched pre-publication stage was skipped")
                return
            after = [
                (stage.name, stage.lstat().st_ino, stage.lstat().st_mtime_ns, stage.read_bytes())
                for stage in stages
            ]
            if before != after or final.exists():
                errors.append("cli-tools/nddev_pi.py: mismatched stage failure mutated namespace")
        with tempfile.TemporaryDirectory(prefix="nddev-pi-public-anchor-winner.") as tmp:
            parent = Path(tmp) / "locks"
            parent.mkdir(mode=module.OWNER_DIRECTORY_MODE)
            final = parent / "global.lock"
            binding = module.anchor_binding("product")
            content = module.canonical_json(binding)
            selected = parent / f"{module.LOCK_TEMP_PREFIX}000006.fff.tmp"
            winner = parent / f"{module.LOCK_TEMP_PREFIX}000007.abc.tmp"
            for stage in (selected, winner):
                descriptor = os.open(
                    stage, os.O_WRONLY | os.O_CREAT | os.O_EXCL, module.OWNER_FILE_MODE
                )
                try:
                    os.write(descriptor, content)
                    os.fsync(descriptor)
                finally:
                    os.close(descriptor)
            original_link = module.os.link
            raced = False

            def racing_link(source: Path, destination: Path) -> None:
                nonlocal raced
                if Path(source) == selected and Path(destination) == final and not raced:
                    raced = True
                    selected.unlink()
                    original_link(winner, final)
                    raise FileNotFoundError(str(source))
                original_link(source, destination)

            module.os.link = racing_link
            lock = None
            try:
                lock = module.ensure_anchor(
                    final, binding, exclusive=True, create=True, recover_alias=True
                )
                if not raced:
                    errors.append("cli-tools/nddev_pi.py: concurrent winner smoke did not race")
                final_info = final.lstat()
                if stat.S_IMODE(final_info.st_mode) != module.OWNER_FILE_MODE:
                    errors.append("cli-tools/nddev_pi.py: concurrent winner mode is not 0600")
                if final_info.st_nlink != 1:
                    errors.append("cli-tools/nddev_pi.py: concurrent winner alias was not drained")
                if final.read_bytes() != content:
                    errors.append("cli-tools/nddev_pi.py: concurrent winner binding changed")
                if selected.exists() or winner.exists():
                    errors.append("cli-tools/nddev_pi.py: concurrent winner left stage residue")
            finally:
                module.os.link = original_link
                module.close_external_lock(lock)
    except Exception as exc:  # pragma: no cover - validator reports instead of crashing
        errors.append(f"cli-tools/nddev_pi.py: anchor behavior check failed: {exc}")
    finally:
        sys.modules.pop(name, None)


def validate_cleanup_metadata_behavior(errors: list[str]) -> None:
    manager = ROOT / "cli-tools" / "nddev_pi.py"
    name = "nddev_pi_public_validator_cleanup_metadata"
    try:
        spec = importlib.util.spec_from_file_location(name, manager)
        if spec is None or spec.loader is None:
            errors.append("cli-tools/nddev_pi.py: cannot load manager module spec")
            return
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory(prefix="nddev-pi-public-cleanup-metadata.") as tmp:
            root = Path(tmp) / "tree"
            child_dir = root / "child"
            child_file = child_dir / "payload.txt"
            child_dir.mkdir(parents=True, mode=module.OWNER_DIRECTORY_MODE)
            child_file.write_text("payload", encoding="utf-8")
            child_file.chmod(module.OWNER_FILE_MODE)
            snapshot = module.snapshot_cleanup_tree(root, "metadata smoke tree")
            os.utime(child_dir, ns=(1660000000000000000, 1660000000000000000))
            tampered = (
                child_dir.lstat().st_ino,
                child_dir.lstat().st_mtime_ns,
                child_file.read_text(encoding="utf-8"),
            )
            try:
                module.validate_cleanup_tree(root, snapshot, "metadata smoke tree")
            except module.PiSetupError as exc:
                if "identity mismatch" not in str(exc):
                    errors.append(f"cli-tools/nddev_pi.py: unexpected metadata tamper error: {exc}")
                    return
            else:
                errors.append("cli-tools/nddev_pi.py: directory metadata tamper was accepted")
                return
            after_tamper = (
                child_dir.lstat().st_ino,
                child_dir.lstat().st_mtime_ns,
                child_file.read_text(encoding="utf-8"),
            )
            if after_tamper != tampered:
                errors.append("cli-tools/nddev_pi.py: metadata tamper validation mutated state")
        with tempfile.TemporaryDirectory(prefix="nddev-pi-public-cleanup-parent.") as tmp:
            parent = Path(tmp) / "parent"
            parent.mkdir(mode=module.OWNER_DIRECTORY_MODE)
            os.utime(parent, ns=(1550000000000000000, 1550000000000000000))
            before = module.directory_metadata(parent, "metadata smoke parent")
            parent.chmod(0o755)
            os.utime(parent, ns=(1560000000000000000, 1560000000000000000))
            module.restore_directory_metadata(parent, before, "metadata smoke parent")
            after = module.directory_metadata(parent, "metadata smoke parent")
            if after != before:
                errors.append("cli-tools/nddev_pi.py: parent metadata restore did not restore exact state")
        with tempfile.TemporaryDirectory(prefix="nddev-pi-public-cleanup-failure.") as tmp:
            parent = Path(tmp) / "cleanup"
            parent.mkdir(mode=module.OWNER_DIRECTORY_MODE)
            os.utime(parent, ns=(1440000000000000000, 1440000000000000000))
            before = module.directory_metadata(parent, "metadata smoke cleanup parent")

            def fail_after_temp_fsync(label: str) -> None:
                if label == "cleanup.journal.temp.fsync":
                    raise module.PiSetupError("injected cleanup publication failure")

            module.lifecycle_hook = fail_after_temp_fsync
            try:
                module.publish_json_no_replace(
                    parent / "pending.json",
                    {"schema_version": 1, "kind": "metadata-smoke"},
                    "journal",
                )
            except module.PiSetupError as exc:
                if "injected cleanup publication failure" not in str(exc):
                    errors.append(f"cli-tools/nddev_pi.py: unexpected cleanup failure error: {exc}")
                    return
            else:
                errors.append("cli-tools/nddev_pi.py: injected cleanup publication failure succeeded")
                return
            if list(parent.iterdir()):
                errors.append("cli-tools/nddev_pi.py: cleanup publication failure left residue")
            after = module.directory_metadata(parent, "metadata smoke cleanup parent")
            if after != before:
                errors.append("cli-tools/nddev_pi.py: cleanup publication failure changed parent metadata")
    except Exception as exc:  # pragma: no cover - validator reports instead of crashing
        errors.append(f"cli-tools/nddev_pi.py: cleanup metadata behavior check failed: {exc}")
    finally:
        sys.modules.pop(name, None)


def validate_launch_workspace_behavior(errors: list[str]) -> None:
    manager = ROOT / "cli-tools" / "nddev_pi.py"
    name = "nddev_pi_public_validator_launch_workspace"
    try:
        spec = importlib.util.spec_from_file_location(name, manager)
        if spec is None or spec.loader is None:
            errors.append("cli-tools/nddev_pi.py: cannot load manager module spec")
            return
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory(prefix="nddev-pi-public-launch-workspace.") as tmp:
            root = Path(tmp)
            target = root / "target"
            workspace = root / "workspace"
            default_workspace = root / "default-workspace"
            target.mkdir(mode=module.OWNER_DIRECTORY_MODE)
            workspace.mkdir(mode=module.OWNER_DIRECTORY_MODE)
            default_workspace.mkdir(mode=module.OWNER_DIRECTORY_MODE)
            child = target / "bin" / "pi"
            child.parent.mkdir(mode=module.OWNER_DIRECTORY_MODE)
            child.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            child.chmod(0o700)
            file_workspace = root / "not-a-directory"
            file_workspace.write_text("not a directory", encoding="utf-8")
            symlink_workspace = root / "workspace-link"
            symlink_workspace.symlink_to(workspace, target_is_directory=True)

            captures: list[dict[str, object]] = []

            class FakeCompleted:
                returncode = 37

            class FakeTargetLock:
                def __init__(self, locked_target: Path) -> None:
                    self.locked_target = locked_target

                def __enter__(self) -> Path:
                    return self.locked_target

                def __exit__(self, *_exc: object) -> bool:
                    return False

            def fake_target_lock(locked_target: Path, mutation: bool = True) -> FakeTargetLock:
                _ = mutation
                return FakeTargetLock(locked_target)

            def fake_run(
                command: list[str],
                *,
                env: dict[str, str] | None = None,
                cwd: str | None = None,
                check: bool = False,
                **_kwargs: object,
            ) -> FakeCompleted:
                captures.append(
                    {
                        "command": list(command),
                        "env": dict(env or {}),
                        "cwd": cwd,
                        "check": check,
                    }
                )
                return FakeCompleted()

            def invoke(argv: list[str]) -> int:
                stdout = io.StringIO()
                stderr = io.StringIO()
                with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                    return module.main(argv)

            originals = {
                "target_lock": module.target_lock,
                "drain_cleanup": module.drain_cleanup,
                "require_clean_managed": module.require_clean_managed,
                "software_status_payload": module.software_status_payload,
                "read_software_stamp": module.read_software_stamp,
                "read_current_settings": module.read_current_settings,
                "subprocess_run": module.subprocess.run,
            }
            old_cwd = Path.cwd()
            try:
                module.target_lock = fake_target_lock
                module.drain_cleanup = lambda _target: False
                module.require_clean_managed = lambda _target: None
                module.software_status_payload = lambda _target: {"current": True, "drift": []}
                module.read_software_stamp = lambda _target: {
                    "node_runtime": {"path": "/usr/bin/node"}
                }
                module.read_current_settings = lambda _target: {
                    "nddev": {"launch_args": ["--offline", "--approve"]}
                }
                module.subprocess.run = fake_run

                rc = invoke(
                    [
                        "launch",
                        "--json",
                        "--target",
                        str(target),
                        "--workspace",
                        str(workspace),
                        "--",
                        "--help",
                    ]
                )
                if rc != FakeCompleted.returncode or len(captures) != 1:
                    errors.append("cli-tools/nddev_pi.py: explicit workspace launch did not spawn once")
                    return
                explicit_capture = captures[-1]
                expected_command = [
                    str(child),
                    "--offline",
                    "--approve",
                    "--skill",
                    str((target / "agent" / "skills" / "nddev-builder").resolve()),
                    "--help",
                ]
                if explicit_capture["command"] != expected_command:
                    errors.append("cli-tools/nddev_pi.py: launch argv is not manager-owned")
                if explicit_capture["cwd"] != str(workspace.resolve()):
                    errors.append("cli-tools/nddev_pi.py: explicit workspace cwd was not used")
                env = explicit_capture["env"]
                if not isinstance(env, dict):
                    errors.append("cli-tools/nddev_pi.py: launch environment was not captured")
                    return
                expected_env = {
                    "HOME": target / ".nddev-pi-runtime" / "home",
                    "XDG_CONFIG_HOME": target / ".nddev-pi-runtime" / "xdg-config",
                    "XDG_DATA_HOME": target / ".nddev-pi-runtime" / "xdg-data",
                    "XDG_STATE_HOME": target / ".nddev-pi-runtime" / "xdg-state",
                    "XDG_CACHE_HOME": target / ".nddev-pi-runtime" / "xdg-cache",
                    "TMPDIR": target / ".nddev-pi-runtime" / "tmp",
                    "PI_CODING_AGENT_DIR": target / "agent",
                    "PI_CODING_AGENT_SESSION_DIR": target / "agent" / "sessions",
                    "PI_PACKAGE_DIR": target / "agent" / "package-cache",
                }
                for key, expected_path in expected_env.items():
                    if env.get(key) != str(expected_path.resolve()):
                        errors.append(f"cli-tools/nddev_pi.py: launch env {key} is not target-owned")
                if env.get("PI_OFFLINE") != "1" or env.get("PI_TELEMETRY") != "0":
                    errors.append("cli-tools/nddev_pi.py: launch network/telemetry env drifted")

                captures.clear()
                os.chdir(default_workspace)
                rc = invoke(["launch", "--json", "--target", str(target), "--", "--version"])
                if rc != FakeCompleted.returncode or len(captures) != 1:
                    errors.append("cli-tools/nddev_pi.py: default workspace launch did not spawn once")
                    return
                if captures[-1]["cwd"] != str(default_workspace.resolve()):
                    errors.append("cli-tools/nddev_pi.py: caller cwd was not captured as workspace")
                os.chdir(old_cwd)

                invalid_workspaces = [
                    ["--workspace", "relative"],
                    ["--workspace", str(root / "missing")],
                    ["--workspace", str(file_workspace)],
                    ["--workspace", str(symlink_workspace)],
                ]
                for workspace_args in invalid_workspaces:
                    captures.clear()
                    rc = invoke(
                        [
                            "launch",
                            "--json",
                            "--target",
                            str(target),
                            *workspace_args,
                            "--",
                            "--help",
                        ]
                    )
                    if rc != 2 or captures:
                        errors.append(
                            "cli-tools/nddev_pi.py: invalid workspace reached child spawn"
                        )

                forwarded_overrides = [
                    ["--workspace=/tmp"],
                    ["--project", "/tmp"],
                    ["--cwd=/tmp"],
                    ["-C/tmp"],
                ]
                for forwarded in forwarded_overrides:
                    captures.clear()
                    rc = invoke(
                        [
                            "launch",
                            "--json",
                            "--target",
                            str(target),
                            "--workspace",
                            str(workspace),
                            "--",
                            *forwarded,
                        ]
                    )
                    if rc != 2 or captures:
                        errors.append(
                            "cli-tools/nddev_pi.py: forwarded workspace override reached child spawn"
                        )
            finally:
                os.chdir(old_cwd)
                module.target_lock = originals["target_lock"]
                module.drain_cleanup = originals["drain_cleanup"]
                module.require_clean_managed = originals["require_clean_managed"]
                module.software_status_payload = originals["software_status_payload"]
                module.read_software_stamp = originals["read_software_stamp"]
                module.read_current_settings = originals["read_current_settings"]
                module.subprocess.run = originals["subprocess_run"]
    except Exception as exc:  # pragma: no cover - validator reports instead of crashing
        errors.append(f"cli-tools/nddev_pi.py: launch workspace behavior check failed: {exc}")
    finally:
        sys.modules.pop(name, None)


def main() -> int:
    errors: list[str] = []
    version = load_json("build/version.json", errors)
    manifest = load_json("build/manifest.json", errors)
    contract = load_json("config/nddev-contract.json", errors)
    baseline = load_json("references/pi-baseline.json", errors)
    builder_package = load_json("builder/nddev-builder/package.json", errors)
    validate_npm_json_output_bound(errors)
    validate_cold_read_coordination(errors)
    validate_software_rollback_identity(errors)
    validate_external_anchor_recovery(errors)
    validate_external_anchor_behavior(errors)
    validate_cleanup_metadata_behavior(errors)
    validate_launch_workspace_behavior(errors)

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
        elif (
            runtime.get("target_role") != "configuration-runtime-home"
            or runtime.get("workspace_option") != "--workspace <absolute-existing-dir>"
            or runtime.get("default_workspace_source") != "caller-cwd-captured-once"
            or runtime.get("explicit_workspace_requirements") != LAUNCH_WORKSPACE_REQUIREMENTS
            or runtime.get("child_cwd") != "resolved-workspace"
            or runtime.get("native_workspace_argument_supported") is not False
            or runtime.get("native_workspace_argument") is not None
            or runtime.get("blocked_forwarded_scope_overrides") != LAUNCH_BLOCKED_SCOPE_OVERRIDES
        ):
            errors.append("build/manifest.json: launch workspace contract mismatch")
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
            or transaction.get("cold_no_anchor_namespace")
            != "bounded-empty-or-fail-closed-retry-whole-read"
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
        setup_rollback = (
            transaction.get("setup_rollback") if isinstance(transaction, dict) else None
        )
        if (
            not isinstance(setup_rollback, dict)
            or setup_rollback.get("strategy") != "object-preserving held managed files"
            or setup_rollback.get("restores_original_file_identity") is not True
            or setup_rollback.get("backup_commit_after_desired_postcondition") is not True
        ):
            errors.append("build/manifest.json: setup rollback policy mismatch")
        software_rollback = (
            transaction.get("software_rollback") if isinstance(transaction, dict) else None
        )
        if (
            not isinstance(software_rollback, dict)
            or software_rollback.get("strategy")
            != "object-preserving cleanup intent replacements"
            or software_rollback.get("restores_original_file_identity") is not True
            or software_rollback.get("prepare_intent_before_visible_replacement") is not True
            or software_rollback.get("committed_success_cleanup_pending") is not True
        ):
            errors.append("build/manifest.json: software rollback policy mismatch")
        backup_policy = manifest.get("backup_policy")
        if (
            not isinstance(backup_policy, dict)
            or backup_policy.get("full_pool_behavior") != "fail-closed"
            or backup_policy.get("envelope_schema") != 2
            or backup_policy.get("file_metadata") != ["size", "sha256"]
            or backup_policy.get("exact_managed_path_set") is not True
        ):
            errors.append("build/manifest.json: backup policy mismatch")

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
        runtime = contract.get("runtime_launch")
        if (
            not isinstance(runtime, dict)
            or runtime.get("target_role") != "configuration-runtime-home"
            or runtime.get("workspace_option") != "--workspace <absolute-existing-dir>"
            or runtime.get("default_workspace_source") != "caller-cwd-captured-once"
            or runtime.get("explicit_workspace_requirements") != LAUNCH_WORKSPACE_REQUIREMENTS
            or runtime.get("child_cwd") != "resolved-workspace"
            or runtime.get("native_workspace_argument_supported") is not False
            or runtime.get("native_workspace_argument") is not None
            or runtime.get("blocked_forwarded_scope_overrides") != LAUNCH_BLOCKED_SCOPE_OVERRIDES
        ):
            errors.append("config/nddev-contract.json: launch workspace contract mismatch")
        safety = contract.get("safety", {})
        if (
            safety.get("backup_full_pool_behavior") != "fail-closed"
            or safety.get("backup_envelope_schema") != 2
            or safety.get("backup_records_sizes_and_digests") is not True
            or safety.get("backup_exact_managed_path_set") is not True
        ):
            errors.append("config/nddev-contract.json: backup policy mismatch")
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
            "npm_source": "<stage>/install/node_modules/.bin/pi",
            "required_package_target": (
                "<stage>/install/node_modules/@earendil-works/pi-coding-agent/dist/cli.js"
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
                ".nddev-pi-software/current/install/node_modules/"
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
            or coordination.get("cold_no_anchor_namespace")
            != "bounded-empty-or-fail-closed-retry-whole-read"
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
        setup_rollback = contract.get("safety", {}).get("setup_rollback")
        if (
            not isinstance(setup_rollback, dict)
            or setup_rollback.get("strategy") != "object-preserving held managed files"
            or setup_rollback.get("restores_original_file_identity") is not True
            or setup_rollback.get("backup_commit_after_desired_postcondition") is not True
        ):
            errors.append("config/nddev-contract.json: setup rollback policy mismatch")
        software_rollback = contract.get("safety", {}).get("software_rollback")
        if (
            not isinstance(software_rollback, dict)
            or software_rollback.get("strategy")
            != "object-preserving cleanup intent replacements"
            or software_rollback.get("restores_original_file_identity") is not True
            or software_rollback.get("prepare_intent_before_visible_replacement") is not True
            or software_rollback.get("committed_success_cleanup_pending") is not True
        ):
            errors.append("config/nddev-contract.json: software rollback policy mismatch")
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
        launch_scope = baseline.get("launch_scope")
        if (
            not isinstance(launch_scope, dict)
            or launch_scope.get("target_role") != "configuration-runtime-home"
            or launch_scope.get("default_workspace_source") != "caller-cwd-captured-once"
            or launch_scope.get("manager_workspace_option") != "--workspace <absolute-existing-dir>"
            or launch_scope.get("explicit_workspace_requirements")
            != LAUNCH_WORKSPACE_REQUIREMENTS
            or launch_scope.get("child_cwd") != "resolved-workspace"
            or launch_scope.get("native_workspace_argument_supported") is not False
            or launch_scope.get("native_workspace_argument") is not None
            or launch_scope.get("official_cli_grammar", {}).get("workspace_project_cwd_flags")
            != []
        ):
            errors.append("references/pi-baseline.json: launch scope baseline mismatch")

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
