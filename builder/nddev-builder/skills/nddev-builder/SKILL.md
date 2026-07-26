---
name: nddev-builder
description: Build, inspect, and maintain NDDev-compatible Pi setup artifacts through documented Pi skills/package surfaces.
---

# nddev-builder for Pi

Use this skill when working on NDDev Pi setup artifacts. Keep public module
state separate from private validation state, prefer explicit target paths, and
do not run installers or read provider credentials unless the user explicitly
does so outside the setup manager.

For Pi, this projection is intentionally limited to documented native surfaces:
`settings.skills`, `enableSkillCommands`, and a local package manifest with
`pi.skills`. No external Pi package catalog entry or marketplace plugin is
claimed by this module.
