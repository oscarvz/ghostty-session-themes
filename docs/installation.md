# Installation, migration and recovery

See the [README](../README.md) for prerequisites and commands. One active installation
per shell configuration is supported. Multiple installations controlling the same
terminals can compete for colours.

## Files and paths

Installation copies code into the per-user prefix, creates settings on first use,
and adds a labelled zshrc block. Upgrades retain settings and session state. Builds
and theme validation happen before user files are changed.

The default zshrc uses an exported `$ZDOTDIR`, otherwise `~/.zshrc`. Use `--zshrc`
when ZDOTDIR is set only inside the shell. Symlinks are resolved so the link survives.
To move integration to a different zshrc, uninstall first and select the new path.

Existing Ghostty `config.ghostty` and `config` files in the standard XDG and macOS
locations are snapshotted, but never edited. These are
[Ghostty's documented locations](https://ghostty.org/docs/config). Files referenced
through `config-file` are not recursively backed up because this project does not
modify them. Private backups can include your zshrc and must stay out of Git.

## Legacy migration

The default legacy directory is
`~/Library/Application Support/com.mitchellh.ghostty/`. On first installation,
the presence of `session-themes.py` and `session-themes.conf` triggers migration.
Use `--legacy-dir` for another location.

Settings and assignments are imported. The old observer stops before the new one
starts. The old Python/zsh entry points become forwarding files for existing shells.
Old binaries, documentation and backups remain available, but repository source
and the new installed settings are now the maintained versions.

## Upgrade and uninstall

Run `git pull --ff-only` and `./scripts/install`, or select a release tag before
installing. `session-theme status` reports the installed version. Updating the
checkout alone does not deploy it. Supply a custom `--prefix` again on subsequent
install/uninstall commands. Reinstall after moving Ghostty or replacing Python.

Uninstall stops the observer, removes its shell block and sets `.disabled`. Settings
and code are retained so already-open shells can stop safely. It can be repeated.
Reinstall to enable it again. Once all old shells are closed, retained files can be
removed manually if their settings and backups are no longer needed. Keep legacy
forwarding files until shells that reference them have closed.

## Restore

Install, upgrade and uninstall print a backup directory:

```sh
./scripts/restore "$HOME/Library/Application Support/ghostty-session-themes/backups/<timestamp>-install"
```

Restore verifies backup hashes and checks that managed files have not changed since
the operation. It refuses to overwrite later edits. Compare such files with the
numbered originals identified in `manifest.json`; do not blindly restore your whole
zshrc. Session state is retained rather than rolled back to a snapshot.

Restoring an upgrade reinstates earlier code. Restoring uninstall reinstates the
shell integration. Restoring a fresh installation removes its integration but
retains disabled code and data for existing shells. Restoring migration also restores
the original helper. Open a new shell afterwards. A legacy rollback resumes the
legacy registry; the migrated registry remains in the new prefix for reference.

If the observer cannot stop within the bounded wait, installation aborts. If replacing
files fails, the journal restores previous files unless it detects a concurrent edit.
An error identifies the recovery backup. A failed restore leaves the installation
disabled so partially restored code is not automatically launched; use the backup
manifest for recovery.
