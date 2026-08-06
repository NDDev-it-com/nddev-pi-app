# Changelog

## [0.1.1] - 2026-08-06

- Update Pi Coding Agent to `0.84.0`, including exact npm integrity and tarball
  identity.
- Keep the native installed-wrapper `pi --version` output (`0.0.0`) paired with
  package.json `0.84.0` as two independently required executable identities.
- Keep persistent external lock anchors valid across manager version upgrades;
  legacy version-bearing bindings are accepted only when every stable identity
  field still matches.

## [0.1.0]

- Add an explicit-target Pi Coding Agent setup manager.
- Add the nddev-builder content setup with full-auto and safe runtime profiles.
- Project nddev-builder through documented Pi skills/package surfaces.
- Add public contract metadata, Pi baseline evidence, and release CI callers.
