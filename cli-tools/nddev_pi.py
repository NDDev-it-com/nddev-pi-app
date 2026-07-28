#!/usr/bin/env python3
"""Transactional setup manager for caller-selected Pi Coding Agent targets."""

from __future__ import annotations

import argparse
import base64
import binascii
import contextlib
import fcntl
import hashlib
import io
import json
import os
import platform
import re
import shlex
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import time
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, NoReturn

ROOT = Path(__file__).resolve().parents[1]
CATALOG_ROOT = ROOT / "setups"
PROFILES_ROOT = ROOT / "profiles"
VERSION = (ROOT / "VERSION").read_text(encoding="ascii").strip()
PRODUCT_NAME = "nddev-pi-app"
PI_COMMAND = "pi"
DEFAULT_SETUP_ID = "nddev-builder"
DEFAULT_PROFILE_ID = "full-auto"
SETTINGS_REL = Path("agent") / "settings.json"
SETTINGS_NAME = SETTINGS_REL.as_posix()
AGENTS_REL = Path("agent") / "AGENTS.md"
AGENTS_NAME = AGENTS_REL.as_posix()
STAMP_NAME = "NDDEV-PI-SETUP.json"
BACKUP_NAME = "NDDEV-PI-BACKUP.json"
OWNER_FILE_MODE = 0o600
OWNER_DIRECTORY_MODE = 0o700
METADATA_MAX_BYTES = 256 * 1024
MANAGED_PAYLOAD_MAX_BYTES = 8 * 1024 * 1024
LOCK_BINDING_MAX_BYTES = 16 * 1024
LOCK_NAMESPACE_NAME = "nddev-pi-app-locks"
LOCK_PRODUCT_ANCHOR_NAME = "global.lock"
LOCK_TARGET_SUFFIX = ".target.lock"
LOCK_TEMP_PREFIX = ".nddev-pi-publish."
CLEANUP_DIR_NAME = ".nddev-pi-cleanup"
CLEANUP_INTENT_NAME = "prepare-intent.json"
CLEANUP_JOURNAL_NAME = "pending.json"
CLEANUP_TOMBSTONES_NAME = "tombstones"
CLEANUP_MAX_ENTRIES = 4
CLEANUP_MAX_OBJECTS = 25000
CLEANUP_MAX_BYTES = 192 * 1024 * 1024
IDENTIFIER_PATTERN = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")
SETUP_ID_PATTERN = IDENTIFIER_PATTERN
PROFILE_ID_PATTERN = IDENTIFIER_PATTERN
BUILDER_SOURCE_ROOT = ROOT / "builder" / "nddev-builder"
BUILDER_SKILL_DIR = Path("agent") / "skills" / "nddev-builder"
BUILDER_PACKAGE_DIR = Path("agent") / "packages" / "nddev-builder"
BUILDER_FILES = (
    (BUILDER_SOURCE_ROOT / "AGENTS.md", AGENTS_REL),
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
    "profile_id",
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
    "source_profile_id",
    "managed_files",
    "created_at",
    "files",
    "file_metadata",
}
CHILD_ENV_ALLOWLIST = {
    "LANG",
    "LC_ALL",
    "TERM",
    "COLORTERM",
    "SYSTEMROOT",
}
PROVIDER_ENV_ALLOWLIST = {
    "ANTHROPIC_AUTH_TOKEN",
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_OAUTH_TOKEN",
    "ANT_LING_API_KEY",
    "AI_GATEWAY_API_KEY",
    "AWS_ACCESS_KEY_ID",
    "AWS_BEARER_TOKEN_BEDROCK",
    "AWS_DEFAULT_REGION",
    "AWS_PROFILE",
    "AWS_REGION",
    "AWS_SECRET_ACCESS_KEY",
    "AWS_SESSION_TOKEN",
    "AZURE_OPENAI_API_KEY",
    "AZURE_OPENAI_API_VERSION",
    "AZURE_OPENAI_BASE_URL",
    "AZURE_OPENAI_DEPLOYMENT_NAME_MAP",
    "AZURE_OPENAI_ENDPOINT",
    "AZURE_OPENAI_RESOURCE_NAME",
    "CEREBRAS_API_KEY",
    "CLOUDFLARE_ACCOUNT_ID",
    "CLOUDFLARE_API_KEY",
    "CLOUDFLARE_GATEWAY_ID",
    "DEEPSEEK_API_KEY",
    "FIREWORKS_API_KEY",
    "GEMINI_API_KEY",
    "GOOGLE_API_KEY",
    "GROQ_API_KEY",
    "KIMI_API_KEY",
    "MINIMAX_API_KEY",
    "MISTRAL_API_KEY",
    "MOONSHOT_API_KEY",
    "NVIDIA_API_KEY",
    "OPENCODE_API_KEY",
    "OPENAI_API_KEY",
    "OPENAI_BASE_URL",
    "OPENROUTER_API_KEY",
    "QWEN_TOKEN_PLAN_API_KEY",
    "QWEN_TOKEN_PLAN_CN_API_KEY",
    "TOGETHER_API_KEY",
    "XIAOMI_API_KEY",
    "XIAOMI_TOKEN_PLAN_AMS_API_KEY",
    "XIAOMI_TOKEN_PLAN_CN_API_KEY",
    "XIAOMI_TOKEN_PLAN_SGP_API_KEY",
    "XAI_API_KEY",
    "ZAI_API_KEY",
    "ZAI_CODING_CN_API_KEY",
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
PI_CLI_VERSION_OUTPUT = "0.0.0"
PI_NODE_REQUIREMENT = ">=22.19.0"
PI_REGISTRY_INTEGRITY = "sha512-zbkAhoIuDPMF3pKuja0ajZabrMWU29FUMV9A/XMXT/XC1yXs5xt6t6t13GogQFsDrDqbFP4DkZQO1w8rWRAzYA=="
PI_REGISTRY_SHASUM = "39c00809ff5531b6552b9ecb2c41f4c3529ec988"
PI_REGISTRY_TARBALL_URL = (
    "https://registry.npmjs.org/@earendil-works/pi-coding-agent/-/pi-coding-agent-0.82.1.tgz"
)
NPM_VIEW_ARGV = [
    "view",
    f"{PI_PACKAGE_NAME}@{PI_PACKAGE_VERSION}",
    "dist",
    "--json",
]
NPM_PACK_ARGV = [
    "pack",
    "--json",
    "--ignore-scripts",
    "--pack-destination",
    "<stage>/tarballs",
    f"{PI_PACKAGE_NAME}@{PI_PACKAGE_VERSION}",
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
SOFTWARE_STAMP_NAME = "NDDEV-PI-SOFTWARE.json"
SOFTWARE_DIR_NAME = ".nddev-pi-software"
SOFTWARE_CURRENT_NAME = "current"
SOFTWARE_STAGE_FRAGMENT = ".nddev-pi-software-stage"
SOFTWARE_FILE_MAX_BYTES = 192 * 1024 * 1024
SOFTWARE_TREE_MAX_BYTES = 192 * 1024 * 1024
SOFTWARE_TREE_MAX_PATHS = 25000
PROCESS_OUTPUT_MAX_BYTES = 64 * 1024
PROCESS_TIMEOUT_SECONDS = 120
PI_PACKAGE_RELATIVE = "install/lib/node_modules/@earendil-works/pi-coding-agent"
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
SOFTWARE_STAMP_REGISTRY_KEYS = {"integrity", "shasum", "tarball"}
SOFTWARE_STAMP_TREE_LIMIT_KEYS = {"max_paths", "max_bytes"}
SOFTWARE_STAMP_NODE_KEYS = {"path", "version", "sha256", "requirement"}
SOFTWARE_STAMP_PROBE_KEYS = {
    "argv",
    "environment",
    "expected_output",
    "package_version",
    "stdout_stderr_sha256",
}
SOFTWARE_STAMP_SCRIPT_KEYS = {"preinstall", "install", "postinstall", "prepublishOnly"}
SOFTWARE_STAMP_INSTALLER_KEYS = {
    "tool",
    "metadata_argv",
    "pack_argv",
    "local_install_argv",
    "argv",
    "trust_reason",
    "env",
    "byte_verification",
}
SOFTWARE_STAMP_INSTALLER_ENV_KEYS = {
    "HOME",
    "npm_config_cache",
    "npm_config_ignore_scripts",
    "npm_config_userconfig",
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
    "--no-session": "session persistence override",
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
    "--session": "session file override",
    "--session-id": "session identity override",
    "--fork": "session fork override",
    "--session-dir": "session directory override",
    "--tools": "tool selection override",
    "-t": "tool selection override",
    "--exclude-tools": "tool selection override",
    "-xt": "tool selection override",
    "--extension": "extension resource override",
    "-e": "extension resource override",
    "--skill": "skill resource override",
    "--prompt-template": "prompt resource override",
    "--theme": "theme resource override",
}


class PiSetupError(Exception):
    """A safe, user-facing lifecycle failure."""


class JsonArgumentParser(argparse.ArgumentParser):
    """argparse variant that honors --json for parse-time errors."""

    current_argv: list[str] = []

    def parse_args(
        self, args: list[str] | None = None, namespace: argparse.Namespace | None = None
    ) -> argparse.Namespace:
        JsonArgumentParser.current_argv = list(sys.argv[1:] if args is None else args)
        return super().parse_args(args, namespace)

    def error(self, message: str) -> NoReturn:
        if "--json" in JsonArgumentParser.current_argv:
            sys.stdout.write(canonical_json({"error": message}).decode("utf-8"))
            raise SystemExit(2)
        super().error(message)


def fail(message: str) -> NoReturn:
    raise PiSetupError(message)


def lifecycle_hook(label: str) -> None:
    _ = label


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


def normalize_machine(machine: str) -> str:
    normalized = machine.lower()
    if normalized in {"x86_64", "amd64"}:
        return "x64"
    if normalized in {"arm64", "aarch64"}:
        return "arm64"
    return normalized


def parse_libc_version(version: str) -> tuple[int, ...]:
    if not re.fullmatch(r"\d+(?:\.\d+)*", version):
        fail(f"unsupported glibc version: {version!r}")
    return tuple(int(part) for part in version.split("."))


def detect_supported_host() -> dict[str, Any]:
    arch = normalize_machine(platform.machine())
    if arch not in {"x64", "arm64"}:
        fail(f"unsupported architecture: {platform.machine()!r}")
    if sys.platform == "darwin":
        return {
            "host_id": f"macos-{arch}",
            "os": "macos",
            "arch": arch,
            "distro_id": None,
            "glibc": None,
        }
    if sys.platform.startswith("linux"):
        try:
            os_release = platform.freedesktop_os_release()
        except OSError as exc:
            fail(f"cannot detect Linux distribution: {exc}")
        distro_id = str(os_release.get("ID", "")).lower()
        id_like = {
            item.lower()
            for item in str(os_release.get("ID_LIKE", "")).replace(",", " ").split()
            if item
        }
        if distro_id != "ubuntu" and "ubuntu" not in id_like:
            fail(f"unsupported Linux distribution: {distro_id or 'unknown'}")
        libc_name, libc_version = platform.libc_ver()
        if libc_name != "glibc" or not libc_version:
            fail("Ubuntu hosts must use glibc")
        parse_libc_version(libc_version)
        return {
            "host_id": f"ubuntu-glibc-{arch}",
            "os": "ubuntu",
            "arch": arch,
            "distro_id": distro_id,
            "glibc": libc_version,
        }
    fail(f"unsupported operating system: {sys.platform}")


def require_supported_host() -> dict[str, Any]:
    return detect_supported_host()


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


def assert_no_sensitive_environment(
    env: dict[str, str], label: str, *, allowed_exact: set[str] | None = None
) -> None:
    allowed = allowed_exact or set()
    leaked = sorted(
        name for name in env if name not in allowed and is_sensitive_environment_name(name)
    )
    if leaked:
        fail(f"{label} contains sensitive environment variables: {', '.join(leaked)}")


def child_base_environment() -> dict[str, str]:
    return {
        name: value
        for name, value in os.environ.items()
        if (name in CHILD_ENV_ALLOWLIST and not is_sensitive_environment_name(name))
        or name in PROVIDER_ENV_ALLOWLIST
    }


def stat_optional(path: Path, label: str) -> os.stat_result | None:
    try:
        info = path.lstat()
    except FileNotFoundError:
        return None
    except OSError as exc:
        fail(f"cannot inspect {label}: {exc}")
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


def file_sha256(path: Path, *, label: str, max_bytes: int = SOFTWARE_FILE_MAX_BYTES) -> str:
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
            fail(f"software tree exceeds the {SOFTWARE_TREE_MAX_BYTES}-byte limit")
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
    if stat_optional(path, label) is None:
        return None
    return load_json_object(path, label)


def validate_setup_id(setup_id: str) -> None:
    if not SETUP_ID_PATTERN.fullmatch(setup_id):
        fail(f"invalid setup id: {setup_id!r}")


def validate_profile_id(profile_id: str) -> None:
    if not PROFILE_ID_PATTERN.fullmatch(profile_id):
        fail(f"invalid profile id: {profile_id!r}")


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
            "native_surfaces",
        },
        f"setup {setup_id} metadata",
    )
    if metadata["schema_version"] != 2:
        fail(f"setup {setup_id} metadata has unsupported schema")
    if metadata["id"] != setup_id:
        fail(f"setup {setup_id} metadata identity mismatch")
    if metadata["managed_files"] != managed_file_relatives(include_stamp=False):
        fail(f"setup {setup_id} managed file declaration is invalid")
    if metadata["builder_projection"] != "default-on":
        fail(f"setup {setup_id} must enable the builder projection")
    if validate_string_array(metadata["native_surfaces"], f"setup {setup_id} native_surfaces") != [
        "settings.skills",
        "settings.packages",
        "package.pi.skills",
        "agent.AGENTS.md",
    ]:
        fail(f"setup {setup_id} native surface declaration is invalid")

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


