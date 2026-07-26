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
import shutil
import stat
import subprocess
import sys
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
    "PATH",
    "LANG",
    "LC_ALL",
    "TERM",
    "COLORTERM",
    "TMPDIR",
    "SYSTEMROOT",
    "FAKE_PI_EXIT",
}


class PiSetupError(Exception):
    """A safe, user-facing lifecycle failure."""


def fail(message: str) -> NoReturn:
    raise PiSetupError(message)


def canonical_json(value: Any) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


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


def software_payload(action: str) -> dict[str, Any]:
    baseline = load_json_object(
        ROOT / "references" / "pi-baseline.json", "references/pi-baseline.json"
    )
    package = baseline["package"]
    install_command = [
        "npm",
        "install",
        "-g",
        "--ignore-scripts",
        f"{package['name']}@{package['version']}",
    ]
    update_command = ["pi", "update", "--self"]
    return {
        "action": action,
        "live_check": False,
        "mutates": False,
        "package": {
            "name": package["name"],
            "version": package["version"],
            "integrity": package["integrity"],
            "shasum": package["shasum"],
            "tarball": package["tarball"],
        },
        "command": PI_COMMAND,
        "install_command": install_command,
        "update_command": update_command,
        "execution": "dry-run-metadata-only",
    }


def build_child_env(target: Path) -> dict[str, str]:
    child_env = {name: value for name, value in os.environ.items() if name in CHILD_ENV_ALLOWLIST}
    runtime_home = target / ".nddev-pi-runtime" / "home"
    agent_dir = target / "agent"
    session_dir = agent_dir / "sessions"
    package_dir = agent_dir / "package-cache"
    for directory in (runtime_home, agent_dir, session_dir, package_dir):
        ensure_directory(directory)
    child_env.update(
        {
            "HOME": str(runtime_home.resolve()),
            "PI_CODING_AGENT_DIR": str(agent_dir.resolve()),
            "PI_CODING_AGENT_SESSION_DIR": str(session_dir.resolve()),
            "PI_PACKAGE_DIR": str(package_dir.resolve()),
            "PI_OFFLINE": "1",
            "PI_SKIP_VERSION_CHECK": "1",
            "PI_TELEMETRY": "0",
        }
    )
    return child_env


def command_launch(target: Path, forwarded: list[str]) -> int:
    require_clean_managed(target)
    settings = read_current_settings(target)
    if settings is None:
        fail("managed settings are missing")
    nddev_settings = settings.get("nddev")
    if not isinstance(nddev_settings, dict):
        fail("managed nddev settings are missing")
    launch_args = validate_string_array(nddev_settings.get("launch_args"), "managed launch_args")
    user_args = list(forwarded)
    if user_args and user_args[0] == "--":
        user_args = user_args[1:]
    child_args = [*launch_args, "--skill", builder_skill_path(target), *user_args]
    child_env = build_child_env(target)
    try:
        completed = subprocess.run([PI_COMMAND, *child_args], env=child_env, check=False)
    except FileNotFoundError:
        fail("pi command was not found on PATH")
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

    for command in ("software-status", "software-install", "software-update"):
        command_parser = subparsers.add_parser(command)
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
        if args.command in {"software-status", "software-install", "software-update"}:
            emit(software_payload(args.command), json_enabled)
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
