# Security Policy

## Supported versions

The project is pre-1.0. Security fixes are applied to the latest commit on
`main`; older snapshots are not supported.

## Reporting a vulnerability

Please use GitHub's private vulnerability reporting for this repository. Do
not open a public issue for an unpatched vulnerability. Include the affected
command, task definition, impact, reproduction steps, and any suggested
mitigation.

## Trust boundary

Task definitions and evaluator commands are trusted executable input. The
harness avoids shell interpolation, constrains declared patches, audits
filesystem effects, and uses detached Git worktrees for source isolation. It
does not provide an OS, process, network, or container sandbox. Run untrusted
tasks only inside an external sandbox with appropriate resource and network
controls.