def load_profile(profile_id: str) -> dict[str, Any]:
    validate_profile_id(profile_id)
    profile_root = PROFILES_ROOT / profile_id
    if not profile_root.is_dir() or profile_root.is_symlink():
        fail(f"unknown profile: {profile_id}")
    metadata = load_json_object(profile_root / "profile.json", f"profile {profile_id} metadata")
    require_exact_keys(
        metadata,
        {
            "schema_version",
            "id",
            "description",
            "default",
            "settings",
            "launch_args",
            "tool_boundary",
            "os_security_boundary",
        },
        f"profile {profile_id} metadata",
    )
    if metadata["schema_version"] != 1:
        fail(f"profile {profile_id} metadata has unsupported schema")
    if metadata["id"] != profile_id:
        fail(f"profile {profile_id} metadata identity mismatch")
    if not isinstance(metadata["default"], bool):
        fail(f"profile {profile_id} default must be boolean")
    settings = metadata["settings"]
    if not isinstance(settings, dict):
        fail(f"profile {profile_id} settings must be an object")
    allowed_settings = {"defaultProjectTrust", "sessionDir"}
    unknown = sorted(set(settings) - allowed_settings)
    if unknown:
        fail(f"profile {profile_id} has unsupported managed settings: {', '.join(unknown)}")
    if "defaultProjectTrust" in settings and settings["defaultProjectTrust"] not in {
        "always",
        "ask",
        "never",
    }:
        fail(f"profile {profile_id} defaultProjectTrust is invalid")
    if "sessionDir" in settings and (
        not isinstance(settings["sessionDir"], str) or settings["sessionDir"].startswith("/")
    ):
        fail(f"profile {profile_id} sessionDir must be a relative string")
    validate_string_array(metadata["launch_args"], f"profile {profile_id} launch_args")
    if not isinstance(metadata["tool_boundary"], str):
        fail(f"profile {profile_id} tool_boundary must be a string")
    if metadata["os_security_boundary"] is not False:
        fail(f"profile {profile_id} must not claim an OS security boundary")
    return metadata


def list_profiles() -> list[dict[str, Any]]:
    if not PROFILES_ROOT.is_dir() or PROFILES_ROOT.is_symlink():
        fail("profile catalog is missing or unsafe")
    entries: list[dict[str, Any]] = []
    for candidate in sorted(PROFILES_ROOT.iterdir(), key=lambda path: path.name):
        if not candidate.is_dir() or candidate.is_symlink():
            fail(f"profile entry must be a real directory: {candidate.name}")
        metadata = load_profile(candidate.name)
        entries.append(
            {
                "id": metadata["id"],
                "description": metadata["description"],
                "default": metadata["default"],
                "launch_args": metadata["launch_args"],
                "tool_boundary": metadata["tool_boundary"],
            }
        )
    if not entries:
        fail("profile catalog is empty")
    default_profiles = [entry["id"] for entry in entries if entry["default"]]
    if default_profiles != [DEFAULT_PROFILE_ID]:
        fail("profile catalog must declare exactly the full-auto default")
    return entries


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
                "native_surfaces": metadata["native_surfaces"],
            }
        )
    if not entries:
        fail("setup catalog is empty")
    return entries


def lexical_target(raw_target: str | None) -> Path:
    if not raw_target:
        fail("--target is required")
    expanded = Path(raw_target).expanduser()
    if not expanded.is_absolute():
        fail("--target must be an absolute path")
    return expanded


def canonical_target_under_lock(target: Path) -> Path:
    try:
        raw_info = target.lstat()
    except FileNotFoundError:
        raw_info = None
    if raw_info is not None and stat.S_ISLNK(raw_info.st_mode):
        fail("--target must not be a symlink")
    if raw_info is not None and not stat.S_ISDIR(raw_info.st_mode):
        fail("--target must be a directory")
    return target.resolve(strict=False)


@dataclass(frozen=True)
class ExternalLock:
    descriptor: int
    path: Path
    exclusive: bool


def write_complete_fd(descriptor: int, content: bytes, label: str) -> None:
    view = memoryview(content)
    total = 0
    while total < len(view):
        written = os.write(descriptor, view[total:])
        if written <= 0:
            fail(f"cannot write complete {label}")
        total += written


def open_directory_for_sync(path: Path, label: str) -> int:
    flags = os.O_RDONLY
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        fail(f"cannot open {label} for sync: {exc}")
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISDIR(info.st_mode):
            fail(f"{label} must be a directory")
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def fsync_directory(path: Path, label: str) -> None:
    descriptor = open_directory_for_sync(path, label)
    try:
        os.fsync(descriptor)
    except OSError as exc:
        fail(f"cannot sync {label}: {exc}")
    finally:
        os.close(descriptor)


def fsync_file_descriptor(descriptor: int, label: str) -> None:
    try:
        os.fsync(descriptor)
    except OSError as exc:
        fail(f"cannot sync {label}: {exc}")


def bootstrap_system_temp_root() -> Path:
    if sys.platform == "darwin":
        return Path("/private/tmp")
    return Path("/tmp")


def product_lock_root_path() -> Path:
    uid = os.geteuid() if hasattr(os, "geteuid") else os.getuid()
    return bootstrap_system_temp_root() / f"{LOCK_NAMESPACE_NAME}-{uid}"


def require_product_lock_root(*, create: bool) -> Path | None:
    system_root = bootstrap_system_temp_root()
    system_info = require_directory(system_root, "system temp root")
    if not stat.S_IMODE(system_info.st_mode) & stat.S_ISVTX:
        fail("system temp root must be sticky")
    root = product_lock_root_path()
    info = stat_optional(root, "product lock root")
    if info is None:
        if not create:
            return None
        try:
            root.mkdir(mode=OWNER_DIRECTORY_MODE)
            lifecycle_hook("lock.product.root.mkdir")
            os.chmod(root, OWNER_DIRECTORY_MODE)
            fsync_directory(system_root, "system temp root")
        except BaseException:
            with contextlib.suppress(OSError):
                root.rmdir()
                fsync_directory(system_root, "system temp root")
            raise
        info = require_directory(root, "product lock root")
    if not stat.S_ISDIR(info.st_mode):
        fail("product lock root must be a directory")
    require_current_user_owner(info, "product lock root")
    if stat.S_IMODE(info.st_mode) != OWNER_DIRECTORY_MODE:
        fail("product lock root must be private")
    return root


def product_anchor_path(root: Path) -> Path:
    return root / LOCK_PRODUCT_ANCHOR_NAME


def target_anchor_digest(canonical_target: Path) -> str:
    return sha256_bytes(f"{PRODUCT_NAME}\0{canonical_target}".encode("utf-8"))


def target_anchor_path(root: Path, canonical_target: Path) -> Path:
    return root / f"{target_anchor_digest(canonical_target)}{LOCK_TARGET_SUFFIX}"


def validate_no_orphan_target_anchors(root: Path) -> None:
    try:
        entries = list(root.iterdir())
    except OSError as exc:
        fail(f"cannot inspect product lock root: {exc}")
    for entry in entries:
        if entry.name.endswith(LOCK_TARGET_SUFFIX):
            fail("target anchor exists without product coordination anchor")


def anchor_binding(kind: str, canonical_target: Path | None = None) -> dict[str, Any]:
    binding: dict[str, Any] = {
        "schema_version": 1,
        "product_name": PRODUCT_NAME,
        "build_version": VERSION,
        "kind": kind,
        "namespace": LOCK_NAMESPACE_NAME,
    }
    if kind == "product":
        return binding
    if kind == "target" and canonical_target is not None:
        binding["canonical_target"] = str(canonical_target)
        binding["target_digest"] = target_anchor_digest(canonical_target)
        return binding
    fail("invalid external lock binding request")


def read_fd_bounded(descriptor: int, label: str, *, max_bytes: int) -> bytes:
    os.lseek(descriptor, 0, os.SEEK_SET)
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = os.read(descriptor, 65536)
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            fail(f"{label} is too large")
        chunks.append(chunk)
    return b"".join(chunks)


def validate_anchor_descriptor(
    path: Path,
    descriptor: int,
    expected_binding: dict[str, Any],
    *,
    allow_publication_alias: bool,
) -> os.stat_result:
    opened = os.fstat(descriptor)
    if not stat.S_ISREG(opened.st_mode):
        fail("external lock anchor must be a regular file")
    require_current_user_owner(opened, "external lock anchor")
    if stat.S_IMODE(opened.st_mode) != OWNER_FILE_MODE:
        fail("external lock anchor must have mode 0600")
    if opened.st_nlink != 1 and not (allow_publication_alias and opened.st_nlink == 2):
        fail("external lock anchor has unsafe link count")
    try:
        final = path.lstat()
    except FileNotFoundError:
        fail("external lock anchor is missing")
    if stat.S_ISLNK(final.st_mode) or not stat.S_ISREG(final.st_mode):
        fail("external lock anchor must be a regular file")
    require_current_user_owner(final, "external lock anchor")
    if stat.S_IMODE(final.st_mode) != OWNER_FILE_MODE:
        fail("external lock anchor must have mode 0600")
    if final.st_size > LOCK_BINDING_MAX_BYTES:
        fail("external lock anchor binding is too large")
    if identity_of(opened) != identity_of(final):
        fail("external lock anchor changed while opening")
    if final.st_nlink != opened.st_nlink:
        fail("external lock anchor link count changed while opening")
    content = read_fd_bounded(descriptor, "external lock binding", max_bytes=LOCK_BINDING_MAX_BYTES)
    if not content:
        fail("external lock binding is empty")
    binding = parse_json_object(content, "external lock binding")
    if binding != expected_binding:
        fail("external lock binding mismatch")
    return opened


def publication_aliases(parent: Path, final: Path, final_info: os.stat_result) -> list[Path]:
    aliases: list[Path] = []
    try:
        entries = list(parent.iterdir())
    except OSError as exc:
        fail(f"cannot inspect external lock parent: {exc}")
    pattern = re.compile(re.escape(LOCK_TEMP_PREFIX) + r"[0-9]+\.[0-9a-f]+\.tmp\Z")
    for entry in entries:
        if entry.name == final.name:
            continue
        if not pattern.fullmatch(entry.name):
            continue
        try:
            info = entry.lstat()
        except FileNotFoundError:
            continue
        if identity_of(info) == identity_of(final_info):
            aliases.append(entry)
        else:
            fail("external lock publication alias state is ambiguous")
    return aliases


def recover_anchor_publication_alias(path: Path, descriptor: int, expected: dict[str, Any]) -> None:
    opened = validate_anchor_descriptor(path, descriptor, expected, allow_publication_alias=True)
    if opened.st_nlink == 1:
        return
    aliases = publication_aliases(path.parent, path, opened)
    if len(aliases) != 1:
        fail("external lock publication alias state is ambiguous")
    try:
        aliases[0].unlink()
        lifecycle_hook(f"lock.{expected['kind']}.alias.unlink")
        fsync_directory(path.parent, "external lock parent")
    except OSError as exc:
        fail(f"cannot recover external lock publication alias: {exc}")
    validate_anchor_descriptor(path, descriptor, expected, allow_publication_alias=False)


def open_anchor_no_create(
    path: Path,
    expected: dict[str, Any],
    *,
    exclusive: bool,
    recover_alias: bool,
) -> ExternalLock:
    flags = os.O_RDWR
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except FileNotFoundError:
        raise
    except OSError as exc:
        fail(f"cannot open external lock anchor: {exc}")
    locked = False
    try:
        operation = fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH
        fcntl.flock(descriptor, operation)
        locked = True
        if recover_alias:
            recover_anchor_publication_alias(path, descriptor, expected)
        else:
            validate_anchor_descriptor(path, descriptor, expected, allow_publication_alias=False)
        return ExternalLock(descriptor=descriptor, path=path, exclusive=exclusive)
    except OSError as exc:
        fail(f"cannot lock external anchor: {exc}")
    except BaseException:
        if locked:
            with contextlib.suppress(OSError):
                fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)
        raise


def close_external_lock(lock: ExternalLock | None) -> None:
    if lock is None:
        return
    with contextlib.suppress(OSError):
        fcntl.flock(lock.descriptor, fcntl.LOCK_UN)
    with contextlib.suppress(OSError):
        os.close(lock.descriptor)


