#!/usr/bin/env python3
"""Transactional setup manager for caller-selected Pi Coding Agent targets."""

from __future__ import annotations

import argparse
import base64
import contextlib
import hashlib
import json
import os
import re
import shlex
import shutil
import stat
import subprocess
import sys
import tempfile
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any, NoReturn

ROOT = Path(__file__).resolve().parents[1]
CATALOG_ROOT = ROOT / "setups"
VERSION = (ROOT / "VERSION").read_text(encoding="ascii").strip()
PRODUCT_NAME = "nddev-pi-app"
PI_COMMAND = "pi"
SETTINGS_REL = Path("agent") / "settings.json"
SETTINGS_NAME = SETTINGS_REL.as_posix()
STAMP_NAME = "NDDEV-PI-SETUP.json"
BACKUP_NAME = "NDDEV-PI-BACKUP.json"
OWNER_FILE_MODE = 0o600
OWNER_DIRECTORY_MODE = 0o700
METADATA_MAX_BYTES = 256 * 1024
MANAGED_PAYLOAD_MAX_BYTES = 8 * 1024 * 1024
SETUP_ID_PATTERN = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")
BUILDER_SOURCE_ROOT = ROOT / "builder" / "nddev-builder"
BUILDER_SKILL_DIR = Path("agent") / "skills" / "nddev-builder"
BUILDER_PACKAGE_DIR = Path("agent") / "packages" / "nddev-builder"
BUILDER_FILES = (
    (
        BUILDER_SOURCE_ROOT / "skills" / "nddev-builder" / "SKILL.md",
        BUILDER_SKILL_DIR / "SKILL.md",
    ),
    (BUILDER_SOURCE_ROOT / "package.json", BUILDER_PACKAGE_DIR / "package.json"),
    (
        BUILDER_SOURCE_ROOT / "skills" / "nddev-builder" / "SKILL.md",
        BUILDER_PACKAGE_DIR / "skills" / "nddev-builder" / "SKILL.md",
    ),
)
MANAGED_SETTING_KEYS = (
    "defaultProjectTrust",
    "enableInstallTelemetry",
    "enableAnalytics",
    "enableSkillCommands",
    "sessionDir",
    "nddev",
)
STAMP_KEYS = {
    "schema_version",
    "product_name",
    "build_version",
    "setup_id",
    "canonical_target",
    "managed_files",
    "builder_projection",
}
BACKUP_KEYS = {
    "schema_version",
    "product_name",
    "build_version",
    "slot",
    "canonical_target",
    "source_setup_id",
    "managed_files",
    "created_at",
    "files",
}
CHILD_ENV_ALLOWLIST = {
    "LANG",
    "LC_ALL",
    "TERM",
    "COLORTERM",
    "SYSTEMROOT",
}
SENSITIVE_ENVIRONMENT_SUFFIXES = (
    "_API_KEY",
    "_AUTH_TOKEN",
    "_TOKEN",
    "_SECRET",
)
SENSITIVE_ENVIRONMENT_EXACT = {
    "BUN_AUTH_TOKEN",
    "BUN_CONFIG_REGISTRY",
    "NODE_AUTH_TOKEN",
    "NPM_TOKEN",
}
PI_PACKAGE_NAME = "@earendil-works/pi-coding-agent"
PI_PACKAGE_VERSION = "0.82.1"
PI_PACKAGE_BIN = "dist/cli.js"
PI_NODE_REQUIREMENT = ">=22.19.0"
PI_REGISTRY_INTEGRITY = (
    "sha512-zbkAhoIuDPMF3pKuja0ajZabrMWU29FUMV9A/"
    "XMXT/XC1yXs5xt6t6t13GogQFsDrDqbFP4DkZQO1w8rWRAzYA=="
)
PI_REGISTRY_SHASUM = "39c00809ff5531b6552b9ecb2c41f4c3529ec988"
BUN_INSTALL_ARGV = [
    "add",
    "--global",
    "--exact",
    f"{PI_PACKAGE_NAME}@{PI_PACKAGE_VERSION}",
]
SOFTWARE_STAMP_NAME = "NDDEV-PI-SOFTWARE.json"
SOFTWARE_DIR_NAME = ".nddev-pi-software"
SOFTWARE_CURRENT_NAME = "current"
SOFTWARE_STAGE_FRAGMENT = ".nddev-pi-software-stage"
SOFTWARE_FILE_MAX_BYTES = 192 * 1024 * 1024
SOFTWARE_TREE_MAX_BYTES = 192 * 1024 * 1024
SOFTWARE_TREE_MAX_PATHS = 25000
PROCESS_OUTPUT_MAX_BYTES = 64 * 1024
PROCESS_TIMEOUT_SECONDS = 120
PI_PACKAGE_RELATIVE = "install/global/node_modules/@earendil-works/pi-coding-agent"
PI_PACKAGE_BINARY_RELATIVE = f"{PI_PACKAGE_RELATIVE}/{PI_PACKAGE_BIN}"
SOFTWARE_STAMP_KEYS = {
    "schema_version",
    "product_name",
    "build_version",
    "canonical_target",
    "package",
    "version",
    "command",
    "package_bin",
    "entrypoint",
    "entrypoint_kind",
    "entrypoint_main",
    "installed_tree",
    "manager",
    "entrypoint_sha256",
    "package_binary_sha256",
    "installed_tree_sha256",
    "installed_tree_path_count",
    "installed_tree_bytes",
    "tree_limits",
    "registry",
    "node_runtime",
    "version_probe",
    "official_package_scripts",
    "installer",
}
SOFTWARE_STAMP_REGISTRY_KEYS = {"integrity", "shasum"}
SOFTWARE_STAMP_TREE_LIMIT_KEYS = {"max_paths", "max_bytes"}
SOFTWARE_STAMP_NODE_KEYS = {"path", "version", "sha256", "requirement"}
SOFTWARE_STAMP_PROBE_KEYS = {"argv", "environment", "stdout_stderr_sha256"}
SOFTWARE_STAMP_SCRIPT_KEYS = {"preinstall", "install", "postinstall", "prepublishOnly"}
SOFTWARE_STAMP_INSTALLER_KEYS = {"tool", "argv", "trust_reason", "env"}
SOFTWARE_STAMP_INSTALLER_ENV_KEYS = {
    "BUN_INSTALL_GLOBAL_DIR",
    "BUN_INSTALL_BIN",
    "BUN_INSTALL_CACHE_DIR",
    "HOME",
    "XDG_CONFIG_HOME",
    "TMPDIR",
}
LAUNCH_BLOCKED_COMMANDS = {
    "install": "package installation mutates Pi package scope",
    "remove": "package removal mutates Pi package scope",
    "uninstall": "package removal mutates Pi package scope",
    "update": "package/self update mutates Pi package scope",
    "config": "interactive config can mutate Pi settings scope",
}
LAUNCH_BLOCKED_BOOLEAN_FLAGS = {
    "--approve": "project trust override",
    "-a": "project trust override",
    "--no-approve": "project trust override",
    "-na": "project trust override",
    "--no-tools": "tool selection override",
    "-nt": "tool selection override",
    "--no-builtin-tools": "tool selection override",
    "-nbt": "tool selection override",
    "--no-extensions": "extension resource override",
    "-ne": "extension resource override",
    "--no-skills": "skill resource override",
    "-ns": "skill resource override",
    "--no-prompt-templates": "prompt resource override",
    "-np": "prompt resource override",
    "--no-themes": "theme resource override",
    "--no-context-files": "work context override",
    "-nc": "work context override",
}
LAUNCH_BLOCKED_VALUE_FLAGS = {
    "--provider": "model provider override",
    "--model": "model override",
    "--api-key": "provider credential override",
    "--system-prompt": "prompt override",
    "--append-system-prompt": "prompt override",
    "--name": "session metadata override",
    "-n": "session metadata override",
    "--session": "session file override",
    "--session-id": "session identity override",
    "--fork": "session fork override",
    "--session-dir": "session directory override",
    "--models": "model cycling override",
    "--tools": "tool selection override",
    "-t": "tool selection override",
    "--exclude-tools": "tool selection override",
    "-xt": "tool selection override",
    "--thinking": "model thinking override",
    "--extension": "extension resource override",
    "-e": "extension resource override",
    "--skill": "skill resource override",
    "--prompt-template": "prompt resource override",
    "--theme": "theme resource override",
}


class PiSetupError(Exception):
    """A safe, user-facing lifecycle failure."""


def fail(message: str) -> NoReturn:
    raise PiSetupError(message)


def canonical_json(value: Any) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def identity_of(info: os.stat_result) -> tuple[int, int]:
    return info.st_dev, info.st_ino


def is_current_user_owner(info: os.stat_result) -> bool:
    if not hasattr(os, "geteuid"):
        return True
    return info.st_uid == os.geteuid()


def require_current_user_owner(info: os.stat_result, label: str) -> None:
    if not is_current_user_owner(info):
        fail(f"{label} must be owned by the current user")


def is_sensitive_environment_name(name: str) -> bool:
    upper = name.upper()
    lower = name.lower()
    if upper.startswith("AWS_"):
        return True
    if lower.startswith("npm_config_"):
        return True
    if upper in SENSITIVE_ENVIRONMENT_EXACT:
        return True
    return upper.endswith(SENSITIVE_ENVIRONMENT_SUFFIXES)


def assert_no_sensitive_environment(env: dict[str, str], label: str) -> None:
    leaked = sorted(name for name in env if is_sensitive_environment_name(name))
    if leaked:
        fail(f"{label} contains sensitive environment variables: {', '.join(leaked)}")


def child_base_environment() -> dict[str, str]:
    return {
        name: value
        for name, value in os.environ.items()
        if name in CHILD_ENV_ALLOWLIST and not is_sensitive_environment_name(name)
    }


def stat_optional(path: Path, label: str) -> os.stat_result | None:
    try:
        info = path.lstat()
    except FileNotFoundError:
        return None
    if stat.S_ISLNK(info.st_mode):
        fail(f"{label} must not be a symlink")
    return info


def require_directory(path: Path, label: str) -> os.stat_result:
    try:
        info = path.lstat()
    except FileNotFoundError:
        fail(f"{label} is missing")
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
        fail(f"{label} must be a real directory")
    return info


def require_safe_partial_directory(path: Path, label: str) -> None:
    info = stat_optional(path, label)
    if info is None:
        return
    if not stat.S_ISDIR(info.st_mode):
        fail(f"{label} must be a directory")
    require_current_user_owner(info, label)
    if stat.S_IMODE(info.st_mode) != OWNER_DIRECTORY_MODE:
        fail(f"{label} must be private")


