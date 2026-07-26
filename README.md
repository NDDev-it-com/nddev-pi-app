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
python3 cli-tools/nddev_pi.py launch --target /absolute/pi-target -- --help
```

`launch` starts `pi` with target-local `HOME`, `PI_CODING_AGENT_DIR`,
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