def publish_anchor_no_replace(parent: Path, final: Path, binding: dict[str, Any]) -> None:
    content = canonical_json(binding)
    if len(content) > LOCK_BINDING_MAX_BYTES:
        fail("external lock binding is too large")
    temp = parent / f"{LOCK_TEMP_PREFIX}{os.getpid()}.{time.monotonic_ns():x}.tmp"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    descriptor = os.open(temp, flags, OWNER_FILE_MODE)
    final_visible = False
    try:
        os.fchmod(descriptor, OWNER_FILE_MODE)
        lifecycle_hook(f"lock.{binding['kind']}.temp.chmod")
        write_complete_fd(descriptor, content, "external lock binding")
        lifecycle_hook(f"lock.{binding['kind']}.temp.write")
        os.fsync(descriptor)
        lifecycle_hook(f"lock.{binding['kind']}.temp.fsync")
        os.close(descriptor)
        descriptor = -1
        try:
            os.link(temp, final)
            final_visible = True
            lifecycle_hook(f"lock.{binding['kind']}.final.visible")
        except FileExistsError:
            return
        fsync_directory(parent, "external lock parent")
        lifecycle_hook(f"lock.{binding['kind']}.parent.fsync")
    finally:
        if descriptor >= 0:
            with contextlib.suppress(OSError):
                os.close(descriptor)
        with contextlib.suppress(FileNotFoundError):
            temp.unlink()
            lifecycle_hook(f"lock.{binding['kind']}.alias.cleanup")
            fsync_directory(parent, "external lock parent")
        if not final_visible:
            with contextlib.suppress(FileNotFoundError):
                temp.unlink()


def ensure_anchor(
    path: Path,
    expected: dict[str, Any],
    *,
    exclusive: bool,
    create: bool,
    recover_alias: bool,
) -> ExternalLock | None:
    try:
        return open_anchor_no_create(
            path, expected, exclusive=exclusive, recover_alias=recover_alias
        )
    except FileNotFoundError:
        if not create:
            return None
    publish_anchor_no_replace(path.parent, path, expected)
    return open_anchor_no_create(path, expected, exclusive=exclusive, recover_alias=recover_alias)


def acquire_product_coordination(
    *, exclusive: bool, create: bool, recover_alias: bool
) -> tuple[Path | None, ExternalLock | None]:
    root = require_product_lock_root(create=create)
    if root is None:
        return None, None
    lock = ensure_anchor(
        product_anchor_path(root),
        anchor_binding("product"),
        exclusive=exclusive,
        create=create,
        recover_alias=recover_alias,
    )
    return root, lock


@contextlib.contextmanager
def product_coordination(
    *, exclusive: bool, create: bool, recover_alias: bool
) -> Iterator[tuple[Path | None, ExternalLock | None]]:
    root, lock = acquire_product_coordination(
        exclusive=exclusive,
        create=create,
        recover_alias=recover_alias,
    )
    try:
        yield root, lock
    finally:
        close_external_lock(lock)


@contextlib.contextmanager
def external_target_coordination(target: Path, *, mutation: bool) -> Iterator[tuple[Path, bool]]:
    if mutation:
        root, product_lock = acquire_product_coordination(
            exclusive=True, create=True, recover_alias=True
        )
        target_lock_obj: ExternalLock | None = None
        try:
            canonical = canonical_target_under_lock(target)
            if root is None:
                fail("product lock root disappeared during mutation")
            target_lock_obj = ensure_anchor(
                target_anchor_path(root, canonical),
                anchor_binding("target", canonical),
                exclusive=True,
                create=True,
                recover_alias=True,
            )
            if target_lock_obj is None:
                fail("target lock anchor was not created")
            lifecycle_hook("lock.target.handoff")
        finally:
            close_external_lock(product_lock)
        try:
            yield canonical, True
        finally:
            close_external_lock(target_lock_obj)
        return

    root = require_product_lock_root(create=False)
    if root is None or not product_anchor_path(root).exists():
        if root is not None:
            validate_no_orphan_target_anchors(root)
        canonical = canonical_target_under_lock(target)
        yield canonical, False
        root_after = require_product_lock_root(create=False)
        if root_after is not None:
            if product_anchor_path(root_after).exists():
                fail("concurrent mutation published product coordination during read")
            validate_no_orphan_target_anchors(root_after)
        return
    product_root, product_lock = acquire_product_coordination(
        exclusive=False, create=False, recover_alias=False
    )
    target_lock_obj: ExternalLock | None = None
    hold_product_during_read = True
    try:
        canonical = canonical_target_under_lock(target)
        if product_root is None:
            fail("product lock root disappeared during read")
        target_anchor = target_anchor_path(product_root, canonical)
        target_lock_obj = ensure_anchor(
            target_anchor,
            anchor_binding("target", canonical),
            exclusive=False,
            create=False,
            recover_alias=False,
        )
        if target_lock_obj is not None:
            hold_product_during_read = False
            close_external_lock(product_lock)
            product_lock = None
    except BaseException:
        close_external_lock(target_lock_obj)
        close_external_lock(product_lock)
        raise
    try:
        yield canonical, target_lock_obj is not None
    finally:
        close_external_lock(target_lock_obj)
        if hold_product_during_read:
            close_external_lock(product_lock)


def backup_pool(target: Path) -> Path:
    return target.parent / f".{target.name}.nddev-pi-backups"


@contextlib.contextmanager
def target_lock(target: Path, *, mutation: bool = True) -> Iterator[Path]:
    with external_target_coordination(target, mutation=mutation) as (canonical, _):
        yield canonical


def read_only_target(target: Path, callback: Any) -> Any:
    with target_lock(target, mutation=False) as canonical:
        return callback(canonical)


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


def durable_replace_private_file(
    path: Path,
    content: bytes,
    *,
    mode: int,
    label: str,
) -> None:
    parent = path.parent
    temporary = parent / f".{path.name}.tmp-{os.getpid()}-{time.monotonic_ns()}"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    descriptor = os.open(temporary, flags, mode)
    descriptor_open = True
    try:
        os.fchmod(descriptor, mode)
        lifecycle_hook(f"write.{label}.temp.chmod")
        write_complete_fd(descriptor, content, label)
        lifecycle_hook(f"write.{label}.temp.write")
        fsync_file_descriptor(descriptor, label)
        lifecycle_hook(f"write.{label}.temp.fsync")
        os.close(descriptor)
        descriptor_open = False
        os.replace(temporary, path)
        lifecycle_hook(f"write.{label}.final.replace")
        fsync_directory(parent, f"{label} parent")
        lifecycle_hook(f"write.{label}.parent.fsync")
    except BaseException:
        if descriptor_open:
            with contextlib.suppress(OSError):
                os.close(descriptor)
        removed = False
        with contextlib.suppress(FileNotFoundError):
            temporary.unlink()
            removed = True
        if removed:
            with contextlib.suppress(PiSetupError):
                fsync_directory(parent, f"{label} parent")
        raise


def safe_write_file(path: Path, content: bytes, *, label: str | None = None) -> None:
    parent = path.parent
    ensure_directory(parent)
    info = stat_optional(path, path.as_posix())
    if info is not None:
        if not stat.S_ISREG(info.st_mode):
            fail(f"{path} must be a regular file")
        require_current_user_owner(info, path.as_posix())
        require_bounded_size(info, path.as_posix(), MANAGED_PAYLOAD_MAX_BYTES)
    durable_replace_private_file(
        path,
        content,
        mode=OWNER_FILE_MODE,
        label=label or "managed-file",
    )


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


def unlink_regular_for_transaction(path: Path, label: str) -> None:
    info = path.lstat()
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        fail(f"{label} must be a regular file")
    require_current_user_owner(info, label)
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


def directory_metadata(path: Path, label: str) -> dict[str, Any] | None:
    info = stat_optional(path, label)
    if info is None:
        return None
    if not stat.S_ISDIR(info.st_mode):
        fail(f"{label} must be a directory")
    return {
        "mode": stat.S_IMODE(info.st_mode),
        "uid": info.st_uid,
        "dev": info.st_dev,
        "ino": info.st_ino,
        "atime_ns": info.st_atime_ns,
        "mtime_ns": info.st_mtime_ns,
    }


def restore_directory_metadata(path: Path, expected: dict[str, Any] | None, label: str) -> None:
    if expected is None:
        with contextlib.suppress(OSError):
            path.rmdir()
        return
    info = require_directory(path, label)
    if info.st_dev != expected["dev"] or info.st_ino != expected["ino"]:
        fail(f"{label} identity changed")
    if stat.S_IMODE(info.st_mode) != expected["mode"]:
        os.chmod(path, expected["mode"])
    os.utime(path, ns=(expected["atime_ns"], expected["mtime_ns"]), follow_symlinks=False)


def managed_parent_relatives(relatives: list[str]) -> list[Path]:
    parents: set[Path] = {Path(".")}
    for relative in relatives:
        parent = Path(relative).parent
        while parent != Path("."):
            parents.add(parent)
            parent = parent.parent
    return sorted(parents, key=lambda item: len(item.parts), reverse=True)


@dataclass
class ManagedHeldFile:
    relative: str
    existed: bool
    hold_path: Path | None
    content: bytes | None
    mode: int | None
    size: int | None
    sha256: str | None


class ManagedFileTransaction:
    """Preserve managed file objects until the whole setup mutation commits."""

    def __init__(self, target: Path, relatives: list[str]) -> None:
        self.target = target
        self.relatives = relatives
        self.tx_dir = target / f".nddev-pi-managed-txn.{os.getpid()}.{time.monotonic_ns():x}"
        self.held: dict[str, ManagedHeldFile] = {}
        self.parents = {
            relative.as_posix(): directory_metadata(target / relative, f"managed parent {relative}")
            for relative in managed_parent_relatives(relatives)
        }
        ensure_directory(self.tx_dir)
        fsync_directory(target, "target")
        for relative in relatives:
            path = target / relative
            info = stat_optional(path, f"managed file {relative}")
            if info is None:
                self.held[relative] = ManagedHeldFile(
                    relative=relative,
                    existed=False,
                    hold_path=None,
                    content=None,
                    mode=None,
                    size=None,
                    sha256=None,
                )
                continue
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                fail(f"managed file {relative} must be a regular non-hard-linked file")
            content = read_regular_file(path, f"managed file {relative}")
            hold = self.tx_dir / f"{sha256_bytes(relative.encode('utf-8'))}.held"
            os.link(path, hold)
            fsync_directory(self.tx_dir, "managed transaction")
            self.held[relative] = ManagedHeldFile(
                relative=relative,
                existed=True,
                hold_path=hold,
                content=content,
                mode=stat.S_IMODE(info.st_mode),
                size=len(content),
                sha256=sha256_bytes(content),
            )

    def files_for_backup(self) -> dict[str, str | None]:
        files: dict[str, str | None] = {}
        for relative in self.relatives:
            held = self.held[relative]
            files[relative] = (
                None if held.content is None else base64.b64encode(held.content).decode("ascii")
            )
        return files

    def rollback(self) -> None:
        errors: list[str] = []
        for relative in reversed(self.relatives):
            held = self.held[relative]
            path = self.target / relative
            try:
                if held.existed:
                    if held.hold_path is None:
                        fail(f"managed file {relative} has no held object")
                    with contextlib.suppress(FileNotFoundError):
                        delete_file(path)
                    ensure_directory(path.parent)
                    os.link(held.hold_path, path)
                    if held.mode is not None:
                        os.chmod(path, held.mode)
                    fsync_directory(path.parent, f"managed file {relative} parent")
                else:
                    with contextlib.suppress(FileNotFoundError):
                        delete_file(path)
                        fsync_directory(path.parent, f"managed file {relative} parent")
            except BaseException as exc:
                errors.append(f"{relative}: {exc}")
        for relative in managed_parent_relatives(self.relatives):
            label = relative.as_posix()
            try:
                restore_directory_metadata(self.target / relative, self.parents[label], label)
            except BaseException as exc:
                errors.append(f"{label}: {exc}")
        try:
            self.cleanup()
        except BaseException as exc:
            errors.append(f"transaction cleanup: {exc}")
        if errors:
            fail("managed rollback failed: " + "; ".join(errors))

    def cleanup(self) -> None:
        for hold in self.tx_dir.iterdir():
            info = hold.lstat()
            if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
                fail("managed held object must be a regular file")
            hold.unlink()
        fsync_directory(self.tx_dir, "managed transaction")
        self.tx_dir.rmdir()
        fsync_directory(self.target, "target")


def remove_builder_projection_dirs(target: Path) -> None:
    for relative in (
        BUILDER_SKILL_DIR / "SKILL.md",
        BUILDER_PACKAGE_DIR / "skills" / "nddev-builder" / "SKILL.md",
        BUILDER_PACKAGE_DIR / "package.json",
    ):
        delete_file(target / relative)
    for relative in (
        BUILDER_PACKAGE_DIR / "skills" / "nddev-builder",
        BUILDER_PACKAGE_DIR / "skills",
        BUILDER_PACKAGE_DIR,
        BUILDER_SKILL_DIR,
        BUILDER_SKILL_DIR.parent,
    ):
        path = target / relative
        try:
            info = path.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
            fail(f"{path} must be a managed directory")
        path.rmdir()


