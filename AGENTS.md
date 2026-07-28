# nddev-pi-app Agent Rules

Work only inside this public module unless the user explicitly changes scope.
Repository artifacts are English.

## Ownership

- Public manager: `cli-tools/nddev_pi.py`.
- Public validator: `cli-tools/validate_public_contracts.py`.
- Public contract: `config/nddev-contract.json`.
- Public build metadata: `build/manifest.json` and `build/version.json`.
- Runtime baseline pins: `references/pi-baseline.json`.
- Content setup: `setups/nddev-builder/`.
- Permission profiles: `profiles/full-auto/` and `profiles/safe/`.
- Native builder resources: `builder/nddev-builder/`.

Do not add private validation, fixtures, benchmark data, operational memories,
runtime logs, generated evidence, credentials, live `~/.pi` state, root harness
files, registry updates, CI changes, pushes, or tags here.

## Product Boundary

The module manages only explicit caller-selected targets. The target is a
Pi configuration/runtime home, not the project workspace. Managed launch must
pass an explicit child working directory selected by the public manager.

Use the setup/profile model: `nddev-builder` owns content, while `full-auto`
and `safe` own runtime posture. Keep future setup switching orthogonal to
future profile switching.

## Native Pi Surfaces

Use documented native Pi surfaces only:

- `settings.skills`
- `settings.packages`
- local package `pi.skills`
- target-owned Pi configuration, session, package-cache, and runtime
  environment paths declared in the public contract

Do not claim a Pi plugin marketplace, native sub-agent format, native plan mode,
or built-in permission sandbox unless official Pi sources add one and the
contract is updated.

## Validation

Before committing public module changes, run:

```bash
PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 -B cli-tools/validate_public_contracts.py
/usr/bin/python3 -B cli-tools/nddev_pi.py list --json
git diff --check
```

Do not run live software install, CI, push, or tag unless the user explicitly
approves that later phase.
