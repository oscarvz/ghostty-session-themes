# Installation, migration and recovery

See the [README](../README.md) for prerequisites and commands. One selected shell
per installation prefix is supported. Multiple installations controlling the same
terminals can compete for colours.

## Files and paths

Installation copies code into the per-user prefix, creates settings on first use,
and adds labelled shell startup blocks. Upgrades retain settings and session state. Builds
and theme validation happen before user files are changed.

macOS defaults to `~/Library/Application Support/ghostty-session-themes/`; Linux
uses `$XDG_DATA_HOME/ghostty-session-themes/`, falling back to
`~/.local/share/ghostty-session-themes/`. Personal settings, state and backups live
in that same prefix on either platform. `--prefix` overrides it.

Linux needs no native build. In automatic mode preparation verifies that `gdbus`
can read the desktop Settings portal. If unavailable, supply an initial `--config`
with `appearance = light` or `dark`. `--resources /path/to/themes` handles custom
Ghostty packages; its value is recorded for upgrades. `GHOSTTY_RESOURCES_DIR` instead
points to the Ghostty resources directory containing `themes/`.

Fresh installations choose Bash or zsh from `$SHELL`; `--shell bash|zsh` overrides it.
Upgrades retain the recorded shell and startup paths. Older runtime metadata without
a shell field is treated as zsh for compatibility.

zsh uses an exported `$ZDOTDIR`, otherwise `~/.zshrc`. Bash uses `~/.bashrc` and
the first existing login profile in Bash's search order: `~/.bash_profile`,
`~/.bash_login`, `~/.profile`. If none exists, it creates `~/.bash_profile`. This covers
both login and non-login interactive shells. A guard makes the Bash block inert
when `.profile` is read by another shell. Repeated sourcing does not duplicate the
prompt callback or rotate the current session.

Use `--shell bash --rc-file /path/to/bashrc` or `--shell zsh --rc-file /path/to/zshrc`
to manage just one custom file. `--zshrc /path` remains a compatibility alias for zsh.
With a custom file, ensure your shell loads it. Symlinks are resolved so links survive.
To switch shells or startup files, uninstall first, then reinstall with the new
selection. Settings and assignments are retained. The installer never changes your
login shell.

Existing Ghostty `config.ghostty` and `config` files in the standard XDG and macOS
locations are snapshotted, but never edited. These are
[Ghostty's documented locations](https://ghostty.org/docs/config). Files referenced
through `config-file` are not recursively backed up because this project does not
modify them. Private backups can include your shell configuration and must stay out of Git.

## Legacy migration

The default legacy directory is
`~/Library/Application Support/com.mitchellh.ghostty/` on macOS, or
`${XDG_CONFIG_HOME:-~/.config}/ghostty/` on Linux. On first installation,
the presence of `session-themes.py` and `session-themes.conf` triggers migration.
Use `--legacy-dir` for another location.

Migrate the earlier zsh helper with `--shell zsh` first. To use Bash afterwards,
uninstall that integration and reinstall with `--shell bash`.

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
./scripts/restore '/exact/backup/path/printed/by/the/installer'
```

Restore verifies backup hashes and checks that managed files have not changed since
the operation. It refuses to overwrite later edits. Compare such files with the
numbered originals identified in `manifest.json`; do not blindly restore your whole
shell configuration. Session state is retained rather than rolled back to a snapshot.

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