def cleanup_parent(target: Path) -> Path:
    return target / CLEANUP_DIR_NAME


def cleanup_tombstones(target: Path) -> Path:
    return cleanup_parent(target) / CLEANUP_TOMBSTONES_NAME


def cleanup_intent_path(target: Path) -> Path:
    return cleanup_parent(target) / CLEANUP_INTENT_NAME


def cleanup_journal_path(target: Path) -> Path:
    return cleanup_parent(target) / CLEANUP_JOURNAL_NAME


def bounded_relative(value: str, label: str) -> Path:
    if not isinstance(value, str) or not value or value.startswith("/"):
        fail(f"{label} must be a relative path")
    relative = Path(value)
    if any(part in {"", ".", ".."} for part in relative.parts):
        fail(f"{label} must be bounded and normalized")
    if len(relative.as_posix()) > 160:
        fail(f"{label} is too long")
    return relative


def anchor_path(target: Path, anchor: str) -> Path:
    if anchor == "target":
        return target
    if anchor == "backup_pool":
        return backup_pool(target)
    if anchor == "cleanup":
        return cleanup_parent(target)
    fail(f"unknown cleanup anchor: {anchor!r}")


def anchored_path(target: Path, anchor: str, relative: str) -> Path:
    return anchor_path(target, anchor) / bounded_relative(relative, "cleanup relative path")


def snapshot_cleanup_tree(path: Path, label: str) -> dict[str, Any]:
    root_info = require_directory(path, label)
    require_current_user_owner(root_info, label)
    entries: list[dict[str, Any]] = []
    total = 0
    paths = [path, *sorted(path.rglob("*"), key=lambda item: item.relative_to(path).as_posix())]
    if len(paths) > CLEANUP_MAX_OBJECTS:
        fail(f"{label} exceeds cleanup object bound")
    for item in paths:
        relative = "." if item == path else item.relative_to(path).as_posix()
        info = item.lstat()
        mode = stat.S_IMODE(info.st_mode)
        record: dict[str, Any] = {
            "relative": relative,
            "uid": info.st_uid,
            "mode": mode,
            "nlink": info.st_nlink,
            "dev": info.st_dev,
            "ino": info.st_ino,
            "size": info.st_size,
            "mtime_ns": info.st_mtime_ns,
        }
        if stat.S_ISLNK(info.st_mode):
            fail(f"{label} contains a symlink: {relative}")
        if stat.S_ISDIR(info.st_mode):
            record["kind"] = "directory"
        elif stat.S_ISREG(info.st_mode):
            if info.st_nlink != 1:
                fail(f"{label} contains a hard-linked file: {relative}")
            content = read_regular_file(
                item, f"{label}:{relative}", max_bytes=SOFTWARE_FILE_MAX_BYTES
            )
            total += len(content)
            if total > CLEANUP_MAX_BYTES:
                fail(f"{label} exceeds cleanup byte bound")
            record["kind"] = "file"
            record["sha256"] = sha256_bytes(content)
        else:
            fail(f"{label} contains an unsupported object: {relative}")
        entries.append(record)
    return {"objects": entries, "object_count": len(entries), "byte_count": total}


def validate_cleanup_tree(path: Path, expected: dict[str, Any], label: str) -> None:
    if snapshot_cleanup_tree(path, label) != expected:
        fail(f"{label} identity mismatch")


def cleanup_snapshot_records(expected: dict[str, Any], label: str) -> dict[str, dict[str, Any]]:
    objects = expected.get("objects")
    if not isinstance(objects, list):
        fail(f"{label} snapshot objects are invalid")
    records: dict[str, dict[str, Any]] = {}
    for item in objects:
        if not isinstance(item, dict) or "relative" not in item:
            fail(f"{label} snapshot object is invalid")
        relative = item["relative"]
        if not isinstance(relative, str):
            fail(f"{label} snapshot relative path is invalid")
        if relative != ".":
            bounded_relative(relative, f"{label} snapshot relative path")
        if relative in records:
            fail(f"{label} snapshot contains duplicate object")
        records[relative] = item
    if expected.get("object_count") != len(records):
        fail(f"{label} snapshot object count mismatch")
    if "." not in records:
        fail(f"{label} snapshot root is missing")
    return records


def validate_cleanup_object(path: Path, expected: dict[str, Any], label: str) -> None:
    info = path.lstat()
    if stat.S_ISLNK(info.st_mode):
        fail(f"{label} must not be a symlink")
    if expected["kind"] == "directory":
        if not stat.S_ISDIR(info.st_mode):
            fail(f"{label} kind mismatch")
        checks = {
            "uid": info.st_uid,
            "mode": stat.S_IMODE(info.st_mode),
            "dev": info.st_dev,
            "ino": info.st_ino,
        }
        for key, value in checks.items():
            if expected.get(key) != value:
                fail(f"{label} identity mismatch")
        return
    if expected["kind"] == "file":
        if not stat.S_ISREG(info.st_mode):
            fail(f"{label} kind mismatch")
        content = read_regular_file(path, label, max_bytes=SOFTWARE_FILE_MAX_BYTES)
        checks = {
            "uid": info.st_uid,
            "mode": stat.S_IMODE(info.st_mode),
            "nlink": info.st_nlink,
            "dev": info.st_dev,
            "ino": info.st_ino,
            "size": info.st_size,
            "mtime_ns": info.st_mtime_ns,
            "sha256": sha256_bytes(content),
        }
        for key, value in checks.items():
            if expected.get(key) != value:
                fail(f"{label} identity mismatch")
        return
    fail(f"{label} kind is unsupported")


def validate_cleanup_tree_partial(path: Path, expected: dict[str, Any], label: str) -> None:
    records = cleanup_snapshot_records(expected, label)
    if not path.exists():
        return
    actual_paths = [
        path,
        *sorted(path.rglob("*"), key=lambda item: item.relative_to(path).as_posix()),
    ]
    for item in actual_paths:
        relative = "." if item == path else item.relative_to(path).as_posix()
        if relative not in records:
            fail(f"{label} contains an unknown object: {relative}")
        validate_cleanup_object(item, records[relative], f"{label}:{relative}")


def cleanup_parent_identity(path: Path, label: str) -> dict[str, Any]:
    info = require_directory(path, label)
    require_current_user_owner(info, label)
    return {
        "kind": "directory",
        "uid": info.st_uid,
        "mode": stat.S_IMODE(info.st_mode),
        "dev": info.st_dev,
        "ino": info.st_ino,
    }


def validate_cleanup_parent_identity(path: Path, expected: dict[str, Any], label: str) -> None:
    if cleanup_parent_identity(path, label) != expected:
        fail(f"{label} parent identity mismatch")


def validate_cleanup_source_policy(entry: dict[str, Any], label: str) -> None:
    purpose = entry["purpose"]
    source_anchor = entry["source_anchor"]
    source_relative = entry["source_relative"]
    if purpose == "software-current":
        if (
            source_anchor != "target"
            or source_relative != f"{SOFTWARE_DIR_NAME}/{SOFTWARE_CURRENT_NAME}"
        ):
            fail(f"{label} software cleanup source mismatch")
        if not entry["tombstone_relative"].startswith(f"{CLEANUP_TOMBSTONES_NAME}/{purpose}."):
            fail(f"{label} software cleanup tombstone mismatch")
        return
    fail(f"{label} cleanup purpose is unsupported")


def cleanup_entry(
    target: Path,
    *,
    purpose: str,
    source_anchor: str,
    source_relative: str,
    tombstone_relative: str,
    snapshot: dict[str, Any],
) -> dict[str, Any]:
    return {
        "purpose": purpose,
        "source_anchor": source_anchor,
        "source_relative": source_relative,
        "source_kind": "directory",
        "source_parent": cleanup_parent_identity(
            anchored_path(target, source_anchor, source_relative).parent,
            "cleanup source parent",
        ),
        "tombstone_anchor": "cleanup",
        "tombstone_relative": tombstone_relative,
        "tombstone_parent": cleanup_parent_identity(
            (cleanup_parent(target) / tombstone_relative).parent,
            "cleanup tombstone parent",
        ),
        "snapshot": snapshot,
    }


def cleanup_document(target: Path, *, state: str, entries: list[dict[str, Any]]) -> dict[str, Any]:
    if len(entries) > CLEANUP_MAX_ENTRIES:
        fail("cleanup journal has too many entries")
    return {
        "schema_version": 1,
        "product_name": PRODUCT_NAME,
        "build_version": VERSION,
        "canonical_target": str(target),
        "state": state,
        "cleanup_anchor": CLEANUP_DIR_NAME,
        "entries": entries,
    }


def validate_cleanup_document(
    target: Path, document: dict[str, Any], label: str
) -> list[dict[str, Any]]:
    require_exact_keys(
        document,
        {
            "schema_version",
            "product_name",
            "build_version",
            "canonical_target",
            "state",
            "cleanup_anchor",
            "entries",
        },
        label,
    )
    if document["schema_version"] != 1 or document["product_name"] != PRODUCT_NAME:
        fail(f"{label} identity mismatch")
    if document["canonical_target"] != str(target):
        fail(f"{label} target mismatch")
    if document["cleanup_anchor"] != CLEANUP_DIR_NAME:
        fail(f"{label} cleanup anchor mismatch")
    if document["state"] not in {"intent", "pending"}:
        fail(f"{label} state is invalid")
    entries = document["entries"]
    if not isinstance(entries, list) or len(entries) > CLEANUP_MAX_ENTRIES:
        fail(f"{label} entries are invalid")
    seen_tombstones: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict):
            fail(f"{label} entry must be an object")
        require_exact_keys(
            entry,
            {
                "purpose",
                "source_anchor",
                "source_relative",
                "source_kind",
                "source_parent",
                "tombstone_anchor",
                "tombstone_relative",
                "tombstone_parent",
                "snapshot",
            },
            f"{label} entry",
        )
        if entry["source_kind"] != "directory":
            fail(f"{label} entry source kind is unsupported")
        if entry["source_anchor"] not in {"target", "backup_pool"}:
            fail(f"{label} entry source anchor is invalid")
        if entry["tombstone_anchor"] != "cleanup":
            fail(f"{label} entry tombstone anchor is invalid")
        bounded_relative(entry["source_relative"], f"{label} source_relative")
        bounded_relative(entry["tombstone_relative"], f"{label} tombstone_relative")
        for key in ("source_parent", "tombstone_parent"):
            parent = entry[key]
            if not isinstance(parent, dict) or set(parent) != {
                "kind",
                "uid",
                "mode",
                "dev",
                "ino",
            }:
                fail(f"{label} {key} schema is invalid")
            if parent["kind"] != "directory":
                fail(f"{label} {key} kind is invalid")
        validate_cleanup_source_policy(entry, label)
        if entry["tombstone_relative"] in seen_tombstones:
            fail(f"{label} duplicate tombstone")
        seen_tombstones.add(entry["tombstone_relative"])
        snapshot = entry["snapshot"]
        if not isinstance(snapshot, dict) or set(snapshot) != {
            "objects",
            "object_count",
            "byte_count",
        }:
            fail(f"{label} entry snapshot schema is invalid")
        if snapshot["object_count"] != len(snapshot["objects"]):
            fail(f"{label} entry object count mismatch")
    return entries


def publish_json_no_replace(path: Path, payload: dict[str, Any], label: str) -> None:
    content = canonical_json(payload)
    if len(content) > METADATA_MAX_BYTES:
        fail(f"{label} is too large")
    ensure_directory(path.parent)
    temp = path.parent / f"{LOCK_TEMP_PREFIX}{os.getpid()}.{time.monotonic_ns():x}.tmp"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    fd = os.open(temp, flags, OWNER_FILE_MODE)
    final_visible = False
    try:
        os.fchmod(fd, OWNER_FILE_MODE)
        write_complete_fd(fd, content, label)
        lifecycle_hook(f"cleanup.{label}.temp.write")
        os.fsync(fd)
        lifecycle_hook(f"cleanup.{label}.temp.fsync")
        os.close(fd)
        fd = -1
        try:
            os.link(temp, path)
            final_visible = True
            lifecycle_hook(f"cleanup.{label}.final.visible")
        except FileExistsError:
            fail(f"{label} already exists")
        fsync_directory(path.parent, f"{label} parent")
        lifecycle_hook(f"cleanup.{label}.parent.fsync")
    finally:
        if fd >= 0:
            with contextlib.suppress(OSError):
                os.close(fd)
        with contextlib.suppress(FileNotFoundError):
            temp.unlink()
            fsync_directory(path.parent, f"{label} parent")
        if not final_visible:
            with contextlib.suppress(FileNotFoundError):
                temp.unlink()


def cleanup_publication_aliases(path: Path, final_info: os.stat_result) -> list[Path]:
    pattern = re.compile(re.escape(LOCK_TEMP_PREFIX) + r"[0-9]+\.[0-9a-f]+\.tmp\Z")
    aliases: list[Path] = []
    try:
        entries = list(path.parent.iterdir())
    except OSError as exc:
        fail(f"cannot inspect cleanup publication parent: {exc}")
    for entry in entries:
        if entry.name == path.name:
            continue
        if not pattern.fullmatch(entry.name):
            continue
        try:
            info = entry.lstat()
        except FileNotFoundError:
            continue
        if identity_of(info) == identity_of(final_info):
            aliases.append(entry)
        else:
            fail("cleanup publication alias state is ambiguous")
    return aliases


