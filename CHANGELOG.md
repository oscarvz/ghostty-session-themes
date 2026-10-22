# Changelog

## Unreleased

- Bash 3.2+ support alongside zsh, preserving prompt callbacks and command exit status.
- Explicit shell/custom startup selection, Bash login and non-login integration,
  and backward-compatible upgrades for existing zsh installations.
- Linux installation with XDG paths, executable/resource discovery and Snap support.
- Linux Settings portal observer for automatic light/dark switching in idle and busy
  terminals, sharing rendering and state with macOS. Pinned modes need no portal.
- Portable session UUID generation and Linux pseudo-terminal ownership checks.
- Linux lifecycle and installer regressions, cross-platform setup and contributor docs.

## 0.1.0 — 2026-09-30

First repository release, extracted from the working personal installation.

- Per-terminal rotation across ten light/dark families.
- Native macOS appearance observer for idle/busy terminals, with prompt fallback.
- Central controls, native-default restoration and terminal ownership checks.
- Per-user install, upgrade, uninstall and checksum-checked restore.
- Ghostty discovery, recorded Python paths and local native compilation.
- Migration preserving settings and assignments, including forwarding for old shells.
- Regression and installer tests, macOS build workflow and maintenance documentation.

## Before the repository

These milestones come from saved backups and implementation history. They are
historical notes, not reconstructed Git commits.

- **2026-09-08:** Initial rotation, central configuration, backups and ten-family list.
- **2026-09-21:** Structured macOS preference parsing replaced error-text matching.
- **2026-09-30:** Background observer, live controls and idle/busy verification.

Git history starts with the license commit, followed by the working implementation
import and separate packaging changes.
