# nddev-pi-app

Portable setup manager for the current Pi Coding Agent.

This module manages only explicit caller-selected targets. It does not read or
modify the owner's live `~/.pi`, provider credentials, project trust store, or
global package installation.

## Current Pi Identity

The package identity, version pin, registry provenance, and runtime constraints
are machine-owned by `build/version.json`, `references/pi-baseline.json`, and
`config/nddev-contract.json`. Official Pi documentation is at
<https://pi.dev/docs/latest>.

## Usage

```bash
python3 cli-tools/nddev_pi.py list
python3 cli-tools/nddev_pi.py plan --target /absolute/pi-target
python3 cli-tools/nddev_pi.py install --profile full-auto --target /absolute/pi-target
python3 cli-tools/nddev_pi.py status --target /absolute/pi-target
python3 cli-tools/nddev_pi.py switch --profile safe --target /absolute/pi-target
python3 cli-tools/nddev_pi.py restore --backup 0 --target /absolute/pi-target
python3 cli-tools/nddev_pi.py remove --target /absolute/pi-target
python3 cli-tools/nddev_pi.py software-plan --target /absolute/pi-target
python3 cli-tools/nddev_pi.py software-status --target /absolute/pi-target
python3 cli-tools/nddev_pi.py software-install --target /absolute/pi-target
python3 cli-tools/nddev_pi.py software-update --target /absolute/pi-target
python3 cli-tools/nddev_pi.py launch --target /absolute/pi-target -- --help
```

`software-install` uses Pi's reproducible npm package channel in an isolated
staging directory. The exact package pin, npm argv, integrity, staged layout,
and consumer lifecycle-script policy are owned by the public machine contract
files named above.

`launch` starts the target-owned `<target>/bin/pi` wrapper with target-local
`HOME`, `XDG_*`, `TMPDIR`, `PATH`, `PI_CODING_AGENT_DIR`,
`PI_CODING_AGENT_SESSION_DIR`, and `PI_PACKAGE_DIR`. Source-proven provider
credential environment variables may be inherited by the child process only;
they are not copied into target files.

## Setup And Profiles

The only content setup id is `nddev-builder`. `full-auto` is the default
runtime profile. `safe` is a reduced-tool future profile. These profiles are Pi
permission/runtime settings, not content setups and not OS security boundaries.

Pi does not document built-in permission prompts, sub-agents, or plan mode. The
manager records that reality instead of inventing unsupported contracts.

## nddev-builder

`nddev-builder` is default-on through documented native Pi resource surfaces:

- `settings.skills`
- `settings.packages`
- local package manifest `pi.skills`

No external Pi package catalog entry or marketplace plugin is claimed by this
module.