def validate_cleanup_document_file(
    path: Path,
    target: Path,
    label: str,
    *,
    allow_publication_alias: bool,
) -> tuple[dict[str, Any], os.stat_result]:
    try:
        info = path.lstat()
    except FileNotFoundError:
        fail(f"{label} is missing")
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        fail(f"{label} must be a regular non-symlink file")
    require_bounded_size(info, label, METADATA_MAX_BYTES)
    require_current_user_owner(info, label)
    if stat.S_IMODE(info.st_mode) != OWNER_FILE_MODE:
        fail(f"{label} must have mode 0600")
    if info.st_nlink != 1 and not (allow_publication_alias and info.st_nlink == 2):
        fail(f"{label} has unsafe link count")
    flags = os.O_RDONLY
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        fail(f"cannot open {label}: {exc}")
    try:
        opened = os.fstat(descriptor)
        if identity_of(opened) != identity_of(info):
            fail(f"{label} changed while it was being opened")
        if not stat.S_ISREG(opened.st_mode):
            fail(f"{label} changed to an unsafe file")
        if opened.st_nlink != info.st_nlink:
            fail(f"{label} link count changed while opening")
        content = read_fd_bounded(descriptor, label, max_bytes=METADATA_MAX_BYTES)
    finally:
        os.close(descriptor)
    document = parse_json_object(content, label)
    validate_cleanup_document(target, document, label)
    return document, info


def recover_cleanup_publication_alias(path: Path, target: Path, label: str) -> None:
    if stat_optional(path, label) is None:
        return
    document, info = validate_cleanup_document_file(
        path, target, label, allow_publication_alias=True
    )
    if info.st_nlink == 1:
        return
    aliases = cleanup_publication_aliases(path, info)
    if len(aliases) != 1:
        fail(f"{label} publication alias state is ambiguous")
    alias = aliases[0]
    alias_document, alias_info = validate_cleanup_document_file(
        alias, target, f"{label} publication alias", allow_publication_alias=True
    )
    if identity_of(alias_info) != identity_of(info) or alias_document != document:
        fail(f"{label} publication alias mismatch")
    try:
        alias.unlink()
        lifecycle_hook(f"cleanup.{label}.alias.unlink")
        fsync_directory(path.parent, f"{label} parent")
        lifecycle_hook(f"cleanup.{label}.alias.parent.fsync")
    except OSError as exc:
        fail(f"cannot recover {label} publication alias: {exc}")
    validate_cleanup_document_file(path, target, label, allow_publication_alias=False)


def read_cleanup_document(path: Path, target: Path, label: str) -> dict[str, Any] | None:
    info = stat_optional(path, label)
    if info is None:
        return None
    document, _ = validate_cleanup_document_file(path, target, label, allow_publication_alias=False)
    return document


def validate_cleanup_pending_readonly(target: Path, entries: list[dict[str, Any]]) -> None:
    cleanup_root = cleanup_parent(target)
    root_info = require_directory(cleanup_root, "cleanup parent")
    require_current_user_owner(root_info, "cleanup parent")
    if stat.S_IMODE(root_info.st_mode) != OWNER_DIRECTORY_MODE:
        fail("cleanup parent must be private")
    expected_root_names = {CLEANUP_JOURNAL_NAME, CLEANUP_TOMBSTONES_NAME}
    if cleanup_intent_path(target).exists():
        expected_root_names.add(CLEANUP_INTENT_NAME)
    try:
        root_entries = list(cleanup_root.iterdir())
    except OSError as exc:
        fail(f"cannot inspect cleanup parent: {exc}")
    for entry in root_entries:
        if entry.name not in expected_root_names:
            fail(f"cleanup parent contains an unknown object: {entry.name}")
    expected_tombstones = {
        Path(entry["tombstone_relative"]).parts[1]
        for entry in entries
        if len(Path(entry["tombstone_relative"]).parts) == 2
    }
    tombstones = cleanup_tombstones(target)
    tombstone_info = stat_optional(tombstones, "cleanup tombstones")
    if tombstone_info is not None:
        if not stat.S_ISDIR(tombstone_info.st_mode):
            fail("cleanup tombstones must be a directory")
        require_current_user_owner(tombstone_info, "cleanup tombstones")
        if stat.S_IMODE(tombstone_info.st_mode) != OWNER_DIRECTORY_MODE:
            fail("cleanup tombstones must be private")
        for child in tombstones.iterdir():
            if child.name not in expected_tombstones:
                fail(f"cleanup tombstones contain an unknown object: {child.name}")
    for entry in entries:
        tombstone = anchored_path(target, entry["tombstone_anchor"], entry["tombstone_relative"])
        if stat_optional(tombstone, "cleanup tombstone") is None:
            continue
        validate_cleanup_parent_identity(
            tombstone.parent, entry["tombstone_parent"], "cleanup tombstone"
        )
        validate_cleanup_tree_partial(tombstone, entry["snapshot"], entry["purpose"])


def cleanup_state(target: Path) -> dict[str, Any]:
    pending = read_cleanup_document(cleanup_journal_path(target), target, "cleanup journal")
    intent = read_cleanup_document(cleanup_intent_path(target), target, "cleanup intent")
    if pending is not None:
        entries = validate_cleanup_document(target, pending, "cleanup journal")
        validate_cleanup_pending_readonly(target, entries)
        return {"cleanup_pending": True, "cleanup_entries": len(entries)}
    if intent is not None:
        fail("cleanup intent is incomplete and requires exclusive recovery")
    return {"cleanup_pending": False, "cleanup_entries": 0}


def move_directory_for_cleanup(
    target: Path,
    *,
    purpose: str,
    source_anchor: str,
    source_relative: str,
) -> dict[str, Any]:
    cleanup_root = cleanup_parent(target)
    tombstones = cleanup_tombstones(target)
    ensure_directory(cleanup_root)
    ensure_directory(tombstones)
    source = anchored_path(target, source_anchor, source_relative)
    snapshot = snapshot_cleanup_tree(source, f"cleanup source {purpose}")
    tombstone_name = f"{purpose}.{os.getpid()}.{time.monotonic_ns():x}"
    tombstone_relative = f"{CLEANUP_TOMBSTONES_NAME}/{tombstone_name}"
    tombstone = cleanup_root / tombstone_relative
    entry = cleanup_entry(
        target,
        purpose=purpose,
        source_anchor=source_anchor,
        source_relative=source_relative,
        tombstone_relative=tombstone_relative,
        snapshot=snapshot,
    )
    publish_json_no_replace(
        cleanup_intent_path(target),
        cleanup_document(target, state="intent", entries=[entry]),
        "intent",
    )
    validate_cleanup_parent_identity(source.parent, entry["source_parent"], "cleanup source")
    validate_cleanup_parent_identity(
        tombstone.parent, entry["tombstone_parent"], "cleanup tombstone"
    )
    source.rename(tombstone)
    lifecycle_hook(f"cleanup.{purpose}.source.move.after")
    fsync_directory(source.parent, "cleanup source parent")
    lifecycle_hook(f"cleanup.{purpose}.source.parent.fsync")
    fsync_directory(tombstone.parent, "cleanup tombstone parent")
    lifecycle_hook(f"cleanup.{purpose}.tombstone.parent.fsync")
    validate_cleanup_tree(tombstone, snapshot, f"cleanup tombstone {purpose}")
    return entry


def recover_cleanup_intent(target: Path) -> None:
    intent = read_cleanup_document(cleanup_intent_path(target), target, "cleanup intent")
    if intent is None:
        return
    entries = validate_cleanup_document(target, intent, "cleanup intent")
    if len(entries) != 1:
        fail("cleanup intent recovery supports exactly one entry")
    entry = entries[0]
    source = anchored_path(target, entry["source_anchor"], entry["source_relative"])
    tombstone = anchored_path(target, entry["tombstone_anchor"], entry["tombstone_relative"])
    source_info = stat_optional(source, "cleanup intent source")
    tombstone_info = stat_optional(tombstone, "cleanup intent tombstone")
    if source_info is not None and tombstone_info is None:
        validate_cleanup_parent_identity(source.parent, entry["source_parent"], "cleanup source")
        delete_file(cleanup_intent_path(target))
        fsync_directory(cleanup_parent(target), "cleanup parent")
        return
    if source_info is not None and tombstone_info is not None:
        validate_cleanup_parent_identity(source.parent, entry["source_parent"], "cleanup source")
        validate_cleanup_parent_identity(
            tombstone.parent, entry["tombstone_parent"], "cleanup tombstone"
        )
        validate_cleanup_tree(tombstone, entry["snapshot"], "cleanup intent tombstone")
        publish_cleanup_pending(target, entries)
        return
    if source_info is None and tombstone_info is not None:
        validate_cleanup_parent_identity(source.parent, entry["source_parent"], "cleanup source")
        validate_cleanup_parent_identity(
            tombstone.parent, entry["tombstone_parent"], "cleanup tombstone"
        )
        validate_cleanup_tree(tombstone, entry["snapshot"], "cleanup intent tombstone")
        ensure_directory(source.parent)
        tombstone.rename(source)
        fsync_directory(source.parent, "cleanup source parent")
        fsync_directory(tombstone.parent, "cleanup tombstone parent")
        validate_cleanup_tree(source, entry["snapshot"], "cleanup restored source")
        delete_file(cleanup_intent_path(target))
        fsync_directory(cleanup_parent(target), "cleanup parent")
        return
    fail("cleanup intent is incoherent")


def delete_cleanup_tree(path: Path, expected: dict[str, Any], label: str) -> None:
    validate_cleanup_tree_partial(path, expected, label)
    records = cleanup_snapshot_records(expected, label)
    for relative, record in sorted(
        records.items(), key=lambda item: len(Path(item[0]).parts), reverse=True
    ):
        item = path if relative == "." else path / relative
        info = stat_optional(item, f"{label}:{relative}")
        if info is None:
            continue
        validate_cleanup_object(item, record, f"{label}:{relative}")
        if stat.S_ISDIR(info.st_mode):
            lifecycle_hook(f"cleanup.{label}.object.rmdir.before")
            item.rmdir()
            lifecycle_hook(f"cleanup.{label}.object.rmdir.after")
        else:
            lifecycle_hook(f"cleanup.{label}.object.unlink.before")
            delete_file(item)
            lifecycle_hook(f"cleanup.{label}.object.unlink.after")
        lifecycle_hook(f"cleanup.{label}.object.parent.fsync.before")
        fsync_directory(item.parent, f"{label} parent")
        lifecycle_hook(f"cleanup.{label}.object.parent.fsync.after")


def drain_cleanup(target: Path) -> bool:
    recover_cleanup_publication_alias(cleanup_journal_path(target), target, "cleanup journal")
    recover_cleanup_publication_alias(cleanup_intent_path(target), target, "cleanup intent")
    pending = read_cleanup_document(cleanup_journal_path(target), target, "cleanup journal")
    if pending is None:
        recover_cleanup_intent(target)
        return False
    entries = validate_cleanup_document(target, pending, "cleanup journal")
    try:
        for entry in entries:
            tombstone = anchored_path(
                target, entry["tombstone_anchor"], entry["tombstone_relative"]
            )
            info = stat_optional(tombstone, "cleanup tombstone")
            if info is None:
                continue
            validate_cleanup_parent_identity(
                tombstone.parent, entry["tombstone_parent"], "cleanup tombstone"
            )
            delete_cleanup_tree(tombstone, entry["snapshot"], entry["purpose"])
        if cleanup_intent_path(target).exists():
            lifecycle_hook("cleanup.intent.retire.unlink.before")
            delete_file(cleanup_intent_path(target))
            lifecycle_hook("cleanup.intent.retire.unlink.after")
            fsync_directory(cleanup_parent(target), "cleanup parent")
            lifecycle_hook("cleanup.intent.retire.parent.fsync")
        with contextlib.suppress(OSError):
            cleanup_tombstones(target).rmdir()
            lifecycle_hook("cleanup.tombstones.rmdir")
            fsync_directory(cleanup_parent(target), "cleanup parent")
        lifecycle_hook("cleanup.drain.target.fsync.before")
        fsync_directory(target, "target")
    except BaseException:
        return True
    try:
        lifecycle_hook("cleanup.journal.retire.unlink.before")
        delete_file(cleanup_journal_path(target))
        lifecycle_hook("cleanup.journal.retire.unlink.after")
        fsync_directory(cleanup_parent(target), "cleanup parent")
        lifecycle_hook("cleanup.journal.retire.parent.fsync")
    except BaseException:
        return stat_optional(cleanup_journal_path(target), "cleanup journal") is not None
    with contextlib.suppress(OSError):
        cleanup_parent(target).rmdir()
    return False