def require_safe_partial_file(path: Path, label: str, *, max_bytes: int) -> None:
    info = stat_optional(path, label)
    if info is None:
        return
    if not stat.S_ISREG(info.st_mode):
        fail(f"{label} must be a regular file")
    require_current_user_owner(info, label)
    if info.st_nlink != 1:
        fail(f"{label} must not be a hardlink")
    if info.st_size > max_bytes:
        fail(f"{label} is too large")


def require_exact_keys(value: dict[str, Any], expected: set[str], label: str) -> None:
    actual = set(value)
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        fail(f"{label} has invalid keys (missing={missing}, extra={extra})")


def require_bounded_size(info: os.stat_result, label: str, max_bytes: int) -> None:
    if info.st_size > max_bytes:
        fail(f"{label} exceeds the {max_bytes}-byte size limit")


def require_regular_file(path: Path, label: str, *, max_bytes: int) -> os.stat_result:
    try:
        info = path.lstat()
    except FileNotFoundError:
        fail(f"{label} is missing")
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        fail(f"{label} must be a regular non-symlink file")
    if info.st_nlink != 1:
        fail(f"{label} must not have hard-link aliases")
    require_bounded_size(info, label, max_bytes)
    return info


def read_regular_file(
    path: Path, label: str, *, max_bytes: int = MANAGED_PAYLOAD_MAX_BYTES
) -> bytes:
    before = require_regular_file(path, label, max_bytes=max_bytes)
    flags = os.O_RDONLY
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags)
    try:
        opened = os.fstat(descriptor)
        if (before.st_dev, before.st_ino) != (opened.st_dev, opened.st_ino):
            fail(f"{label} changed while it was being opened")
        if not stat.S_ISREG(opened.st_mode) or opened.st_nlink != 1:
            fail(f"{label} changed to an unsafe file")
        require_bounded_size(opened, label, max_bytes)
        blocks: list[bytes] = []
        total = 0
        while True:
            block = os.read(descriptor, 65536)
            if not block:
                break
            total += len(block)
            if total > max_bytes:
                fail(f"{label} exceeds the {max_bytes}-byte size limit")
            blocks.append(block)
        after = os.fstat(descriptor)
        require_bounded_size(after, label, max_bytes)
    finally:
        os.close(descriptor)
    final = require_regular_file(path, label, max_bytes=max_bytes)
    expected = (before.st_dev, before.st_ino)
    if (after.st_dev, after.st_ino) != expected or (final.st_dev, final.st_ino) != expected:
        fail(f"{label} changed while it was being read")
    return b"".join(blocks)


def file_sha256(
    path: Path, *, label: str, max_bytes: int = SOFTWARE_FILE_MAX_BYTES
) -> str:
    content = read_regular_file(path, label, max_bytes=max_bytes)
    info = require_regular_file(path, label, max_bytes=max_bytes)
    require_current_user_owner(info, label)
    return sha256_bytes(content)


def software_tree_identity(root: Path) -> tuple[str, int, int]:
    root_info = require_directory(root, "software tree")
    require_current_user_owner(root_info, "software tree")
    if stat.S_IMODE(root_info.st_mode) != OWNER_DIRECTORY_MODE:
        fail("software tree root must be private")
    paths = sorted(root.rglob("*"), key=lambda item: item.relative_to(root).as_posix())
    if len(paths) > SOFTWARE_TREE_MAX_PATHS:
        fail(
            f"software tree has {len(paths)} paths, exceeding "
            f"the {SOFTWARE_TREE_MAX_PATHS}-path limit"
        )
    digest = hashlib.sha256()
    total = 0
    for path in paths:
        relative = path.relative_to(root).as_posix()
        info = path.lstat()
        mode = stat.S_IMODE(info.st_mode)
        if stat.S_ISLNK(info.st_mode):
            fail(f"software tree must not contain symlinks: {relative}")
        digest.update(relative.encode("utf-8") + b"\0" + oct(mode).encode("ascii") + b"\0")
        if stat.S_ISDIR(info.st_mode):
            require_current_user_owner(info, relative)
            if mode != OWNER_DIRECTORY_MODE:
                fail(f"software tree directory must be private: {relative}")
            digest.update(b"dir\0")
            continue
        if not stat.S_ISREG(info.st_mode):
            fail(f"software tree entry must be a regular file: {relative}")
        require_current_user_owner(info, relative)
        if info.st_nlink != 1:
            fail(f"software tree entry must not be a hardlink: {relative}")
        content = read_regular_file(path, relative, max_bytes=SOFTWARE_FILE_MAX_BYTES)
        total += len(content)
        if total > SOFTWARE_TREE_MAX_BYTES:
            fail(
                f"software tree exceeds the {SOFTWARE_TREE_MAX_BYTES}-byte limit"
            )
        digest.update(b"file\0" + sha256_bytes(content).encode("ascii") + b"\0")
    return digest.hexdigest(), len(paths), total


