# Pi Setup Manager

`nddev-pi-app` writes a complete Pi Coding Agent setup into one explicit
absolute target. The target becomes the Pi runtime root for managed launches:

- `PI_CODING_AGENT_DIR=<target>/agent`
- `PI_CODING_AGENT_SESSION_DIR=<target>/agent/sessions`
- `PI_PACKAGE_DIR=<target>/agent/package-cache`
- `HOME=<target>/.nddev-pi-runtime/home`
- `XDG_CONFIG_HOME`, `XDG_DATA_HOME`, `XDG_STATE_HOME`, and `XDG_CACHE_HOME`
  under `<target>/.nddev-pi-runtime/`
- `TMPDIR=<target>/.nddev-pi-runtime/tmp`
- `PATH=<target>/bin:<recorded-node-dir>:/usr/bin:/bin`

The manager rejects relative targets, target symlinks, symlinked managed files,
hard-linked managed files, and oversized managed metadata. Backups are stored in
the target-bound sibling directory `.<target-name>.nddev-pi-backups` and rotate
across ten slots.

## Lifecycle

`plan` is side-effect free. `install`, `switch`, `restore`, and `remove` require
a clean managed target and create target-bound backups before replacing managed
state. Unknown files and user-owned settings keys are preserved. Co-owned
`skills` and `packages` arrays keep non-NDDev entries.

## Pi Capability Model

Official Pi documentation confirms settings, skills, packages, extensions, and
project trust controls. It does not document native permission popups, sub-agent
configuration, or a built-in plugin marketplace for this manager. The
`full-auto` profile therefore uses Pi project trust approval and isolated
process environment only; it is not represented as a sandbox.

## Software Commands

`software-plan` and `software-status` are side-effect free and never execute the
target-owned Pi binary. `software-install` and `software-update` install the
pinned Pi npm package in isolated stage-owned install/cache/home/tmp paths. The
exact npm argv, package identity, layout checks, Node runtime recording, and
version-probe contract are owned by `references/pi-baseline.json`,
`build/version.json`, and `config/nddev-contract.json`.

The manager does not persist npm-created symlinks or detach Pi's ESM entrypoint
from neighboring imports. It materializes a private Node wrapper inside the
sanitized software tree and a target-visible wrapper that points at that
package entrypoint.

Staged and persisted trees remain bounded by independently enforced path-count
and logical-byte limits. The measured exact-package calibration is owned by
`references/pi-baseline.json`, while `config/nddev-contract.json` declares the
protective limits and preserved path, symlink, mode, and digest checks. The
software stamp records the installed tree metrics and limits for status
revalidation.

The pinned package has no consumer `preinstall`, `install`, or `postinstall`
script in the recorded baseline. npm is invoked with consumer scripts disabled.