def publish_cleanup_pending(target: Path, entries: list[dict[str, Any]]) -> bool:
    try:
        publish_json_no_replace(
            cleanup_journal_path(target),
            cleanup_document(target, state="pending", entries=entries),
            "journal",
        )
    except BaseException:
        if stat_optional(cleanup_journal_path(target), "cleanup journal") is None:
            raise
        recover_cleanup_publication_alias(cleanup_journal_path(target), target, "cleanup journal")
        read_cleanup_document(cleanup_journal_path(target), target, "cleanup journal")
        return True
    pending = drain_cleanup(target)
    return pending


def builder_skill_path(target: Path) -> str:
    return str((target / BUILDER_SKILL_DIR).resolve())


def builder_package_entry(target: Path) -> str:
    return str((target / BUILDER_PACKAGE_DIR).resolve())


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
    existing: dict[str, Any] | None,
    setup_settings: dict[str, Any],
    profile: dict[str, Any],
    target: Path,
) -> dict[str, Any]:
    result: dict[str, Any] = {}
    if existing is not None:
        for key, value in existing.items():
            if key not in MANAGED_SETTING_KEYS and key not in {"skills", "packages"}:
                result[key] = value

    for key in MANAGED_SETTING_KEYS:
        if key in setup_settings:
            result[key] = setup_settings[key]
    profile_settings = profile["settings"]
    if not isinstance(profile_settings, dict):
        fail("profile settings must be an object")
    for key, value in profile_settings.items():
        result[key] = value
    result["nddev"] = {
        "schema_version": 2,
        "setup_id": setup_settings["nddev"]["setup_id"],
        "profile_id": profile["id"],
        "builder_projection": "skills+package",
        "launch_args": profile["launch_args"],
        "tool_boundary": profile["tool_boundary"],
        "os_security_boundary": False,
    }

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
    setup_id: str, profile_id: str, target: Path, existing: dict[str, Any] | None
) -> tuple[dict[str, Any], dict[str, bytes]]:
    metadata, settings = load_setup(setup_id)
    profile = load_profile(profile_id)
    merged_settings = merge_settings(existing, settings, profile, target)
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
        AGENTS_REL,
        BUILDER_SKILL_DIR / "SKILL.md",
        BUILDER_PACKAGE_DIR / "package.json",
        BUILDER_PACKAGE_DIR / "skills" / "nddev-builder" / "SKILL.md",
    ):
        content = read_existing_file(target / relative)
        if content is not None:
            digests[relative.as_posix()] = sha256_bytes(content)
    return digests


def make_stamp(
    target: Path, setup_id: str, profile_id: str, final_settings: dict[str, Any]
) -> dict[str, Any]:
    managed_files = compute_managed_digests(target, final_settings)
    return {
        "schema_version": 1,
        "product_name": PRODUCT_NAME,
        "build_version": VERSION,
        "setup_id": setup_id,
        "profile_id": profile_id,
        "canonical_target": str(target),
        "managed_files": managed_files,
        "builder_projection": "skills+package",
    }


def status_for_target(target: Path) -> dict[str, Any]:
    if not target.exists():
        return {
            "state": "missing",
            "setup_id": None,
            "profile_id": None,
            "drift": [],
            "target": str(target),
            "cleanup_pending": False,
        }
    cleanup = cleanup_state(target)
    stamp = load_stamp(target)
    if stamp is None:
        return {
            "state": "unmanaged",
            "setup_id": None,
            "profile_id": None,
            "drift": [],
            "target": str(target),
            "cleanup_pending": cleanup["cleanup_pending"],
        }
    require_exact_keys(stamp, STAMP_KEYS, STAMP_NAME)
    setup_id = stamp.get("setup_id")
    if not isinstance(setup_id, str):
        fail("stamp setup_id must be a string")
    profile_id = stamp.get("profile_id")
    if not isinstance(profile_id, str):
        fail("stamp profile_id must be a string")
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
        "profile_id": profile_id,
        "drift": sorted(set(drift)),
        "target": str(target),
        "builder_projection": stamp.get("builder_projection"),
        "cleanup_pending": cleanup["cleanup_pending"],
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


def backup_file_metadata(files: dict[str, str | None]) -> dict[str, dict[str, Any]]:
    metadata: dict[str, dict[str, Any]] = {}
    expected_relatives = managed_file_relatives()
    if set(files) != set(expected_relatives):
        fail("backup file set must match managed files exactly")
    for relative in expected_relatives:
        encoded = files[relative]
        if encoded is None:
            metadata[relative] = {"present": False, "size": None, "sha256": None}
            continue
        try:
            content = base64.b64decode(encoded.encode("ascii"), validate=True)
        except (ValueError, binascii.Error) as exc:
            fail(f"backup file {relative} is not valid base64: {exc}")
        metadata[relative] = {
            "present": True,
            "size": len(content),
            "sha256": sha256_bytes(content),
        }
    return metadata


def validate_backup_files(files: Any, metadata: Any) -> dict[str, str | None]:
    if not isinstance(files, dict) or not isinstance(metadata, dict):
        fail("backup files and metadata must be objects")
    expected_relatives = managed_file_relatives()
    if set(files) != set(expected_relatives) or set(metadata) != set(expected_relatives):
        fail("backup file path set must match managed files exactly")
    validated: dict[str, str | None] = {}
    for relative in expected_relatives:
        encoded = files[relative]
        record = metadata[relative]
        if not isinstance(record, dict) or set(record) != {"present", "size", "sha256"}:
            fail(f"backup metadata for {relative} has invalid schema")
        if encoded is None:
            if record != {"present": False, "size": None, "sha256": None}:
                fail(f"backup metadata for absent {relative} is invalid")
            validated[relative] = None
            continue
        if not isinstance(encoded, str):
            fail(f"backup payload for {relative} must be a base64 string or null")
        try:
            content = base64.b64decode(encoded.encode("ascii"), validate=True)
        except (ValueError, binascii.Error) as exc:
            fail(f"backup payload for {relative} is invalid base64: {exc}")
        if (
            record.get("present") is not True
            or record.get("size") != len(content)
            or record.get("sha256") != sha256_bytes(content)
        ):
            fail(f"backup metadata for {relative} does not match payload")
        validated[relative] = encoded
    return validated


def restore_snapshot(target: Path, snapshot: dict[str, str | None]) -> None:
    if set(snapshot) != set(managed_file_relatives()):
        fail("restore snapshot path set must match managed files exactly")
    for relative in managed_file_relatives():
        encoded = snapshot[relative]
        path = target / relative
        if encoded is None:
            with contextlib.suppress(FileNotFoundError):
                delete_file(path)
        else:
            safe_write_file(path, base64.b64decode(encoded.encode("ascii")))


def managed_file_relatives(*, include_stamp: bool = True) -> list[str]:
    relatives = [
        SETTINGS_NAME,
        AGENTS_NAME,
        (BUILDER_SKILL_DIR / "SKILL.md").as_posix(),
        (BUILDER_PACKAGE_DIR / "package.json").as_posix(),
        (BUILDER_PACKAGE_DIR / "skills" / "nddev-builder" / "SKILL.md").as_posix(),
    ]
    if include_stamp:
        return [*relatives, STAMP_NAME]
    return relatives


def next_backup_slot(pool: Path) -> int:
    ensure_directory(pool)
    existing = {int(path.name) for path in pool.iterdir() if path.is_dir() and path.name.isdigit()}
    for slot in range(10):
        if slot not in existing:
            return slot
    fail("backup pool is full; remove or archive a slot before creating another backup")


def remove_backup_slot(target: Path, slot: int) -> None:
    pool = backup_pool(target)
    slot_dir = pool / str(slot)
    with contextlib.suppress(FileNotFoundError):
        delete_tree(slot_dir)
        fsync_directory(pool, "backup pool")
    with contextlib.suppress(OSError):
        pool.rmdir()
        fsync_directory(target.parent, "target parent")


def create_backup_from_files(
    target: Path,
    source_setup_id: str | None,
    source_profile_id: str | None,
    files: dict[str, str | None],
) -> int:
    pool = backup_pool(target)
    pool_existed = stat_optional(pool, "backup pool") is not None
    slot = next_backup_slot(pool)
    temp_dir = pool / f".{slot}.tmp-{os.getpid()}-{time.monotonic_ns():x}"
    final_dir = pool / str(slot)
    temp_dir.mkdir(mode=OWNER_DIRECTORY_MODE)
    envelope = {
        "schema_version": 2,
        "product_name": PRODUCT_NAME,
        "build_version": VERSION,
        "slot": slot,
        "canonical_target": str(target),
        "source_setup_id": source_setup_id,
        "source_profile_id": source_profile_id,
        "managed_files": [relative for relative, encoded in files.items() if encoded is not None],
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "files": files,
        "file_metadata": backup_file_metadata(files),
    }
    try:
        safe_write_file(temp_dir / BACKUP_NAME, canonical_json(envelope), label="backup")
        if final_dir.exists():
            fail("backup slot appeared during publication")
        temp_dir.rename(final_dir)
        fsync_directory(pool, "backup pool")
        validate_backup_slot_directory(final_dir, slot)
        return slot
    except BaseException:
        with contextlib.suppress(FileNotFoundError):
            delete_tree(temp_dir)
            fsync_directory(pool, "backup pool")
        if not pool_existed:
            with contextlib.suppress(OSError):
                pool.rmdir()
                fsync_directory(target.parent, "target parent")
        raise


def create_backup(target: Path, source_setup_id: str | None, source_profile_id: str | None) -> int:
    return create_backup_from_files(
        target,
        source_setup_id,
        source_profile_id,
        snapshot_files(target, managed_file_relatives()),
    )


def validate_backup_slot_directory(slot_dir: Path, slot: int) -> None:
    info = require_directory(slot_dir, f"backup slot {slot}")
    require_current_user_owner(info, f"backup slot {slot}")
    if stat.S_IMODE(info.st_mode) != OWNER_DIRECTORY_MODE:
        fail(f"backup slot {slot} must be private")
    entries = sorted(path.name for path in slot_dir.iterdir())
    if entries != [BACKUP_NAME]:
        fail(f"backup slot {slot} contains unexpected entries")


def load_backup(target: Path, slot: int) -> dict[str, Any]:
    if slot < 0 or slot > 9:
        fail("--backup must be in the 0..9 range")
    slot_dir = backup_pool(target) / str(slot)
    validate_backup_slot_directory(slot_dir, slot)
    envelope = load_json_object(slot_dir / BACKUP_NAME, f"backup slot {slot}")
    require_exact_keys(envelope, BACKUP_KEYS, f"backup slot {slot}")
    if envelope.get("schema_version") != 2:
        fail("backup has unsupported schema")
    if envelope.get("product_name") != PRODUCT_NAME or envelope.get("build_version") != VERSION:
        fail("backup product identity mismatch")
    if envelope.get("canonical_target") != str(target):
        fail("backup does not belong to this target")
    if envelope.get("slot") != slot:
        fail("backup slot envelope mismatch")
    files = validate_backup_files(envelope.get("files"), envelope.get("file_metadata"))
    managed_files = envelope.get("managed_files")
    if managed_files != [
        relative for relative in managed_file_relatives() if files[relative] is not None
    ]:
        fail("backup managed_files do not match file payloads")
    return envelope


def desired_setup_files(
    target: Path, setup_id: str, profile_id: str, files: dict[str, bytes]
) -> dict[str, bytes]:
    final_settings = parse_json_object(files[SETTINGS_NAME], SETTINGS_NAME)
    managed_digests: dict[str, str] = {
        SETTINGS_NAME: sha256_bytes(canonical_json(managed_settings_view(final_settings, target)))
    }
    for relative, content in files.items():
        if relative != SETTINGS_NAME:
            managed_digests[relative] = sha256_bytes(content)
    stamp = {
        "schema_version": 1,
        "product_name": PRODUCT_NAME,
        "build_version": VERSION,
        "setup_id": setup_id,
        "profile_id": profile_id,
        "canonical_target": str(target),
        "managed_files": managed_digests,
        "builder_projection": "skills+package",
    }
    return {**files, STAMP_NAME: canonical_json(stamp)}


def apply_managed_files_transaction(
    target: Path,
    desired: dict[str, bytes | None],
    *,
    backup_source: tuple[str | None, str | None] | None,
) -> tuple[list[str], int | None]:
    relatives = managed_file_relatives()
    if set(desired) != set(relatives):
        fail("desired managed file set must match managed files exactly")
    current = snapshot_files(target, relatives)
    changed: list[str] = []
    encoded_desired: dict[str, str | None] = {}
    for relative in relatives:
        content = desired[relative]
        encoded = None if content is None else base64.b64encode(content).decode("ascii")
        encoded_desired[relative] = encoded
        if current[relative] != encoded:
            changed.append(relative)
    if not changed and backup_source is None:
        return [], None
    transaction = ManagedFileTransaction(target, changed)
    backup_slot: int | None = None
    try:
        for relative in relatives:
            if relative not in changed:
                continue
            content = desired[relative]
            path = target / relative
            if content is None:
                if transaction.held[relative].existed:
                    unlink_regular_for_transaction(path, f"managed file {relative}")
                continue
            safe_write_file(path, content)
        if backup_source is not None:
            backup_slot = create_backup_from_files(
                target, backup_source[0], backup_source[1], current
            )
        for relative in relatives:
            encoded = encoded_desired[relative]
            actual = snapshot_files(target, [relative])[relative]
            if actual != encoded:
                fail(f"managed postcondition failed for {relative}")
        transaction.cleanup()
        return changed, backup_slot
    except BaseException:
        if backup_slot is not None:
            remove_backup_slot(target, backup_slot)
        transaction.rollback()
        raise


