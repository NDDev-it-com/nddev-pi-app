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
`full-auto` setup therefore uses Pi project trust approval and isolated process
environment only; it is not represented as a sandbox.

## Software Commands

`software-plan` and `software-status` are side-effect free and never execute the
target-owned Pi binary. `software-install` and `software-update` install
`@earendil-works/pi-coding-agent@0.82.1` with:

```bash
bun add --global --exact @earendil-works/pi-coding-agent@0.82.1
```

The Bun process receives only stage-owned install/cache/home/tmp paths. The
manager persists the staged `install/global` and `bin` trees, verifies the
official package layout, checks the staged binary with isolated Pi runtime
environment, records the external Node path/version/digest, then atomically
swaps `<target>/.nddev-pi-software/current`, `<target>/bin/pi`, and
`NDDEV-PI-SOFTWARE.json`. Fresh failures remove transaction-created target
state; updates roll back byte-for-byte including stamp modes.

The Bun-created `bin/pi` symlink must resolve inside staging to the declared
package entrypoint. The manager does not persist that symlink or detach its ESM
file from neighboring imports; it replaces it with a private relative Node
wrapper inside the sanitized software tree. The target-visible wrapper remains
separate and points at the package entrypoint in the atomically swapped tree.

The published package identity is `0.82.1`, while its current `pi --version`
stdout is `0.0.0`. These are independent fail-closed checks: the manager
requires the exact package name/version/bin from package metadata and the exact
CLI probe output recorded by `references/pi-baseline.json`. Probe stdout never
substitutes for package identity.

Staged and persisted trees remain bounded by independently enforced path-count
and logical-byte limits. The measured exact-package calibration is owned by
`references/pi-baseline.json`, while `config/nddev-contract.json` declares the
protective limits and preserved path, symlink, mode, and digest checks. The
software stamp records the installed tree metrics and limits for status
revalidation.

The pinned package has no consumer `preinstall`, `install`, or `postinstall`
script, so Bun `--trust` is not used. The published `prepublishOnly` script is
recorded as package evidence but is not run by consumers.
