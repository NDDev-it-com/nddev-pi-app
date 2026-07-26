# nddev-pi-app

Portable setup manager for the current Pi Coding Agent.

This module manages only explicit caller-selected targets. It does not read or
modify the owner's live `~/.pi`, provider credentials, project trust store, or
global package installation.

## Current Pi Identity

- Product: Pi Coding Agent
- Command: `pi`
- Package: `@earendil-works/pi-coding-agent`
- Tested version: `0.82.1`
- Package bin: `dist/cli.js`
- Node requirement: `>=22.19.0`
- Official repository: <https://github.com/earendil-works/pi>
- Official docs: <https://pi.dev/docs/latest>

The package identity and artifact metadata are pinned in
`references/pi-baseline.json`.

## Usage

```bash
python3 cli-tools/nddev_pi.py list
python3 cli-tools/nddev_pi.py plan --setup safe --target /absolute/pi-target
python3 cli-tools/nddev_pi.py install --setup safe --target /absolute/pi-target
python3 cli-tools/nddev_pi.py status --target /absolute/pi-target
python3 cli-tools/nddev_pi.py switch --setup balanced --target /absolute/pi-target
python3 cli-tools/nddev_pi.py restore --backup 0 --target /absolute/pi-target
python3 cli-tools/nddev_pi.py remove --target /absolute/pi-target
python3 cli-tools/nddev_pi.py software-plan --target /absolute/pi-target
python3 cli-tools/nddev_pi.py software-status --target /absolute/pi-target
python3 cli-tools/nddev_pi.py software-install --target /absolute/pi-target
python3 cli-tools/nddev_pi.py software-update --target /absolute/pi-target
python3 cli-tools/nddev_pi.py launch --target /absolute/pi-target -- --help
```

`software-install` uses `bun add --global --exact
@earendil-works/pi-coding-agent@0.82.1` in an isolated staging directory with
target-owned `BUN_INSTALL_GLOBAL_DIR`, `BUN_INSTALL_BIN`, `BUN_INSTALL_CACHE_DIR`,
`HOME`, `XDG_CONFIG_HOME`, and `TMPDIR`. The package declares no consumer
`preinstall`, `install`, or `postinstall` lifecycle script, so the manager does
not use Bun `--trust`.

`launch` starts the target-owned `<target>/bin/pi` wrapper with target-local
`HOME`, `XDG_*`, `TMPDIR`, `PATH`, `PI_CODING_AGENT_DIR`,
`PI_CODING_AGENT_SESSION_DIR`, and `PI_PACKAGE_DIR`. Provider API keys are not
forwarded.

## Setup Variants

- `safe`: offline startup, no project approval, and no saved Pi session.
- `balanced`: offline startup, no project approval, with target-local sessions.
- `full-auto`: offline startup with Pi project trust approval for that launch;
  this is a trust override, not a native filesystem/process sandbox.

Pi does not document built-in permission prompts, sub-agents, or plan mode. The
manager records that reality instead of inventing unsupported contracts.

## nddev-builder

`nddev-builder` is default-on in every setup through documented native Pi
surfaces:

- `settings.skills`
- `settings.packages`
- local package manifest `pi.skills`

No external Pi package catalog entry or marketplace plugin is claimed by this
module.