def write_rendered_files(
    target: Path,
    setup_id: str,
    profile_id: str,
    files: dict[str, bytes],
    *,
    backup_source: tuple[str | None, str | None] | None = None,
) -> tuple[list[str], int | None]:
    desired = desired_setup_files(target, setup_id, profile_id, files)
    return apply_managed_files_transaction(target, desired, backup_source=backup_source)


def command_plan(target: Path, setup_id: str, profile_id: str) -> dict[str, Any]:
    with target_lock(target, mutation=False) as target:
        status = status_for_target(target)
    operation = "install"
    backup_required = False
    if status["state"] == "managed":
        if status["drift"]:
            operation = "blocked"
        elif status.get("cleanup_pending"):
            operation = "cleanup"
        elif status["setup_id"] == setup_id and status["profile_id"] == profile_id:
            operation = "update"
        else:
            operation = "switch"
            backup_required = True
    return {
        "operation": operation,
        "setup_id": setup_id,
        "profile_id": profile_id,
        "target": str(target),
        "mutates": False,
        "backup_required": backup_required,
        "state": status["state"],
        "drift": status["drift"],
        "cleanup_pending": status.get("cleanup_pending", False),
    }


def command_install(target: Path, setup_id: str, profile_id: str) -> dict[str, Any]:
    with target_lock(target) as target:
        target_parent_state = directory_metadata(target.parent, "target parent")
        created_target = ensure_target_directory(target)
        try:
            if not created_target and drain_cleanup(target):
                fail("cleanup is still pending")
            status = status_for_target(target)
            if status["state"] == "managed" and status["drift"]:
                fail(f"target has drift: {', '.join(status['drift'])}")
            backup_source = None
            if status["state"] == "managed" and (
                status["setup_id"] != setup_id or status["profile_id"] != profile_id
            ):
                backup_source = (status["setup_id"], status["profile_id"])
            existing = read_current_settings(target)
            _, files = render_setup(setup_id, profile_id, target, existing)
            changed, backup_slot = write_rendered_files(
                target,
                setup_id,
                profile_id,
                files,
                backup_source=backup_source,
            )
        except BaseException:
            if created_target:
                with contextlib.suppress(OSError):
                    target.rmdir()
                restore_directory_metadata(target.parent, target_parent_state, "target parent")
            raise
    return {
        "operation": "install",
        "setup_id": setup_id,
        "profile_id": profile_id,
        "target": str(target),
        "changed": changed,
        "backup_slot": backup_slot,
        "builder_projection": "skills+package",
    }


def command_switch(target: Path, setup_id: str, profile_id: str) -> dict[str, Any]:
    with target_lock(target) as target:
        ensure_target_directory(target)
        if drain_cleanup(target):
            fail("cleanup is still pending")
        status = require_clean_managed(target)
        existing = read_current_settings(target)
        _, files = render_setup(setup_id, profile_id, target, existing)
        changed, backup_slot = write_rendered_files(
            target,
            setup_id,
            profile_id,
            files,
            backup_source=(status["setup_id"], status["profile_id"]),
        )
    return {
        "operation": "switch",
        "setup_id": setup_id,
        "profile_id": profile_id,
        "target": str(target),
        "changed": changed,
        "backup_slot": backup_slot,
        "builder_projection": "skills+package",
    }


def command_restore(target: Path, slot: int) -> dict[str, Any]:
    with target_lock(target) as target:
        ensure_target_directory(target)
        if drain_cleanup(target):
            fail("cleanup is still pending")
        status = require_clean_managed(target)
        envelope = load_backup(target, slot)
        desired = {
            relative: (
                None
                if envelope["files"][relative] is None
                else base64.b64decode(envelope["files"][relative].encode("ascii"))
            )
            for relative in managed_file_relatives()
        }
        apply_managed_files_transaction(
            target,
            desired,
            backup_source=(status["setup_id"], status["profile_id"]),
        )
        restored_setup_id = envelope.get("source_setup_id")
        if not isinstance(restored_setup_id, str):
            fail("backup source setup id is missing")
        restored_profile_id = envelope.get("source_profile_id")
        if not isinstance(restored_profile_id, str):
            fail("backup source profile id is missing")
    return {
        "operation": "restore",
        "setup_id": restored_setup_id,
        "profile_id": restored_profile_id,
        "target": str(target),
        "backup_slot": slot,
        "builder_projection": "skills+package",
    }


def command_remove(target: Path) -> dict[str, Any]:
    with target_lock(target) as target:
        ensure_target_directory(target)
        if drain_cleanup(target):
            fail("cleanup is still pending")
        status = require_clean_managed(target)
        settings = read_current_settings(target)
        desired: dict[str, bytes | None] = {relative: None for relative in managed_file_relatives()}
        if settings is not None:
            stripped = strip_managed_settings(settings, target)
            if stripped:
                desired[SETTINGS_NAME] = canonical_json(stripped)
        apply_managed_files_transaction(
            target,
            desired,
            backup_source=(status["setup_id"], status["profile_id"]),
        )
        for relative in managed_parent_relatives(managed_file_relatives()):
            if relative == Path("."):
                continue
            with contextlib.suppress(OSError):
                (target / relative).rmdir()
    return {
        "operation": "remove",
        "removed_setup_id": status["setup_id"],
        "removed_profile_id": status["profile_id"],
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


def validate_package_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
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


def load_package_manifest(root: Path) -> dict[str, Any]:
    return validate_package_manifest(
        load_json_object(package_manifest_path(root), "Pi package manifest")
    )


def load_extracted_package_manifest(root: Path) -> dict[str, Any]:
    return validate_package_manifest(load_json_object(root / "package.json", "Pi package manifest"))


def is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def private_mode_for_source(info: os.stat_result) -> int:
    return 0o700 if stat.S_IMODE(info.st_mode) & 0o100 else OWNER_FILE_MODE


def private_mode_for_tar_entry(member: tarfile.TarInfo) -> int:
    return 0o700 if member.mode & 0o100 else OWNER_FILE_MODE


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
                fail(f"staged software tree exceeds the {SOFTWARE_TREE_MAX_BYTES}-byte limit")
            copy_file_private(source_file, target_path, relative.as_posix())
            continue
        if not stat.S_ISREG(info.st_mode):
            fail(f"staged software entry must be a regular file: {relative.as_posix()}")
        total += info.st_size
        if total > SOFTWARE_TREE_MAX_BYTES:
            fail(f"staged software tree exceeds the {SOFTWARE_TREE_MAX_BYTES}-byte limit")
        copy_file_private(path, target_path, relative.as_posix())


def materialize_staged_entrypoint(
    stage_workspace: Path,
    stage_current: Path,
    allowed_roots: tuple[Path, ...],
    node_runtime: dict[str, str],
) -> None:
    source_root = stage_workspace / "install" / "bin"
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
    expected_package_binary = (stage_workspace / PI_PACKAGE_BINARY_RELATIVE).resolve(strict=True)
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
    allowed_roots = ((stage_workspace / "install").resolve(strict=False),)
    stage_current.mkdir(mode=OWNER_DIRECTORY_MODE)
    copy_tree_sanitized(
        stage_workspace / "install",
        stage_current / "install",
        allowed_roots,
    )
    materialize_staged_entrypoint(
        stage_workspace,
        stage_current,
        allowed_roots,
        node_runtime,
    )


def safe_npm_env(stage_workspace: Path) -> dict[str, str]:
    home = stage_workspace / "home"
    xdg_config = stage_workspace / "xdg-config"
    cache = stage_workspace / "cache"
    tmp = stage_workspace / "tmp"
    userconfig = stage_workspace / "npmrc"
    for directory in (
        home,
        xdg_config,
        cache,
        tmp,
        stage_workspace / "tarballs",
    ):
        directory.mkdir(mode=OWNER_DIRECTORY_MODE, parents=True, exist_ok=True)
    safe_write_file(
        userconfig,
        b"audit=false\nfund=false\nignore-scripts=true\n",
        label="npm-userconfig",
    )
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": str(home),
        "XDG_CONFIG_HOME": str(xdg_config),
        "TMPDIR": str(tmp),
        "npm_config_cache": str(cache),
        "npm_config_ignore_scripts": "true",
        "npm_config_userconfig": str(userconfig),
    }
    assert_no_sensitive_environment(
        env,
        "npm installer environment",
        allowed_exact={
            "npm_config_cache",
            "npm_config_ignore_scripts",
            "npm_config_userconfig",
        },
    )
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


def npm_pack_argv(stage_workspace: Path) -> list[str]:
    return [
        value.replace("<stage>/tarballs", str(stage_workspace / "tarballs"))
        for value in NPM_PACK_ARGV
    ]


def npm_local_install_argv(stage_workspace: Path, tarball: Path) -> list[str]:
    return [
        value.replace("<stage>/install", str(stage_workspace / "install")).replace(
            "<verified-tarball>", str(tarball)
        )
        for value in NPM_LOCAL_INSTALL_ARGV
    ]


def run_npm_json(command: list[str], env: dict[str, str], label: str) -> Any:
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
            fail("npm command was not found on PATH")
        except subprocess.TimeoutExpired:
            fail(f"{label} timed out")
        if completed.returncode != 0:
            detail = (
                read_process_output(stderr, "stderr") or read_process_output(stdout, "stdout")
            ).strip()
            fail(f"{label} failed with exit code {completed.returncode}: {detail}")
        output = read_process_output(stdout, "stdout").strip()
        try:
            return json.loads(output)
        except json.JSONDecodeError as exc:
            fail(f"{label} returned invalid JSON: {exc}")


def run_npm_command(command: list[str], env: dict[str, str], label: str) -> None:
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
            fail("npm command was not found on PATH")
        except subprocess.TimeoutExpired:
            fail(f"{label} timed out")
        if completed.returncode != 0:
            detail = (
                read_process_output(stderr, "stderr") or read_process_output(stdout, "stdout")
            ).strip()
            fail(f"{label} failed with exit code {completed.returncode}: {detail}")


def verify_registry_dist_metadata(value: Any, label: str) -> None:
    if not isinstance(value, dict):
        fail(f"{label} metadata must be an object")
    if value.get("integrity") != PI_REGISTRY_INTEGRITY:
        fail(f"{label} integrity mismatch")
    if value.get("shasum") != PI_REGISTRY_SHASUM:
        fail(f"{label} shasum mismatch")
    if value.get("tarball") != PI_REGISTRY_TARBALL_URL:
        fail(f"{label} tarball URL mismatch")


def verify_npm_pack_metadata(value: Any) -> None:
    if not isinstance(value, list) or len(value) != 1 or not isinstance(value[0], dict):
        fail("npm pack metadata must describe exactly one archive")
    entry = value[0]
    if entry.get("name") != PI_PACKAGE_NAME:
        fail("npm pack package name mismatch")
    if entry.get("version") != PI_PACKAGE_VERSION:
        fail("npm pack package version mismatch")
    if entry.get("integrity") not in {None, PI_REGISTRY_INTEGRITY}:
        fail("npm pack integrity mismatch")
    if entry.get("shasum") not in {None, PI_REGISTRY_SHASUM}:
        fail("npm pack shasum mismatch")


def verify_tarball_identity(path: Path) -> bytes:
    content = read_regular_file(path, "Pi package tarball", max_bytes=SOFTWARE_TREE_MAX_BYTES)
    integrity = "sha512-" + base64.b64encode(hashlib.sha512(content).digest()).decode("ascii")
    if integrity != PI_REGISTRY_INTEGRITY:
        fail("Pi package tarball integrity mismatch")
    shasum = hashlib.sha1(content).hexdigest()
    if shasum != PI_REGISTRY_SHASUM:
        fail("Pi package tarball shasum mismatch")
    return content


def extract_verified_tarball(content: bytes, destination: Path) -> None:
    destination.mkdir(mode=OWNER_DIRECTORY_MODE)
    total = 0
    count = 0
    with tarfile.open(fileobj=io.BytesIO(content), mode="r:gz") as archive:
        for member in archive.getmembers():
            name = PurePosixPath(member.name)
            if name.is_absolute() or ".." in name.parts or not name.parts:
                fail("Pi package tarball contains an unsafe path")
            if name.parts[0] != "package":
                fail("Pi package tarball root must be package/")
            relative = PurePosixPath(*name.parts[1:])
            if not relative.parts:
                continue
            count += 1
            if count > SOFTWARE_TREE_MAX_PATHS:
                fail("Pi package tarball exceeds the path bound")
            target = destination.joinpath(*relative.parts)
            if member.isdir():
                target.mkdir(mode=OWNER_DIRECTORY_MODE, parents=True, exist_ok=True)
                continue
            if not member.isfile():
                fail("Pi package tarball contains a non-regular entry")
            handle = archive.extractfile(member)
            if handle is None:
                fail("Pi package tarball entry is unreadable")
            data = handle.read(SOFTWARE_FILE_MAX_BYTES + 1)
            if len(data) > SOFTWARE_FILE_MAX_BYTES:
                fail("Pi package tarball entry exceeds the file bound")
            total += len(data)
            if total > SOFTWARE_TREE_MAX_BYTES:
                fail("Pi package tarball exceeds the byte bound")
            target.parent.mkdir(mode=OWNER_DIRECTORY_MODE, parents=True, exist_ok=True)
            durable_replace_private_file(
                target,
                data,
                mode=private_mode_for_tar_entry(member),
                label="tarball-extract",
            )


