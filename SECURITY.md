# Security

Report security issues privately through the repository owner.

This module does not persist provider credentials. Tests and benchmarks must
use temporary homes, targets, package directories, and stub executables. The
setup manager refuses implicit live Pi configuration paths and only forwards
source-proven provider environment variables to the launched child process.