def parse_json_object(content: bytes, label: str) -> dict[str, Any]:
    try:
        value = json.loads(content.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        fail(f"cannot read valid JSON from {label}: {exc}")
    if not isinstance(value, dict):
        fail(f"{label} must contain a JSON object")
    return value


def load_json_object(path: Path, label: str) -> dict[str, Any]:
    return parse_json_object(read_regular_file(path, label, max_bytes=METADATA_MAX_BYTES), label)


def maybe_load_json_object(path: Path, label: str) -> dict[str, Any] | None:
    try:
        path.lstat()
    except FileNotFoundError:
        return None
    return load_json_object(path, label)


def validate_setup_id(setup_id: str) -> None:
    if not SETUP_ID_PATTERN.fullmatch(setup_id):
        fail(f"invalid setup id: {setup_id!r}")


def validate_string_array(value: Any, label: str) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        fail(f"{label} must be a string array")
    return value


def load_setup(setup_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
    validate_setup_id(setup_id)
    setup_root = CATALOG_ROOT / setup_id
    if not setup_root.is_dir() or setup_root.is_symlink():
        fail(f"unknown setup: {setup_id}")
    metadata = load_json_object(setup_root / "setup.json", f"setup {setup_id} metadata")
    require_exact_keys(
        metadata,
        {
            "schema_version",
            "id",
            "description",
            "managed_files",
            "builder_projection",
            "permission_model",
            "launch_args",
        },
        f"setup {setup_id} metadata",
    )
    if metadata["schema_version"] != 1:
        fail(f"setup {setup_id} metadata has unsupported schema")
    if metadata["id"] != setup_id:
        fail(f"setup {setup_id} metadata identity mismatch")
    if metadata["managed_files"] != [SETTINGS_NAME]:
        fail(f"setup {setup_id} managed file declaration is invalid")
    if metadata["builder_projection"] != "default-on":
        fail(f"setup {setup_id} must enable the builder projection")
    validate_string_array(metadata["launch_args"], f"setup {setup_id} launch_args")

    settings = load_json_object(setup_root / "settings.json", f"setup {setup_id}/settings.json")
    if settings.get("nddev", {}).get("setup_id") != setup_id:
        fail(f"setup {setup_id} settings identity mismatch")
    if settings.get("enableSkillCommands") is not True:
        fail(f"setup {setup_id} must enable Pi skill commands")
    if settings.get("enableInstallTelemetry") is not False:
        fail(f"setup {setup_id} must disable install telemetry")
    if settings.get("enableAnalytics") is not False:
        fail(f"setup {setup_id} must disable analytics")
    return metadata, settings


def list_setups() -> list[dict[str, Any]]:
    if not CATALOG_ROOT.is_dir() or CATALOG_ROOT.is_symlink():
        fail("setup catalog is missing or unsafe")
    entries: list[dict[str, Any]] = []
    for candidate in sorted(CATALOG_ROOT.iterdir(), key=lambda path: path.name):
        if not candidate.is_dir() or candidate.is_symlink():
            fail(f"catalog entry must be a real directory: {candidate.name}")
        metadata, _ = load_setup(candidate.name)
        entries.append(
            {
                "id": metadata["id"],
                "description": metadata["description"],
                "managed_files": metadata["managed_files"],
                "builder_default_on": metadata["builder_projection"] == "default-on",
                "launch_args": metadata["launch_args"],
            }
        )
    if not entries:
        fail("setup catalog is empty")
    return entries


def resolve_target(raw_target: str | None) -> Path:
    if not raw_target:
        fail("--target is required")
    expanded = Path(raw_target).expanduser()
    if not expanded.is_absolute():
        fail("--target must be an absolute path")
    try:
        raw_info = expanded.lstat()
    except FileNotFoundError:
        raw_info = None
    if raw_info is not None and stat.S_ISLNK(raw_info.st_mode):
        fail("--target must not be a symlink")
    if raw_info is not None and not stat.S_ISDIR(raw_info.st_mode):
        fail("--target must be a directory")
    return expanded.resolve(strict=False)


def backup_pool(target: Path) -> Path:
    return target.parent / f".{target.name}.nddev-pi-backups"


def lock_dir(target: Path) -> Path:
    return target.parent / f".{target.name}.nddev-pi.lock"


@contextlib.contextmanager
def target_lock(target: Path) -> Iterator[None]:
    lock = lock_dir(target)
    try:
        os.mkdir(lock, OWNER_DIRECTORY_MODE)
    except FileExistsError:
        fail("target is already locked by another nddev-pi operation")
    try:
        yield
    finally:
        with contextlib.suppress(FileNotFoundError):
            lock.rmdir()


def ensure_directory(path: Path) -> None:
    try:
        info = path.lstat()
    except FileNotFoundError:
        path.mkdir(mode=OWNER_DIRECTORY_MODE, parents=True, exist_ok=True)
        return
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
        fail(f"{path} must be a real directory")


def ensure_target_directory(target: Path) -> bool:
    try:
        info = target.lstat()
    except FileNotFoundError:
        target.mkdir(mode=OWNER_DIRECTORY_MODE, parents=True)
        return True
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
        fail("--target must be a real directory")
    return False


def safe_write_file(path: Path, content: bytes) -> None:
    parent = path.parent
    ensure_directory(parent)
    try:
        require_regular_file(path, path.as_posix(), max_bytes=MANAGED_PAYLOAD_MAX_BYTES)
    except FileNotFoundError:
        raise
    except PiSetupError as exc:
        if "is missing" not in str(exc):
            raise
    temporary = parent / f".{path.name}.tmp-{os.getpid()}-{time.monotonic_ns()}"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    descriptor = os.open(temporary, flags, OWNER_FILE_MODE)
    try:
        os.write(descriptor, content)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    os.replace(temporary, path)
    path.chmod(OWNER_FILE_MODE)


def read_existing_file(path: Path) -> bytes | None:
    try:
        path.lstat()
    except FileNotFoundError:
        return None
    return read_regular_file(path, path.as_posix(), max_bytes=MANAGED_PAYLOAD_MAX_BYTES)


def delete_file(path: Path) -> None:
    try:
        info = path.lstat()
    except FileNotFoundError:
        return
    if stat.S_ISLNK(info.st_mode):
        fail(f"{path} must not be a symlink")
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        fail(f"{path} must be a regular non-hard-linked file")
    path.unlink()


def delete_tree(path: Path) -> None:
    try:
        info = path.lstat()
    except FileNotFoundError:
        return
    if stat.S_ISLNK(info.st_mode):
        fail(f"{path} must not be a symlink")
    if not stat.S_ISDIR(info.st_mode):
        fail(f"{path} must be a directory")
    shutil.rmtree(path)


def builder_skill_path(target: Path) -> str:
    return str((target / BUILDER_SKILL_DIR).resolve())


def builder_package_entry(target: Path) -> dict[str, str]:
    return {"source": str((target / BUILDER_PACKAGE_DIR).resolve()), "name": "nddev-builder"}


def dedupe_json_list(values: list[Any]) -> list[Any]:
    result: list[Any] = []
    seen: set[str] = set()
    for value in values:
        key = json.dumps(value, sort_keys=True, separators=(",", ":"))
        if key not in seen:
            seen.add(key)
            result.append(value)
    return result


def merge_settings(
    existing: dict[str, Any] | None, setup_settings: dict[str, Any], target: Path
) -> dict[str, Any]:
    result: dict[str, Any] = {}
    if existing is not None:
        for key, value in existing.items():
            if key not in MANAGED_SETTING_KEYS and key not in {"skills", "packages"}:
                result[key] = value

    for key in MANAGED_SETTING_KEYS:
        result[key] = setup_settings[key]

    existing_skills = []
    if existing is not None and "skills" in existing:
        existing_skills = validate_string_array(existing["skills"], "existing settings.skills")
    result["skills"] = dedupe_json_list([*existing_skills, builder_skill_path(target)])

    existing_packages = []
    if existing is not None and "packages" in existing:
        if not isinstance(existing["packages"], list):
            fail("existing settings.packages must be an array")
        existing_packages = existing["packages"]
    result["packages"] = dedupe_json_list([*existing_packages, builder_package_entry(target)])
    return result


def strip_managed_settings(settings: dict[str, Any], target: Path) -> dict[str, Any]:
    result = {
        key: value
        for key, value in settings.items()
        if key not in MANAGED_SETTING_KEYS and key not in {"skills", "packages"}
    }
    skill_path = builder_skill_path(target)
    skills = settings.get("skills")
    if isinstance(skills, list):
        remaining_skills = [value for value in skills if value != skill_path]
        if remaining_skills:
            result["skills"] = remaining_skills
    packages = settings.get("packages")
    package_entry = builder_package_entry(target)
    if isinstance(packages, list):
        remaining_packages = [value for value in packages if value != package_entry]
        if remaining_packages:
            result["packages"] = remaining_packages
    return result


def managed_settings_view(settings: dict[str, Any], target: Path) -> dict[str, Any]:
    view = {key: settings.get(key) for key in MANAGED_SETTING_KEYS}
    view["builder_skill_present"] = builder_skill_path(target) in settings.get("skills", [])
    view["builder_package_present"] = builder_package_entry(target) in settings.get("packages", [])
    return view


def builder_projection_files() -> dict[str, bytes]:
    files: dict[str, bytes] = {}
    for source, target_relative in BUILDER_FILES:
        content = read_regular_file(
            source,
            f"builder projection source {source.relative_to(BUILDER_SOURCE_ROOT).as_posix()}",
            max_bytes=MANAGED_PAYLOAD_MAX_BYTES,
        )
        content.decode("utf-8")
        files[target_relative.as_posix()] = content
    return files


def render_setup(
    setup_id: str, target: Path, existing: dict[str, Any] | None
) -> tuple[dict[str, Any], dict[str, bytes]]:
    metadata, settings = load_setup(setup_id)
    merged_settings = merge_settings(existing, settings, target)
    files: dict[str, bytes] = {SETTINGS_NAME: canonical_json(merged_settings)}
    files.update(builder_projection_files())
    return metadata, files


def read_current_settings(target: Path) -> dict[str, Any] | None:
    return maybe_load_json_object(target / SETTINGS_REL, SETTINGS_NAME)


def load_stamp(target: Path) -> dict[str, Any] | None:
    return maybe_load_json_object(target / STAMP_NAME, STAMP_NAME)


def compute_managed_digests(target: Path, settings: dict[str, Any] | None) -> dict[str, str]:
    digests: dict[str, str] = {}
    if settings is not None:
        digests[SETTINGS_NAME] = sha256_bytes(
            canonical_json(managed_settings_view(settings, target))
        )
    for relative in (
        BUILDER_SKILL_DIR / "SKILL.md",
        BUILDER_PACKAGE_DIR / "package.json",
        BUILDER_PACKAGE_DIR / "skills" / "nddev-builder" / "SKILL.md",
    ):
        content = read_existing_file(target / relative)
        if content is not None:
            digests[relative.as_posix()] = sha256_bytes(content)
    return digests


def make_stamp(target: Path, setup_id: str, final_settings: dict[str, Any]) -> dict[str, Any]:
    managed_files = compute_managed_digests(target, final_settings)
    return {
        "schema_version": 1,
        "product_name": PRODUCT_NAME,
        "build_version": VERSION,
        "setup_id": setup_id,
        "canonical_target": str(target),
        "managed_files": managed_files,
        "builder_projection": "skills+package",
    }


def status_for_target(target: Path) -> dict[str, Any]:
    if not target.exists():
        return {"state": "missing", "setup_id": None, "drift": [], "target": str(target)}
    stamp = load_stamp(target)
    if stamp is None:
        return {"state": "unmanaged", "setup_id": None, "drift": [], "target": str(target)}
    require_exact_keys(stamp, STAMP_KEYS, STAMP_NAME)
    setup_id = stamp.get("setup_id")
    if not isinstance(setup_id, str):
        fail("stamp setup_id must be a string")
    drift: list[str] = []
    if stamp.get("canonical_target") != str(target):
        drift.append(STAMP_NAME)
    settings = read_current_settings(target)
    current_digests = compute_managed_digests(target, settings)
    expected = stamp.get("managed_files")
    if not isinstance(expected, dict):
        fail("stamp managed_files must be an object")
    for relative, digest in expected.items():
        if current_digests.get(relative) != digest:
            drift.append(relative)
    return {
        "state": "managed",
        "setup_id": setup_id,
        "drift": sorted(set(drift)),
        "target": str(target),
        "builder_projection": stamp.get("builder_projection"),
    }


def require_clean_managed(target: Path) -> dict[str, Any]:
    status = status_for_target(target)
    if status["state"] != "managed":
        fail("target is not managed")
    if status["drift"]:
        fail(f"target has drift: {', '.join(status['drift'])}")
    return status


def snapshot_files(target: Path, relatives: list[str]) -> dict[str, str | None]:
    snapshot: dict[str, str | None] = {}
    for relative in relatives:
        content = read_existing_file(target / relative)
        snapshot[relative] = None if content is None else base64.b64encode(content).decode("ascii")
    return snapshot


def restore_snapshot(target: Path, snapshot: dict[str, str | None]) -> None:
    for relative, encoded in snapshot.items():
        path = target / relative
        if encoded is None:
            with contextlib.suppress(FileNotFoundError):
                delete_file(path)
        else:
            safe_write_file(path, base64.b64decode(encoded.encode("ascii")))


def managed_file_relatives() -> list[str]:
    return [
        SETTINGS_NAME,
        STAMP_NAME,
        (BUILDER_SKILL_DIR / "SKILL.md").as_posix(),
        (BUILDER_PACKAGE_DIR / "package.json").as_posix(),
        (BUILDER_PACKAGE_DIR / "skills" / "nddev-builder" / "SKILL.md").as_posix(),
    ]


def next_backup_slot(pool: Path) -> int:
    ensure_directory(pool)
    existing = {int(path.name) for path in pool.iterdir() if path.is_dir() and path.name.isdigit()}
    for slot in range(10):
        if slot not in existing:
            return slot
    return min(
        range(10),
        key=lambda slot: (
            (pool / str(slot) / BACKUP_NAME).stat().st_mtime
            if (pool / str(slot) / BACKUP_NAME).exists()
            else 0
        ),
    )


def create_backup(target: Path, source_setup_id: str | None) -> int:
    pool = backup_pool(target)
    slot = next_backup_slot(pool)
    slot_dir = pool / str(slot)
    if slot_dir.exists():
        delete_tree(slot_dir)
    slot_dir.mkdir(mode=OWNER_DIRECTORY_MODE)
    files = snapshot_files(target, managed_file_relatives())
    envelope = {
        "schema_version": 1,
        "product_name": PRODUCT_NAME,
        "build_version": VERSION,
        "slot": slot,
        "canonical_target": str(target),
        "source_setup_id": source_setup_id,
        "managed_files": [relative for relative, encoded in files.items() if encoded is not None],
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "files": files,
    }
    safe_write_file(slot_dir / BACKUP_NAME, canonical_json(envelope))
    return slot


def load_backup(target: Path, slot: int) -> dict[str, Any]:
    if slot < 0 or slot > 9:
        fail("--backup must be in the 0..9 range")
    envelope = load_json_object(
        backup_pool(target) / str(slot) / BACKUP_NAME, f"backup slot {slot}"
    )
    require_exact_keys(envelope, BACKUP_KEYS, f"backup slot {slot}")
    if envelope.get("canonical_target") != str(target):
        fail("backup does not belong to this target")
    if envelope.get("slot") != slot:
        fail("backup slot envelope mismatch")
    if not isinstance(envelope.get("files"), dict):
        fail("backup files must be an object")
    return envelope


def write_rendered_files(target: Path, setup_id: str, files: dict[str, bytes]) -> list[str]:
    previous = snapshot_files(target, managed_file_relatives())
    changed: list[str] = []
    try:
        for relative, content in files.items():
            before = previous.get(relative)
            after = base64.b64encode(content).decode("ascii")
            if before != after:
                changed.append(relative)
            safe_write_file(target / relative, content)
        final_settings = parse_json_object(files[SETTINGS_NAME], SETTINGS_NAME)
        stamp = make_stamp(target, setup_id, final_settings)
        stamp_content = canonical_json(stamp)
        before_stamp = previous.get(STAMP_NAME)
        after_stamp = base64.b64encode(stamp_content).decode("ascii")
        if before_stamp != after_stamp:
            changed.append(STAMP_NAME)
        safe_write_file(target / STAMP_NAME, stamp_content)
    except BaseException:
        restore_snapshot(target, previous)
        raise
    return changed


def command_plan(target: Path, setup_id: str) -> dict[str, Any]:
    status = status_for_target(target)
    operation = "install"
    backup_required = False
    if status["state"] == "managed":
        if status["drift"]:
            operation = "blocked"
        elif status["setup_id"] == setup_id:
            operation = "update"
        else:
            operation = "switch"
            backup_required = True
    return {
        "operation": operation,
        "setup_id": setup_id,
        "target": str(target),
        "mutates": False,
        "backup_required": backup_required,
        "state": status["state"],
        "drift": status["drift"],
    }


def command_install(target: Path, setup_id: str) -> dict[str, Any]:
    with target_lock(target):
        ensure_target_directory(target)
        status = status_for_target(target)
        if status["state"] == "managed" and status["drift"]:
            fail(f"target has drift: {', '.join(status['drift'])}")
        backup_slot = None
        if status["state"] == "managed" and status["setup_id"] != setup_id:
            backup_slot = create_backup(target, status["setup_id"])
        existing = read_current_settings(target)
        _, files = render_setup(setup_id, target, existing)
        changed = write_rendered_files(target, setup_id, files)
    return {
        "operation": "install",
        "setup_id": setup_id,
        "target": str(target),
        "changed": changed,
        "backup_slot": backup_slot,
        "builder_projection": "skills+package",
    }


def command_switch(target: Path, setup_id: str) -> dict[str, Any]:
    with target_lock(target):
        ensure_target_directory(target)
        status = require_clean_managed(target)
        backup_slot = create_backup(target, status["setup_id"])
        existing = read_current_settings(target)
        _, files = render_setup(setup_id, target, existing)
        changed = write_rendered_files(target, setup_id, files)
    return {
        "operation": "switch",
        "setup_id": setup_id,
        "target": str(target),
        "changed": changed,
        "backup_slot": backup_slot,
        "builder_projection": "skills+package",
    }


def command_restore(target: Path, slot: int) -> dict[str, Any]:
    with target_lock(target):
        ensure_target_directory(target)
        status = require_clean_managed(target)
        create_backup(target, status["setup_id"])
        envelope = load_backup(target, slot)
        previous = snapshot_files(target, managed_file_relatives())
        try:
            for relative, encoded in envelope["files"].items():
                path = target / relative
                if encoded is None:
                    with contextlib.suppress(FileNotFoundError):
                        delete_file(path)
                else:
                    safe_write_file(path, base64.b64decode(encoded.encode("ascii")))
        except BaseException:
            restore_snapshot(target, previous)
            raise
        restored_setup_id = envelope.get("source_setup_id")
        if not isinstance(restored_setup_id, str):
            fail("backup source setup id is missing")
    return {
        "operation": "restore",
        "setup_id": restored_setup_id,
        "target": str(target),
        "backup_slot": slot,
        "builder_projection": "skills+package",
    }


def command_remove(target: Path) -> dict[str, Any]:
    with target_lock(target):
        ensure_target_directory(target)
        status = require_clean_managed(target)
        create_backup(target, status["setup_id"])
        settings = read_current_settings(target)
        previous = snapshot_files(target, managed_file_relatives())
        try:
            if settings is not None:
                stripped = strip_managed_settings(settings, target)
                if stripped:
                    safe_write_file(target / SETTINGS_REL, canonical_json(stripped))
                else:
                    delete_file(target / SETTINGS_REL)
            delete_file(target / STAMP_NAME)
            delete_tree(target / BUILDER_SKILL_DIR)
            delete_tree(target / BUILDER_PACKAGE_DIR)
        except BaseException:
            restore_snapshot(target, previous)
            raise
    return {
        "operation": "remove",
        "removed_setup_id": status["setup_id"],
        "target": str(target),
        "builder_projection": "removed",
    }


def software_root(target: Path) -> Path:
    return target / SOFTWARE_DIR_NAME


def software_current(target: Path) -> Path:
    return software_root(target) / SOFTWARE_CURRENT_NAME


def software_stamp_path(target: Path) -> Path:
    return target / SOFTWARE_STAMP_NAME


def software_entrypoint(target: Path) -> Path:
    return target / "bin" / PI_COMMAND


def package_manifest_path(root: Path) -> Path:
    return root / PI_PACKAGE_RELATIVE / "package.json"


def package_binary_path(root: Path) -> Path:
    return root / PI_PACKAGE_BINARY_RELATIVE


def software_presence(target: Path) -> list[str]:
    labels = (
        (software_stamp_path(target), SOFTWARE_STAMP_NAME),
        (software_root(target), SOFTWARE_DIR_NAME),
        (software_current(target), f"{SOFTWARE_DIR_NAME}/{SOFTWARE_CURRENT_NAME}"),
        (software_entrypoint(target), "bin/pi"),
    )
    return sorted(label for path, label in labels if path.exists() or path.is_symlink())


def canonical_target_readonly(target: Path) -> str:
    info = stat_optional(target, "target")
    if info is not None and not stat.S_ISDIR(info.st_mode):
        fail("target must be a real directory")
    return str(target.resolve(strict=False))


def validate_pre_network_software_target(target: Path) -> None:
    require_safe_partial_directory(target, "target")
    require_safe_partial_directory(software_entrypoint(target).parent, "bin")
    require_safe_partial_directory(software_root(target), "software root")
    require_safe_partial_directory(software_current(target), "current software tree")
    require_safe_partial_file(
        software_entrypoint(target), "Pi entrypoint", max_bytes=SOFTWARE_FILE_MAX_BYTES
    )
    require_safe_partial_file(
        software_stamp_path(target), SOFTWARE_STAMP_NAME, max_bytes=METADATA_MAX_BYTES
    )


def load_package_manifest(root: Path) -> dict[str, Any]:
    manifest = load_json_object(package_manifest_path(root), "Pi package manifest")
    if manifest.get("name") != PI_PACKAGE_NAME:
        fail("Pi package manifest has unexpected package name")
    if manifest.get("version") != PI_PACKAGE_VERSION:
        fail("Pi package manifest has unexpected package version")
    if manifest.get("bin") not in (
        {PI_COMMAND: PI_PACKAGE_BIN},
        {PI_COMMAND: f"./{PI_PACKAGE_BIN}"},
    ):
        fail("Pi package manifest has unexpected bin mapping")
    if manifest.get("engines", {}).get("node") != PI_NODE_REQUIREMENT:
        fail("Pi package manifest has unexpected Node requirement")
    scripts = manifest.get("scripts")
    if not isinstance(scripts, dict):
        fail("Pi package manifest scripts must be an object")
    for key in ("preinstall", "install", "postinstall"):
        if key in scripts:
            fail(f"Pi package manifest must not declare consumer lifecycle script {key}")
    return manifest


def is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def private_mode_for_source(info: os.stat_result) -> int:
    return 0o700 if stat.S_IMODE(info.st_mode) & 0o100 else OWNER_FILE_MODE


def read_staged_file(source: Path, label: str) -> tuple[bytes, os.stat_result]:
    info = source.lstat()
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        fail(f"staged software entry must be a regular file: {label}")
    if info.st_size > SOFTWARE_FILE_MAX_BYTES:
        fail(f"staged software entry is too large: {label}")
    flags = os.O_RDONLY
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(source, flags)
    try:
        opened = os.fstat(descriptor)
        if identity_of(opened) != identity_of(info):
            fail(f"staged software entry changed while opening: {label}")
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = os.read(descriptor, 65536)
            if not chunk:
                break
            total += len(chunk)
            if total > SOFTWARE_FILE_MAX_BYTES:
                fail(f"staged software entry is too large: {label}")
            chunks.append(chunk)
    finally:
        os.close(descriptor)
    return b"".join(chunks), info


def copy_file_private(source: Path, destination: Path, label: str) -> None:
    content, info = read_staged_file(source, label)
    destination.parent.mkdir(mode=OWNER_DIRECTORY_MODE, parents=True, exist_ok=True)
    with destination.open("xb") as target_handle:
        target_handle.write(content)
    destination.chmod(private_mode_for_source(info))


def materialized_source(path: Path, allowed_roots: tuple[Path, ...], label: str) -> Path:
    info = path.lstat()
    if not stat.S_ISLNK(info.st_mode):
        return path
    try:
        resolved = path.resolve(strict=True)
    except FileNotFoundError:
        fail(f"staged software symlink is broken: {label}")
    if not any(is_relative_to(resolved, root) for root in allowed_roots):
        fail(f"staged software symlink escapes persisted tree: {label}")
    resolved_info = resolved.lstat()
    if stat.S_ISLNK(resolved_info.st_mode):
        resolved = resolved.resolve(strict=True)
        resolved_info = resolved.lstat()
    if not stat.S_ISREG(resolved_info.st_mode):
        fail(f"staged software symlink must resolve to a regular file: {label}")
    return resolved


def staged_node_wrapper_content(node_path: str) -> bytes:
    relative_main = f"../{PI_PACKAGE_RELATIVE}/{PI_PACKAGE_BIN}"
    return (
        "#!/bin/sh\n"
        "script_path=$0\n"
        'case "$script_path" in\n'
        "  /*) ;;\n"
        '  *) script_path="$PWD/$script_path" ;;\n'
        "esac\n"
        "script_dir=${script_path%/*}\n"
        f'exec {shlex.quote(node_path)} "$script_dir/{relative_main}" "$@"\n'
    ).encode("utf-8")


def copy_tree_sanitized(source: Path, destination: Path, allowed_roots: tuple[Path, ...]) -> None:
    require_directory(source, "staged software tree")
    paths = sorted(source.rglob("*"), key=lambda item: item.relative_to(source).as_posix())
    if len(paths) > SOFTWARE_TREE_MAX_PATHS:
        fail(
            f"staged software tree has {len(paths)} paths, exceeding "
            f"the {SOFTWARE_TREE_MAX_PATHS}-path limit"
        )
    destination.mkdir(mode=OWNER_DIRECTORY_MODE)
    total = 0
    for path in paths:
        relative = path.relative_to(source)
        target_path = destination / relative
        info = path.lstat()
        if stat.S_ISDIR(info.st_mode):
            target_path.mkdir(mode=OWNER_DIRECTORY_MODE, exist_ok=True)
            continue
        if stat.S_ISLNK(info.st_mode):
            source_file = materialized_source(path, allowed_roots, relative.as_posix())
            source_info = source_file.lstat()
            total += source_info.st_size
            if total > SOFTWARE_TREE_MAX_BYTES:
                fail(
                    "staged software tree exceeds "
                    f"the {SOFTWARE_TREE_MAX_BYTES}-byte limit"
                )
            copy_file_private(source_file, target_path, relative.as_posix())
            continue
        if not stat.S_ISREG(info.st_mode):
            fail(f"staged software entry must be a regular file: {relative.as_posix()}")
        total += info.st_size
        if total > SOFTWARE_TREE_MAX_BYTES:
            fail(
                f"staged software tree exceeds the {SOFTWARE_TREE_MAX_BYTES}-byte limit"
            )
        copy_file_private(path, target_path, relative.as_posix())


def materialize_staged_entrypoint(
    stage_workspace: Path,
    stage_current: Path,
    allowed_roots: tuple[Path, ...],
    node_runtime: dict[str, str],
) -> None:
    source_root = stage_workspace / "bin"
    require_directory(source_root, "staged bin tree")
    paths = sorted(
        source_root.rglob("*"),
        key=lambda item: item.relative_to(source_root).as_posix(),
    )
    if len(paths) > SOFTWARE_TREE_MAX_PATHS:
        fail(
            f"staged bin tree has {len(paths)} paths, exceeding "
            f"the {SOFTWARE_TREE_MAX_PATHS}-path limit"
        )
    relative_paths = [path.relative_to(source_root).as_posix() for path in paths]
    if relative_paths != [PI_COMMAND]:
        fail(f"staged bin tree has unexpected paths: {relative_paths}")
    source_entrypoint = materialized_source(
        source_root / PI_COMMAND,
        allowed_roots,
        PI_COMMAND,
    )
    expected_package_binary = (
        stage_workspace / PI_PACKAGE_BINARY_RELATIVE
    ).resolve(strict=True)
    if source_entrypoint.resolve(strict=True) != expected_package_binary:
        fail("staged Pi entrypoint does not resolve to the official package binary")
    read_staged_file(source_entrypoint, "staged Pi package entrypoint")
    destination_root = stage_current / "bin"
    destination_root.mkdir(mode=OWNER_DIRECTORY_MODE)
    destination = destination_root / PI_COMMAND
    content = staged_node_wrapper_content(node_runtime["path"])
    if len(content) > SOFTWARE_FILE_MAX_BYTES:
        fail("staged Pi wrapper exceeds the bounded file size")
    with destination.open("xb") as handle:
        handle.write(content)
    destination.chmod(0o700)


def materialize_persisted_install(
    stage_workspace: Path,
    stage_current: Path,
    node_runtime: dict[str, str],
) -> None:
    allowed_roots = (
        (stage_workspace / "install" / "global").resolve(strict=False),
        (stage_workspace / "bin").resolve(strict=False),
    )
    stage_current.mkdir(mode=OWNER_DIRECTORY_MODE)
    (stage_current / "install").mkdir(mode=OWNER_DIRECTORY_MODE)
    copy_tree_sanitized(
        stage_workspace / "install" / "global",
        stage_current / "install" / "global",
        allowed_roots,
    )
    materialize_staged_entrypoint(
        stage_workspace,
        stage_current,
        allowed_roots,
        node_runtime,
    )


def safe_bun_env(stage_workspace: Path) -> dict[str, str]:
    home = stage_workspace / "home"
    xdg_config = stage_workspace / "xdg-config"
    cache = stage_workspace / "cache"
    tmp = stage_workspace / "tmp"
    for directory in (
        home,
        xdg_config,
        cache,
        tmp,
        stage_workspace / "install" / "global",
        stage_workspace / "bin",
    ):
        directory.mkdir(mode=OWNER_DIRECTORY_MODE, parents=True, exist_ok=True)
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": str(home),
        "XDG_CONFIG_HOME": str(xdg_config),
        "TMPDIR": str(tmp),
        "BUN_INSTALL_GLOBAL_DIR": str(stage_workspace / "install" / "global"),
        "BUN_INSTALL_BIN": str(stage_workspace / "bin"),
        "BUN_INSTALL_CACHE_DIR": str(cache),
    }
    assert_no_sensitive_environment(env, "bun installer environment")
    return env


def read_process_output(handle: Any, label: str) -> str:
    handle.seek(0, os.SEEK_END)
    size = handle.tell()
    handle.seek(0)
    data = handle.read(PROCESS_OUTPUT_MAX_BYTES + 1)
    text = data.decode("utf-8", errors="replace") if isinstance(data, bytes) else str(data)
    if size > PROCESS_OUTPUT_MAX_BYTES:
        return text[:PROCESS_OUTPUT_MAX_BYTES] + f"\n[{label} truncated]\n"
    return text


def run_bun_install(stage_workspace: Path) -> None:
    command = ["bun", *BUN_INSTALL_ARGV]
    env = safe_bun_env(stage_workspace)
    with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
        try:
            completed = subprocess.run(
                command,
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=stdout,
                stderr=stderr,
                check=False,
                timeout=PROCESS_TIMEOUT_SECONDS,
            )
        except FileNotFoundError:
            fail("bun command was not found on PATH")
        except subprocess.TimeoutExpired:
            fail("bun install timed out")
        if completed.returncode != 0:
            detail = (
                read_process_output(stderr, "stderr") or read_process_output(stdout, "stdout")
            ).strip()
            fail(f"bun install failed with exit code {completed.returncode}: {detail}")


def parse_node_version(raw: str) -> tuple[int, int, int]:
    match = re.fullmatch(r"v?(\d+)\.(\d+)\.(\d+)", raw.strip())
    if not match:
        fail(f"node reported an unparseable version: {raw.strip()!r}")
    return tuple(int(part) for part in match.groups())


def resolve_node_runtime(stage_workspace: Path) -> dict[str, str]:
    node = shutil.which("node", path=os.environ.get("PATH", "/usr/bin:/bin"))
    if node is None:
        fail("node command was not found on PATH")
    try:
        canonical = Path(node).resolve(strict=True)
    except FileNotFoundError:
        fail("node command resolved to a missing path")
    info = canonical.lstat()
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        fail("node command must resolve to a regular file")
    tmp = stage_workspace / "node-probe-tmp"
    home = stage_workspace / "node-probe-home"
    for directory in (tmp, home):
        directory.mkdir(mode=OWNER_DIRECTORY_MODE, parents=True, exist_ok=True)
    env = {"HOME": str(home), "TMPDIR": str(tmp), "PATH": "/usr/bin:/bin"}
    assert_no_sensitive_environment(env, "node probe environment")
    with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
        try:
            completed = subprocess.run(
                [str(canonical), "--version"],
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=stdout,
                stderr=stderr,
                check=False,
                timeout=20,
            )
        except FileNotFoundError:
            fail("node command was not found")
        except subprocess.TimeoutExpired:
            fail("node version probe timed out")
        output = (
            read_process_output(stdout, "stdout") + read_process_output(stderr, "stderr")
        ).strip()
        if completed.returncode != 0:
            fail(f"node version probe failed with exit code {completed.returncode}: {output}")
    if parse_node_version(output) < (22, 19, 0):
        fail(f"node {output} does not satisfy {PI_NODE_REQUIREMENT}")
    return {
        "path": str(canonical),
        "version": output,
        "sha256": file_sha256(canonical, label="node runtime"),
        "requirement": PI_NODE_REQUIREMENT,
    }


def run_stage_version_probe(
    stage_current: Path, stage_workspace: Path, node_runtime: dict[str, str]
) -> str:
    home = stage_workspace / "smoke-home"
    agent_dir = stage_workspace / "smoke-agent"
    session_dir = agent_dir / "sessions"
    package_dir = agent_dir / "package-cache"
    tmp = stage_workspace / "smoke-tmp"
    for directory in (home, agent_dir, session_dir, package_dir, tmp):
        directory.mkdir(mode=OWNER_DIRECTORY_MODE, parents=True, exist_ok=True)
    node_parent = str(Path(node_runtime["path"]).parent)
    env = {
        "HOME": str(home),
        "PI_CODING_AGENT_DIR": str(agent_dir),
        "PI_CODING_AGENT_SESSION_DIR": str(session_dir),
        "PI_PACKAGE_DIR": str(package_dir),
        "PI_OFFLINE": "1",
        "PI_SKIP_VERSION_CHECK": "1",
        "PI_TELEMETRY": "0",
        "PATH": f"{node_parent}{os.pathsep}/usr/bin:/bin",
        "TMPDIR": str(tmp),
    }
    assert_no_sensitive_environment(env, "staged Pi version probe environment")
    command = [str(stage_current / "bin" / PI_COMMAND), "--version"]
    with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
        try:
            completed = subprocess.run(
                command,
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=stdout,
                stderr=stderr,
                check=False,
                timeout=PROCESS_TIMEOUT_SECONDS,
            )
        except FileNotFoundError:
            fail("staged pi executable is missing")
        except subprocess.TimeoutExpired:
            fail("staged pi version probe timed out")
        output = (
            read_process_output(stdout, "stdout") + read_process_output(stderr, "stderr")
        ).strip()
        if completed.returncode != 0:
            fail(f"staged pi version probe failed with exit code {completed.returncode}: {output}")
        if PI_PACKAGE_VERSION not in output:
            fail("staged pi version probe did not report the pinned release")
        return sha256_bytes(output.encode("utf-8"))


def node_wrapper_content(node_path: str, main_path: Path) -> bytes:
    return (
        f'#!/bin/sh\nexec {shlex.quote(node_path)} {shlex.quote(str(main_path))} "$@"\n'
    ).encode("utf-8")


def ensure_software_parent(path: Path, target: Path) -> None:
    relative_parent = path.relative_to(target).parent
    current = target
    for part in relative_parent.parts:
        current = current / part
        info = stat_optional(current, f"software parent {current}")
        if info is None:
            current.mkdir(mode=OWNER_DIRECTORY_MODE)
            continue
        if not stat.S_ISDIR(info.st_mode):
            fail(f"software parent is not a directory: {current}")
        require_current_user_owner(info, f"software parent {current}")
        if stat.S_IMODE(info.st_mode) != OWNER_DIRECTORY_MODE:
            fail(f"software parent must be private: {current}")


def atomic_write_private(path: Path, content: bytes, mode: int = OWNER_FILE_MODE) -> None:
    path.parent.mkdir(mode=OWNER_DIRECTORY_MODE, parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.nddev.tmp.{os.getpid()}.{time.time_ns()}")
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(content)
        os.replace(temporary, path)
        path.chmod(mode)
    except BaseException:
        with contextlib.suppress(FileNotFoundError):
            temporary.unlink()
        raise


def write_target_entrypoint(target: Path, node_runtime: dict[str, str]) -> str:
    destination = software_entrypoint(target)
    ensure_software_parent(destination, target)
    require_safe_partial_file(
        destination, "Pi entrypoint", max_bytes=SOFTWARE_FILE_MAX_BYTES
    )
    content = node_wrapper_content(
        node_runtime["path"], package_binary_path(software_current(target))
    )
    atomic_write_private(destination, content, 0o700)
    return file_sha256(destination, label="Pi entrypoint")


def software_stamp(
    target: Path,
    *,
    entrypoint_digest: str,
    installed_tree_digest: str,
    installed_tree_path_count: int,
    installed_tree_bytes: int,
    package_binary_digest: str,
    version_probe_digest: str,
    node_runtime: dict[str, str],
    prepublish_only: str | None,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "product_name": PRODUCT_NAME,
        "build_version": VERSION,
        "canonical_target": canonical_target_readonly(target),
        "package": PI_PACKAGE_NAME,
        "version": PI_PACKAGE_VERSION,
        "command": PI_COMMAND,
        "package_bin": PI_PACKAGE_BIN,
        "entrypoint": "bin/pi",
        "entrypoint_kind": "node-wrapper",
        "entrypoint_main": f"{SOFTWARE_DIR_NAME}/{SOFTWARE_CURRENT_NAME}/{PI_PACKAGE_BINARY_RELATIVE}",
        "installed_tree": f"{SOFTWARE_DIR_NAME}/{SOFTWARE_CURRENT_NAME}",
        "manager": "cli-tools/nddev_pi.py",
        "entrypoint_sha256": entrypoint_digest,
        "package_binary_sha256": package_binary_digest,
        "installed_tree_sha256": installed_tree_digest,
        "installed_tree_path_count": installed_tree_path_count,
        "installed_tree_bytes": installed_tree_bytes,
        "tree_limits": {
            "max_paths": SOFTWARE_TREE_MAX_PATHS,
            "max_bytes": SOFTWARE_TREE_MAX_BYTES,
        },
        "registry": {
            "integrity": PI_REGISTRY_INTEGRITY,
            "shasum": PI_REGISTRY_SHASUM,
        },
        "node_runtime": node_runtime,
        "version_probe": {
            "argv": ["bin/pi", "--version"],
            "environment": {
                "HOME": "<stage>/smoke-home",
                "PI_CODING_AGENT_DIR": "<stage>/smoke-agent",
                "PI_CODING_AGENT_SESSION_DIR": "<stage>/smoke-agent/sessions",
                "PI_PACKAGE_DIR": "<stage>/smoke-agent/package-cache",
                "PI_OFFLINE": "1",
                "PI_SKIP_VERSION_CHECK": "1",
                "PI_TELEMETRY": "0",
                "PATH": "<node-dir>:/usr/bin:/bin",
                "TMPDIR": "<stage>/smoke-tmp",
            },
            "stdout_stderr_sha256": version_probe_digest,
        },
        "official_package_scripts": {
            "preinstall": None,
            "install": None,
            "postinstall": None,
            "prepublishOnly": prepublish_only,
        },
        "installer": {
            "tool": "bun",
            "argv": BUN_INSTALL_ARGV,
            "trust_reason": None,
            "env": {
                "BUN_INSTALL_GLOBAL_DIR": "<stage>/install/global",
                "BUN_INSTALL_BIN": "<stage>/bin",
                "BUN_INSTALL_CACHE_DIR": "<stage>/cache",
                "HOME": "<stage>/home",
                "XDG_CONFIG_HOME": "<stage>/xdg-config",
                "TMPDIR": "<stage>/tmp",
            },
        },
    }


def read_software_stamp(target: Path) -> dict[str, Any] | None:
    path = software_stamp_path(target)
    info = stat_optional(path, SOFTWARE_STAMP_NAME)
    if info is None:
        return None
    if not stat.S_ISREG(info.st_mode):
        fail("software stamp must be a regular file")
    require_current_user_owner(info, SOFTWARE_STAMP_NAME)
    if info.st_nlink != 1:
        fail("software stamp must not be a hardlink")
    if stat.S_IMODE(info.st_mode) != OWNER_FILE_MODE:
        fail("software stamp mode must be 0600")
    stamp = load_json_object(path, SOFTWARE_STAMP_NAME)
    require_exact_keys(stamp, SOFTWARE_STAMP_KEYS, SOFTWARE_STAMP_NAME)
    require_exact_keys(stamp["registry"], SOFTWARE_STAMP_REGISTRY_KEYS, "software stamp registry")
    require_exact_keys(
        stamp["tree_limits"],
        SOFTWARE_STAMP_TREE_LIMIT_KEYS,
        "software stamp tree_limits",
    )
    require_exact_keys(
        stamp["node_runtime"], SOFTWARE_STAMP_NODE_KEYS, "software stamp node_runtime"
    )
    require_exact_keys(
        stamp["version_probe"], SOFTWARE_STAMP_PROBE_KEYS, "software stamp version_probe"
    )
    require_exact_keys(
        stamp["official_package_scripts"],
        SOFTWARE_STAMP_SCRIPT_KEYS,
        "software stamp official_package_scripts",
    )
    installer = stamp["installer"]
    require_exact_keys(installer, SOFTWARE_STAMP_INSTALLER_KEYS, "software stamp installer")
    require_exact_keys(
        installer["env"], SOFTWARE_STAMP_INSTALLER_ENV_KEYS, "software stamp installer env"
    )
    if stamp.get("product_name") != PRODUCT_NAME:
        fail("software stamp belongs to another product")
    if stamp.get("canonical_target") != canonical_target_readonly(target):
        fail("software stamp is bound to a different canonical target")
    return stamp


def expected_installer_env() -> dict[str, str]:
    return {
        "BUN_INSTALL_GLOBAL_DIR": "<stage>/install/global",
        "BUN_INSTALL_BIN": "<stage>/bin",
        "BUN_INSTALL_CACHE_DIR": "<stage>/cache",
        "HOME": "<stage>/home",
        "XDG_CONFIG_HOME": "<stage>/xdg-config",
        "TMPDIR": "<stage>/tmp",
    }


def expected_probe_env() -> dict[str, str]:
    return {
        "HOME": "<stage>/smoke-home",
        "PI_CODING_AGENT_DIR": "<stage>/smoke-agent",
        "PI_CODING_AGENT_SESSION_DIR": "<stage>/smoke-agent/sessions",
        "PI_PACKAGE_DIR": "<stage>/smoke-agent/package-cache",
        "PI_OFFLINE": "1",
        "PI_SKIP_VERSION_CHECK": "1",
        "PI_TELEMETRY": "0",
        "PATH": "<node-dir>:/usr/bin:/bin",
        "TMPDIR": "<stage>/smoke-tmp",
    }


def software_status_payload(target: Path) -> dict[str, Any]:
    canonical = canonical_target_readonly(target)
    payload: dict[str, Any] = {
        "installed": False,
        "current": False,
        "package": PI_PACKAGE_NAME,
        "version": None,
        "expected_version": PI_PACKAGE_VERSION,
        "command": PI_COMMAND,
        "executable": str(software_entrypoint(target)),
        "installed_tree": str(software_current(target)),
        "drift": [],
        "present": False,
        "presence": [],
        "canonical_target": canonical,
        "live_check": False,
    }
    if not target.exists():
        return payload
    target_info = require_directory(target, "target")
    require_current_user_owner(target_info, "target")
    if stat.S_IMODE(target_info.st_mode) != OWNER_DIRECTORY_MODE:
        fail("target must be private")
    presence = software_presence(target)
    payload["present"] = bool(presence)
    payload["presence"] = presence
    stamp = read_software_stamp(target)
    if stamp is None:
        return payload
    payload["installed"] = True
    payload["version"] = stamp.get("version")
    drift: list[str] = []
    try:
        root_info = stat_optional(software_root(target), "software root")
        if root_info is None or not stat.S_ISDIR(root_info.st_mode):
            drift.append(SOFTWARE_DIR_NAME)
        elif stat.S_IMODE(root_info.st_mode) != OWNER_DIRECTORY_MODE:
            drift.append("software_root_mode")
        current_info = stat_optional(software_current(target), "current software tree")
        if current_info is None or not stat.S_ISDIR(current_info.st_mode):
            drift.append(SOFTWARE_CURRENT_NAME)
        elif stat.S_IMODE(current_info.st_mode) != OWNER_DIRECTORY_MODE:
            drift.append("software_current_mode")
        entrypoint_info = require_regular_file(
            software_entrypoint(target),
            "Pi entrypoint",
            max_bytes=SOFTWARE_FILE_MAX_BYTES,
        )
        require_current_user_owner(entrypoint_info, "Pi entrypoint")
        if stat.S_IMODE(entrypoint_info.st_mode) != 0o700:
            drift.append("entrypoint_mode")
        manifest = load_package_manifest(software_current(target))
        scripts = manifest.get("scripts", {})
        prepublish_only = scripts.get("prepublishOnly")
        entrypoint_digest = file_sha256(software_entrypoint(target), label="Pi entrypoint")
        package_binary_digest = file_sha256(
            package_binary_path(software_current(target)), label="Pi package binary"
        )
        (
            installed_tree_digest,
            installed_tree_path_count,
            installed_tree_bytes,
        ) = software_tree_identity(software_current(target))
        payload["installed_tree_path_count"] = installed_tree_path_count
        payload["installed_tree_bytes"] = installed_tree_bytes
        node_runtime = stamp.get("node_runtime")
        if isinstance(node_runtime, dict):
            node_path = Path(str(node_runtime.get("path", "")))
            if not node_path.is_absolute():
                drift.append("node_runtime")
            else:
                node_info = require_regular_file(
                    node_path, "node runtime", max_bytes=SOFTWARE_FILE_MAX_BYTES
                )
                if stat.S_ISLNK(node_info.st_mode):
                    drift.append("node_runtime")
                if file_sha256(node_path, label="node runtime") != node_runtime.get("sha256"):
                    drift.append("node_runtime")
        expected_wrapper = node_wrapper_content(
            str(stamp.get("node_runtime", {}).get("path", "")),
            package_binary_path(software_current(target)),
        )
        checks = {
            "schema_version": stamp.get("schema_version") == 1,
            "product_name": stamp.get("product_name") == PRODUCT_NAME,
            "build_version": stamp.get("build_version") == VERSION,
            "canonical_target": stamp.get("canonical_target") == canonical,
            "package": stamp.get("package") == PI_PACKAGE_NAME,
            "version": stamp.get("version") == PI_PACKAGE_VERSION,
            "command": stamp.get("command") == PI_COMMAND,
            "package_bin": stamp.get("package_bin") == PI_PACKAGE_BIN,
            "entrypoint": stamp.get("entrypoint") == "bin/pi",
            "entrypoint_kind": stamp.get("entrypoint_kind") == "node-wrapper",
            "entrypoint_main": stamp.get("entrypoint_main")
            == f"{SOFTWARE_DIR_NAME}/{SOFTWARE_CURRENT_NAME}/{PI_PACKAGE_BINARY_RELATIVE}",
            "installed_tree": stamp.get("installed_tree")
            == f"{SOFTWARE_DIR_NAME}/{SOFTWARE_CURRENT_NAME}",
            "manager": stamp.get("manager") == "cli-tools/nddev_pi.py",
            "entrypoint_sha256": stamp.get("entrypoint_sha256") == entrypoint_digest,
            "package_binary_sha256": stamp.get("package_binary_sha256") == package_binary_digest,
            "installed_tree_sha256": stamp.get("installed_tree_sha256") == installed_tree_digest,
            "installed_tree_path_count": stamp.get("installed_tree_path_count")
            == installed_tree_path_count,
            "installed_tree_bytes": stamp.get("installed_tree_bytes")
            == installed_tree_bytes,
            "tree_limits": stamp.get("tree_limits")
            == {
                "max_paths": SOFTWARE_TREE_MAX_PATHS,
                "max_bytes": SOFTWARE_TREE_MAX_BYTES,
            },
            "entrypoint_content": read_regular_file(
                software_entrypoint(target),
                "Pi entrypoint",
                max_bytes=SOFTWARE_FILE_MAX_BYTES,
            )
            == expected_wrapper,
        }
        for label, ok in checks.items():
            if not ok:
                drift.append(label)
        registry = stamp.get("registry")
        if (
            not isinstance(registry, dict)
            or registry.get("integrity") != PI_REGISTRY_INTEGRITY
            or registry.get("shasum") != PI_REGISTRY_SHASUM
        ):
            drift.append("registry")
        installer = stamp.get("installer")
        if (
            not isinstance(installer, dict)
            or installer.get("tool") != "bun"
            or installer.get("argv") != BUN_INSTALL_ARGV
            or installer.get("env") != expected_installer_env()
            or installer.get("trust_reason") is not None
        ):
            drift.append("installer")
        official_scripts = stamp.get("official_package_scripts")
        if (
            not isinstance(official_scripts, dict)
            or official_scripts.get("preinstall") is not None
            or official_scripts.get("install") is not None
            or official_scripts.get("postinstall") is not None
            or official_scripts.get("prepublishOnly") != prepublish_only
        ):
            drift.append("official_package_scripts")
        probe = stamp.get("version_probe")
        if (
            not isinstance(probe, dict)
            or probe.get("argv") != ["bin/pi", "--version"]
            or probe.get("environment") != expected_probe_env()
            or not isinstance(probe.get("stdout_stderr_sha256"), str)
        ):
            drift.append("version_probe")
        node = stamp.get("node_runtime")
        if (
            not isinstance(node, dict)
            or node.get("requirement") != PI_NODE_REQUIREMENT
            or not isinstance(node.get("version"), str)
            or parse_node_version(str(node.get("version"))) < (22, 19, 0)
        ):
            drift.append("node_runtime")
    except PiSetupError as exc:
        drift.append(str(exc))
    payload["drift"] = sorted(set(drift))
    payload["current"] = not drift and stamp.get("version") == PI_PACKAGE_VERSION
    return payload


def software_precondition_state(target: Path) -> dict[str, Any]:
    validate_pre_network_software_target(target)
    try:
        return software_status_payload(target)
    except PiSetupError as exc:
        info = stat_optional(target, "target")
        if info is None or not stat.S_ISDIR(info.st_mode):
            raise
        presence = software_presence(target)
        if not presence:
            raise
        validate_pre_network_software_target(target)
        return {
            "installed": False,
            "current": False,
            "present": True,
            "presence": presence,
            "drift": [str(exc)],
            "package": PI_PACKAGE_NAME,
            "version": None,
            "expected_version": PI_PACKAGE_VERSION,
            "command": PI_COMMAND,
            "executable": str(software_entrypoint(target)),
            "installed_tree": str(software_current(target)),
            "canonical_target": canonical_target_readonly(target),
            "live_check": False,
        }


def snapshot_software_file(
    path: Path, label: str, max_bytes: int
) -> tuple[bytes | None, int | None]:
    info = stat_optional(path, label)
    if info is None:
        return None, None
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        fail(f"{label} must be a regular non-hardlinked file")
    content = read_regular_file(path, label, max_bytes=max_bytes)
    return content, stat.S_IMODE(info.st_mode)


def restore_software_file(
    path: Path,
    target: Path,
    data: bytes | None,
    mode: int | None,
    *,
    remove_empty_parent: bool,
) -> None:
    if data is None:
        with contextlib.suppress(FileNotFoundError):
            path.unlink()
        if remove_empty_parent:
            with contextlib.suppress(OSError):
                path.parent.rmdir()
        return
    ensure_software_parent(path, target)
    atomic_write_private(path, data, mode or OWNER_FILE_MODE)


def remove_created_target_if_empty(target: Path) -> None:
    for candidate in (software_stamp_path(target), software_entrypoint(target)):
        with contextlib.suppress(FileNotFoundError):
            candidate.unlink()
    for candidate in (
        software_entrypoint(target).parent,
        software_current(target),
        software_root(target),
        target,
    ):
        with contextlib.suppress(OSError):
            candidate.rmdir()


def install_or_update_software(target: Path, *, update: bool) -> dict[str, Any]:
    preflight = software_precondition_state(target)
    if preflight["current"]:
        return {
            "changed": False,
            "package": PI_PACKAGE_NAME,
            "version": PI_PACKAGE_VERSION,
            "command": PI_COMMAND,
            "executable": str(software_entrypoint(target)),
            "installed_tree": str(software_current(target)),
            "target": canonical_target_readonly(target),
        }
    if update and not preflight["present"]:
        fail("software-update requires existing target-owned Pi software presence")
    if not update and preflight["present"]:
        fail(
            "software-install found partial or non-current target-owned Pi software; use software-update"
        )

    with target_lock(target):
        created_target = stat_optional(target, "target") is None
        try:
            status = software_precondition_state(target)
            if status["current"]:
                return {
                    "changed": False,
                    "package": PI_PACKAGE_NAME,
                    "version": PI_PACKAGE_VERSION,
                    "command": PI_COMMAND,
                    "executable": str(software_entrypoint(target)),
                    "installed_tree": str(software_current(target)),
                    "target": canonical_target_readonly(target),
                }
            if update and not status["present"]:
                fail("software-update requires existing target-owned Pi software presence")
            if not update and status["present"]:
                fail(
                    "software-install found partial or non-current target-owned Pi software; use software-update"
                )

            parent = target.parent
            with (
                tempfile.TemporaryDirectory(
                    prefix=f".{target.name}{SOFTWARE_STAGE_FRAGMENT}.",
                    dir=str(parent),
                ) as stage_raw,
                tempfile.TemporaryDirectory(
                    prefix=f".{target.name}.nddev-pi-software-rollback.",
                    dir=str(parent),
                ) as rollback_raw,
            ):
                stage_root = Path(stage_raw)
                rollback_root = Path(rollback_raw)
                node_runtime = resolve_node_runtime(stage_root)
                stage_install = stage_root / "install-output"
                stage_current = stage_root / SOFTWARE_CURRENT_NAME
                run_bun_install(stage_install)
                manifest = load_package_manifest(stage_install)
                prepublish_only = manifest.get("scripts", {}).get("prepublishOnly")
                materialize_persisted_install(
                    stage_install,
                    stage_current,
                    node_runtime,
                )
                staged_entrypoint = stage_current / "bin" / PI_COMMAND
                require_regular_file(
                    staged_entrypoint,
                    "staged Pi entrypoint",
                    max_bytes=SOFTWARE_FILE_MAX_BYTES,
                )
                package_binary = package_binary_path(stage_current)
                require_regular_file(
                    package_binary,
                    "staged Pi package binary",
                    max_bytes=SOFTWARE_FILE_MAX_BYTES,
                )
                version_probe_digest = run_stage_version_probe(
                    stage_current, stage_root, node_runtime
                )
                package_binary_digest = file_sha256(
                    package_binary, label="staged Pi package binary"
                )
                (
                    installed_tree_digest,
                    installed_tree_path_count,
                    installed_tree_bytes,
                ) = software_tree_identity(stage_current)

                if created_target:
                    target.mkdir(mode=OWNER_DIRECTORY_MODE)
                    os.chmod(target, OWNER_DIRECTORY_MODE)
                else:
                    require_safe_partial_directory(target, "target")
                software_root_was_present = (
                    stat_optional(software_root(target), "software root") is not None
                )
                entrypoint_parent_was_present = (
                    stat_optional(software_entrypoint(target).parent, "bin") is not None
                )
                software_root(target).mkdir(mode=OWNER_DIRECTORY_MODE, exist_ok=True)
                os.chmod(software_root(target), OWNER_DIRECTORY_MODE)
                current = software_current(target)
                rollback_current = rollback_root / SOFTWARE_CURRENT_NAME
                previous_entrypoint, previous_entrypoint_mode = snapshot_software_file(
                    software_entrypoint(target),
                    "Pi entrypoint",
                    SOFTWARE_FILE_MAX_BYTES,
                )
                previous_stamp, previous_stamp_mode = snapshot_software_file(
                    software_stamp_path(target), SOFTWARE_STAMP_NAME, METADATA_MAX_BYTES
                )
                current_moved = False
                new_current_installed = False
                try:
                    current_info = stat_optional(current, "current software tree")
                    if current_info is not None:
                        if not stat.S_ISDIR(current_info.st_mode):
                            fail("current software tree must be a directory")
                        current.rename(rollback_current)
                        current_moved = True
                    stage_current.rename(current)
                    new_current_installed = True
                    entrypoint_digest = write_target_entrypoint(target, node_runtime)
                    if os.environ.get("NDDEV_PI_TEST_FAIL_AFTER_ENTRYPOINT") == "1":
                        fail("injected software swap failure after entrypoint")
                    stamp = software_stamp(
                        target,
                        entrypoint_digest=entrypoint_digest,
                        installed_tree_digest=installed_tree_digest,
                        installed_tree_path_count=installed_tree_path_count,
                        installed_tree_bytes=installed_tree_bytes,
                        package_binary_digest=package_binary_digest,
                        version_probe_digest=version_probe_digest,
                        node_runtime=node_runtime,
                        prepublish_only=prepublish_only,
                    )
                    atomic_write_private(
                        software_stamp_path(target), canonical_json(stamp), OWNER_FILE_MODE
                    )
                    verified = software_status_payload(target)
                    if not verified["current"]:
                        fail(
                            f"installed software failed status verification: {', '.join(verified['drift'])}"
                        )
                except BaseException:
                    if new_current_installed:
                        shutil.rmtree(current, ignore_errors=True)
                    if current_moved:
                        rollback_current.rename(current)
                    restore_software_file(
                        software_entrypoint(target),
                        target,
                        previous_entrypoint,
                        previous_entrypoint_mode,
                        remove_empty_parent=not entrypoint_parent_was_present,
                    )
                    restore_software_file(
                        software_stamp_path(target),
                        target,
                        previous_stamp,
                        previous_stamp_mode,
                        remove_empty_parent=False,
                    )
                    if not software_root_was_present:
                        with contextlib.suppress(OSError):
                            software_root(target).rmdir()
                    raise
                return {
                    "changed": True,
                    "package": PI_PACKAGE_NAME,
                    "version": PI_PACKAGE_VERSION,
                    "command": PI_COMMAND,
                    "executable": str(software_entrypoint(target)),
                    "installed_tree": str(software_current(target)),
                    "target": canonical_target_readonly(target),
                }
        except BaseException:
            if created_target:
                remove_created_target_if_empty(target)
            raise


def software_plan(target: Path) -> dict[str, Any]:
    status = software_precondition_state(target)
    operation = "none"
    if not status["present"]:
        operation = "install"
    elif not status["current"]:
        operation = "repair-or-update"
    return {
        "operation": operation,
        "target": canonical_target_readonly(target),
        "mutates": False,
        "package": PI_PACKAGE_NAME,
        "version": PI_PACKAGE_VERSION,
        "installed": status["installed"],
        "current": status["current"],
        "presence": status["presence"],
        "drift": status["drift"],
    }


def build_child_env(target: Path, node_runtime: dict[str, str]) -> dict[str, str]:
    child_env = child_base_environment()
    runtime_home = target / ".nddev-pi-runtime" / "home"
    xdg_config = target / ".nddev-pi-runtime" / "xdg-config"
    xdg_data = target / ".nddev-pi-runtime" / "xdg-data"
    xdg_state = target / ".nddev-pi-runtime" / "xdg-state"
    xdg_cache = target / ".nddev-pi-runtime" / "xdg-cache"
    tmp = target / ".nddev-pi-runtime" / "tmp"
    agent_dir = target / "agent"
    session_dir = agent_dir / "sessions"
    package_dir = agent_dir / "package-cache"
    for directory in (
        runtime_home,
        xdg_config,
        xdg_data,
        xdg_state,
        xdg_cache,
        tmp,
        agent_dir,
        session_dir,
        package_dir,
    ):
        ensure_directory(directory)
        directory.chmod(OWNER_DIRECTORY_MODE)
    node_parent = str(Path(node_runtime["path"]).parent)
    child_env.update(
        {
            "HOME": str(runtime_home.resolve()),
            "XDG_CONFIG_HOME": str(xdg_config.resolve()),
            "XDG_DATA_HOME": str(xdg_data.resolve()),
            "XDG_STATE_HOME": str(xdg_state.resolve()),
            "XDG_CACHE_HOME": str(xdg_cache.resolve()),
            "TMPDIR": str(tmp.resolve()),
            "PATH": (
                f"{software_entrypoint(target).parent.resolve()}"
                f"{os.pathsep}{node_parent}{os.pathsep}/usr/bin:/bin"
            ),
            "PI_CODING_AGENT_DIR": str(agent_dir.resolve()),
            "PI_CODING_AGENT_SESSION_DIR": str(session_dir.resolve()),
            "PI_PACKAGE_DIR": str(package_dir.resolve()),
            "PI_OFFLINE": "1",
            "PI_SKIP_VERSION_CHECK": "1",
            "PI_TELEMETRY": "0",
        }
    )
    assert_no_sensitive_environment(child_env, "Pi child environment")
    return child_env


def require_safe_launch_args(child_args: list[str]) -> None:
    first_non_option_checked = False
    index = 0
    while index < len(child_args):
        token = child_args[index]
        if token == "--":
            return
        if (
            not first_non_option_checked
            and token
            and not token.startswith("-")
            and not token.startswith("@")
        ):
            first_non_option_checked = True
            if token in LAUNCH_BLOCKED_COMMANDS:
                fail(f"launch argument {token} is not allowed: {LAUNCH_BLOCKED_COMMANDS[token]}")
        if token in LAUNCH_BLOCKED_BOOLEAN_FLAGS:
            fail(f"launch argument {token} is not allowed: {LAUNCH_BLOCKED_BOOLEAN_FLAGS[token]}")
        flag = token.split("=", 1)[0]
        if flag in LAUNCH_BLOCKED_VALUE_FLAGS:
            fail(f"launch argument {flag} is not allowed: {LAUNCH_BLOCKED_VALUE_FLAGS[flag]}")
        index += 1


def prepare_launch_invocation(
    target: Path, forwarded: list[str]
) -> tuple[list[str], dict[str, str]]:
    user_args = list(forwarded)
    if user_args and user_args[0] == "--":
        user_args = user_args[1:]
    with target_lock(target):
        require_clean_managed(target)
        software = software_status_payload(target)
        if not software["current"]:
            drift = software.get("drift") or ["target-owned Pi package is not installed"]
            fail(f"launch requires current target-owned Pi package: {', '.join(drift)}")
        stamp = read_software_stamp(target)
        if stamp is None:
            fail("target-owned Pi software stamp is missing")
        executable = software_entrypoint(target)
        executable_info = require_regular_file(
            executable,
            "target-owned Pi executable",
            max_bytes=SOFTWARE_FILE_MAX_BYTES,
        )
        require_current_user_owner(executable_info, "target-owned Pi executable")
        if stat.S_IMODE(executable_info.st_mode) != 0o700:
            fail("target-owned Pi executable must be private executable")
        require_safe_launch_args(user_args)
        settings = read_current_settings(target)
        if settings is None:
            fail("managed settings are missing")
        nddev_settings = settings.get("nddev")
        if not isinstance(nddev_settings, dict):
            fail("managed nddev settings are missing")
        launch_args = validate_string_array(
            nddev_settings.get("launch_args"), "managed launch_args"
        )
        child_args = [*launch_args, "--skill", builder_skill_path(target), *user_args]
        child_env = build_child_env(target, stamp["node_runtime"])
        return [str(executable), *child_args], child_env


def command_launch(target: Path, forwarded: list[str]) -> int:
    command, child_env = prepare_launch_invocation(target, forwarded)
    try:
        completed = subprocess.run(command, env=child_env, check=False)
    except FileNotFoundError:
        fail("target-owned pi executable is missing")
    return completed.returncode


def emit(payload: dict[str, Any], json_enabled: bool) -> None:
    if json_enabled:
        sys.stdout.write(canonical_json(payload).decode("utf-8"))
    else:
        sys.stdout.write(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    list_parser = subparsers.add_parser("list")
    list_parser.add_argument("--json", action="store_true")

    for command in ("status", "plan", "install", "switch", "restore", "remove"):
        command_parser = subparsers.add_parser(command)
        command_parser.add_argument("--target")
        command_parser.add_argument("--json", action="store_true")
        if command in {"plan", "install", "switch"}:
            command_parser.add_argument("--setup")
        if command == "restore":
            command_parser.add_argument("--backup", type=int)

    launch_parser = subparsers.add_parser("launch")
    launch_parser.add_argument("--target")
    launch_parser.add_argument("--json", action="store_true")
    launch_parser.add_argument("forwarded", nargs=argparse.REMAINDER)

    for command in ("software-plan", "software-status", "software-install", "software-update"):
        command_parser = subparsers.add_parser(command)
        command_parser.add_argument("--target")
        command_parser.add_argument("--json", action="store_true")

    return parser


def require_setup_argument(setup_id: str | None) -> str:
    if not setup_id:
        fail("--setup is required")
    validate_setup_id(setup_id)
    load_setup(setup_id)
    return setup_id


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    json_enabled = bool(getattr(args, "json", False))
    try:
        if args.command == "list":
            emit({"setups": list_setups()}, json_enabled)
            return 0
        if args.command == "status":
            emit(status_for_target(resolve_target(args.target)), json_enabled)
            return 0
        if args.command == "plan":
            emit(
                command_plan(resolve_target(args.target), require_setup_argument(args.setup)),
                json_enabled,
            )
            return 0
        if args.command == "install":
            emit(
                command_install(resolve_target(args.target), require_setup_argument(args.setup)),
                json_enabled,
            )
            return 0
        if args.command == "switch":
            emit(
                command_switch(resolve_target(args.target), require_setup_argument(args.setup)),
                json_enabled,
            )
            return 0
        if args.command == "restore":
            if args.backup is None:
                fail("--backup is required")
            emit(command_restore(resolve_target(args.target), args.backup), json_enabled)
            return 0
        if args.command == "remove":
            emit(command_remove(resolve_target(args.target)), json_enabled)
            return 0
        if args.command == "launch":
            return command_launch(resolve_target(args.target), args.forwarded)
        if args.command == "software-plan":
            emit(software_plan(resolve_target(args.target)), json_enabled)
            return 0
        if args.command == "software-status":
            emit(software_status_payload(resolve_target(args.target)), json_enabled)
            return 0
        if args.command == "software-install":
            emit(
                install_or_update_software(resolve_target(args.target), update=False), json_enabled
            )
            return 0
        if args.command == "software-update":
            emit(install_or_update_software(resolve_target(args.target), update=True), json_enabled)
            return 0
    except PiSetupError as exc:
        if json_enabled:
            emit({"error": str(exc)}, True)
        else:
            print(f"nddev_pi.py: error: {exc}", file=sys.stderr)
        return 2
    parser.error(f"unsupported command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