def run_npm_install(stage_workspace: Path) -> None:
    env = safe_npm_env(stage_workspace)
    dist = run_npm_json(["npm", *NPM_VIEW_ARGV], env, "npm view")
    verify_registry_dist_metadata(dist, "npm view")
    pack_dir = stage_workspace / "tarballs"
    before = {path.name for path in pack_dir.iterdir()}
    pack_metadata = run_npm_json(["npm", *npm_pack_argv(stage_workspace)], env, "npm pack")
    verify_npm_pack_metadata(pack_metadata)
    archives = [
        path
        for path in pack_dir.glob("*.tgz")
        if path.is_file() and not path.is_symlink() and path.name not in before
    ]
    if len(archives) != 1:
        fail("npm pack did not produce exactly one new tarball")
    content = verify_tarball_identity(archives[0])
    extract_root = stage_workspace / "verified-package"
    extract_verified_tarball(content, extract_root)
    load_extracted_package_manifest(extract_root)
    run_npm_command(
        ["npm", *npm_local_install_argv(stage_workspace, archives[0])],
        env,
        "npm verified tarball install",
    )


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
        if output != PI_CLI_VERSION_OUTPUT:
            fail(
                "staged pi version probe output mismatch: "
                f"expected {PI_CLI_VERSION_OUTPUT!r}, got {output!r}"
            )
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


def atomic_write_private(
    path: Path,
    content: bytes,
    mode: int = OWNER_FILE_MODE,
    *,
    label: str | None = None,
) -> None:
    path.parent.mkdir(mode=OWNER_DIRECTORY_MODE, parents=True, exist_ok=True)
    durable_replace_private_file(
        path,
        content,
        mode=mode,
        label=label or "private-file",
    )


def write_target_entrypoint(target: Path, node_runtime: dict[str, str]) -> str:
    destination = software_entrypoint(target)
    ensure_software_parent(destination, target)
    require_safe_partial_file(destination, "Pi entrypoint", max_bytes=SOFTWARE_FILE_MAX_BYTES)
    content = node_wrapper_content(
        node_runtime["path"], package_binary_path(software_current(target))
    )
    atomic_write_private(destination, content, 0o700, label="software-entrypoint")
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
            "tarball": PI_REGISTRY_TARBALL_URL,
            "integrity": PI_REGISTRY_INTEGRITY,
            "shasum": PI_REGISTRY_SHASUM,
        },
        "node_runtime": node_runtime,
        "version_probe": {
            "argv": ["bin/pi", "--version"],
            "package_version": PI_PACKAGE_VERSION,
            "expected_output": PI_CLI_VERSION_OUTPUT,
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
            "tool": "npm",
            "metadata_argv": NPM_VIEW_ARGV,
            "pack_argv": NPM_PACK_ARGV,
            "local_install_argv": NPM_LOCAL_INSTALL_ARGV,
            "argv": NPM_INSTALL_ARGV,
            "trust_reason": None,
            "env": {
                "HOME": "<stage>/home",
                "npm_config_cache": "<stage>/cache",
                "npm_config_ignore_scripts": "true",
                "npm_config_userconfig": "<stage>/npmrc",
                "XDG_CONFIG_HOME": "<stage>/xdg-config",
                "TMPDIR": "<stage>/tmp",
            },
            "byte_verification": {
                "metadata_integrity": PI_REGISTRY_INTEGRITY,
                "metadata_shasum": PI_REGISTRY_SHASUM,
                "tarball_integrity": PI_REGISTRY_INTEGRITY,
                "tarball_shasum": PI_REGISTRY_SHASUM,
                "verified_before_extract": True,
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
        "HOME": "<stage>/home",
        "npm_config_cache": "<stage>/cache",
        "npm_config_ignore_scripts": "true",
        "npm_config_userconfig": "<stage>/npmrc",
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


def software_status_payload(target: Path, *, validate_cleanup: bool = True) -> dict[str, Any]:
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
        "cleanup_pending": False,
    }
    if not target.exists():
        return payload
    if validate_cleanup:
        cleanup = cleanup_state(target)
        payload["cleanup_pending"] = cleanup["cleanup_pending"]
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
            "installed_tree_bytes": stamp.get("installed_tree_bytes") == installed_tree_bytes,
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
            or registry.get("tarball") != PI_REGISTRY_TARBALL_URL
            or registry.get("integrity") != PI_REGISTRY_INTEGRITY
            or registry.get("shasum") != PI_REGISTRY_SHASUM
        ):
            drift.append("registry")
        installer = stamp.get("installer")
        if (
            not isinstance(installer, dict)
            or installer.get("tool") != "npm"
            or installer.get("metadata_argv") != NPM_VIEW_ARGV
            or installer.get("pack_argv") != NPM_PACK_ARGV
            or installer.get("local_install_argv") != NPM_LOCAL_INSTALL_ARGV
            or installer.get("argv") != NPM_INSTALL_ARGV
            or installer.get("env") != expected_installer_env()
            or installer.get("trust_reason") is not None
            or installer.get("byte_verification")
            != {
                "metadata_integrity": PI_REGISTRY_INTEGRITY,
                "metadata_shasum": PI_REGISTRY_SHASUM,
                "tarball_integrity": PI_REGISTRY_INTEGRITY,
                "tarball_shasum": PI_REGISTRY_SHASUM,
                "verified_before_extract": True,
            }
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
            or probe.get("package_version") != PI_PACKAGE_VERSION
            or probe.get("expected_output") != PI_CLI_VERSION_OUTPUT
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


def is_cleanup_state_error(exc: PiSetupError) -> bool:
    message = str(exc)
    return message.startswith("cleanup ") or message.startswith("cannot inspect cleanup ")


def software_precondition_state(target: Path) -> dict[str, Any]:
    validate_pre_network_software_target(target)
    try:
        return software_status_payload(target)
    except PiSetupError as exc:
        if is_cleanup_state_error(exc):
            raise
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
    atomic_write_private(path, data, mode or OWNER_FILE_MODE, label="software-rollback-file")


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
    with target_lock(target) as target:
        target_parent_state = directory_metadata(target.parent, "target parent")
        created_target = stat_optional(target, "target") is None
        try:
            if not created_target and drain_cleanup(target):
                fail("cleanup is still pending")
            status = software_precondition_state(target)
            if status["current"]:
                return {
                    "changed": False,
                    "cleanup_pending": False,
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
            ):
                stage_root = Path(stage_raw)
                node_runtime = resolve_node_runtime(stage_root)
                stage_install = stage_root / "install-output"
                stage_current = stage_root / SOFTWARE_CURRENT_NAME
                run_npm_install(stage_install)
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
                previous_entrypoint, previous_entrypoint_mode = snapshot_software_file(
                    software_entrypoint(target),
                    "Pi entrypoint",
                    SOFTWARE_FILE_MAX_BYTES,
                )
                previous_stamp, previous_stamp_mode = snapshot_software_file(
                    software_stamp_path(target), SOFTWARE_STAMP_NAME, METADATA_MAX_BYTES
                )
                cleanup_entries: list[dict[str, Any]] = []
                new_current_installed = False
                try:
                    current_info = stat_optional(current, "current software tree")
                    if current_info is not None:
                        if not stat.S_ISDIR(current_info.st_mode):
                            fail("current software tree must be a directory")
                        cleanup_entries.append(
                            move_directory_for_cleanup(
                                target,
                                purpose="software-current",
                                source_anchor="target",
                                source_relative=f"{SOFTWARE_DIR_NAME}/{SOFTWARE_CURRENT_NAME}",
                            )
                        )
                    stage_current.rename(current)
                    new_current_installed = True
                    entrypoint_digest = write_target_entrypoint(target, node_runtime)
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
                        software_stamp_path(target),
                        canonical_json(stamp),
                        OWNER_FILE_MODE,
                        label="software-stamp",
                    )
                    verified = software_status_payload(target, validate_cleanup=False)
                    if not verified["current"]:
                        fail(
                            f"installed software failed status verification: {', '.join(verified['drift'])}"
                        )
                except BaseException:
                    if new_current_installed:
                        delete_tree(current)
                    if cleanup_entries:
                        recover_cleanup_intent(target)
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
                cleanup_pending = False
                if cleanup_entries:
                    cleanup_pending = publish_cleanup_pending(target, cleanup_entries)
                return {
                    "changed": True,
                    "cleanup_pending": cleanup_pending,
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
                restore_directory_metadata(target.parent, target_parent_state, "target parent")
            raise


def software_plan(target: Path) -> dict[str, Any]:
    with target_lock(target, mutation=False) as target:
        status = software_precondition_state(target)
    operation = "none"
    if not status["present"]:
        operation = "install"
    elif not status["current"]:
        operation = "repair-or-update"
    if status.get("cleanup_pending"):
        operation = "cleanup"
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
        "cleanup_pending": status.get("cleanup_pending", False),
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
    assert_no_sensitive_environment(
        child_env, "Pi child environment", allowed_exact=PROVIDER_ENV_ALLOWLIST
    )
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
    launch_args = validate_string_array(nddev_settings.get("launch_args"), "managed launch_args")
    child_args = [*launch_args, "--skill", builder_skill_path(target), *user_args]
    child_env = build_child_env(target, stamp["node_runtime"])
    return [str(executable), *child_args], child_env


def command_launch(target: Path, forwarded: list[str]) -> int:
    with target_lock(target) as target:
        if drain_cleanup(target):
            fail("cleanup is still pending")
        command, child_env = prepare_launch_invocation(target, forwarded)
        lifecycle_hook("launch.before_spawn")
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
    parser = JsonArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    list_parser = subparsers.add_parser("list")
    list_parser.add_argument("--json", action="store_true")

    for command in ("status", "plan", "install", "switch", "restore", "remove"):
        command_parser = subparsers.add_parser(command)
        command_parser.add_argument("--target")
        command_parser.add_argument("--json", action="store_true")
        if command in {"plan", "install", "switch"}:
            command_parser.add_argument("--setup")
            command_parser.add_argument("--profile")
        if command == "restore":
            command_parser.add_argument("--backup")

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
        setup_id = DEFAULT_SETUP_ID
    validate_setup_id(setup_id)
    load_setup(setup_id)
    return setup_id


def require_profile_argument(profile_id: str | None) -> str:
    if not profile_id:
        profile_id = DEFAULT_PROFILE_ID
    validate_profile_id(profile_id)
    load_profile(profile_id)
    return profile_id


def require_backup_slot(raw_slot: str | None) -> int:
    if raw_slot is None:
        fail("--backup is required")
    if not re.fullmatch(r"\d+", raw_slot):
        fail("--backup must be a decimal integer in the 0..9 range")
    slot = int(raw_slot)
    if slot < 0 or slot > 9:
        fail("--backup must be in the 0..9 range")
    return slot


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    json_enabled = bool(getattr(args, "json", False))
    try:
        host = require_supported_host()
        if args.command == "list":
            emit({"setups": list_setups(), "profiles": list_profiles(), "host": host}, json_enabled)
            return 0
        if args.command == "status":
            emit(
                read_only_target(lexical_target(args.target), status_for_target),
                json_enabled,
            )
            return 0
        if args.command == "plan":
            emit(
                command_plan(
                    lexical_target(args.target),
                    require_setup_argument(args.setup),
                    require_profile_argument(args.profile),
                ),
                json_enabled,
            )
            return 0
        if args.command == "install":
            emit(
                command_install(
                    lexical_target(args.target),
                    require_setup_argument(args.setup),
                    require_profile_argument(args.profile),
                ),
                json_enabled,
            )
            return 0
        if args.command == "switch":
            emit(
                command_switch(
                    lexical_target(args.target),
                    require_setup_argument(args.setup),
                    require_profile_argument(args.profile),
                ),
                json_enabled,
            )
            return 0
        if args.command == "restore":
            emit(
                command_restore(lexical_target(args.target), require_backup_slot(args.backup)),
                json_enabled,
            )
            return 0
        if args.command == "remove":
            emit(command_remove(lexical_target(args.target)), json_enabled)
            return 0
        if args.command == "launch":
            return command_launch(lexical_target(args.target), args.forwarded)
        if args.command == "software-plan":
            emit(software_plan(lexical_target(args.target)), json_enabled)
            return 0
        if args.command == "software-status":
            emit(
                read_only_target(lexical_target(args.target), software_status_payload),
                json_enabled,
            )
            return 0
        if args.command == "software-install":
            emit(
                install_or_update_software(lexical_target(args.target), update=False), json_enabled
            )
            return 0
        if args.command == "software-update":
            emit(install_or_update_software(lexical_target(args.target), update=True), json_enabled)
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
