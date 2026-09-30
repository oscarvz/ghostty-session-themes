# Architecture

Three parts cooperate:

1. `src/session-themes.zsh` registers a UUID for each direct, local, interactive
   Ghostty terminal and calls Python at startup and before prompts. Nested shells
   on the same TTY inherit the UUID and family.
2. `src/session-themes.py` owns settings, rotation, rendering, terminal checks,
   persistence and CLI commands.
3. `src/session-themes-observer.m` observes AppKit's `NSApplication.effectiveAppearance`
   and calls the same Python renderer on each change. A 300 ms debounce lets Ghostty
   apply its native appearance first. A two-second timer checks settings modification
   time and the disabled marker; it does not poll system appearance or spawn Python
   every two seconds.

The observer has no window or Dock icon. A process-held lock prevents duplicates.
Child tasks are serialized and bounded to ten seconds. A pending event is retained.
The next shell prompt can restart an observer that has exited; there is no LaunchAgent.

## Installed layout

```text
ghostty-session-themes/
├── session-theme                  # Generated launcher with a Python path
├── session-themes.py
├── session-themes.zsh
├── session-themes-observer         # Compiled locally; excluded from Git
├── runtime.json                   # Detected paths, version and shell target
├── session-themes.conf            # Personal settings and rotation
├── session-themes-state.json      # Counter and assignments
├── session-themes-listener-status.json
├── .session-themes.lock
├── .session-themes-observer.lock
├── .install.lock
├── .disabled                      # Maintenance or uninstall marker
└── backups/
```

Source and example settings belong in Git. Installed code is copied, so checkout
edits do not immediately affect running shells. Personal settings and data survive
upgrades and stay outside the repository.

## Colour updates

The helper parses bundled themes as data and emits
[OSC 4](https://ghostty.org/docs/vt/osc/4) and
[OSC 10/11/12](https://ghostty.org/docs/vt/osc/1x). It accepts six-digit RGB colours,
a complete 16-colour ANSI palette and optional extra palette entries. It never
executes theme files.

For background events the newest session on a TTY wins. Native-default sessions
are skipped. The owning shell's UID, TTY and start time must match the saved entry.
The target must be a user-owned character device and is opened without following
symlinks. Dead shells and reused terminals are skipped. Only colour escapes are
written as terminal output; no command input is sent.

State is committed after a successful background write. Failed writes invalidate
the cached signature so the prompt hook can retry. Atomic replacement and bounded
locks protect files. State stores UUIDs, TTYs, PIDs, timestamps and theme choices,
never command history. The prompt fallback reads a preferences plist instead of
matching localized `defaults` errors. Native-default appearance remains Ghostty's job.

## Installation boundary

`scripts/manage.py` centralizes install, uninstall and restore. It builds and
validates before changing user files. A journal records affected files, permissions
and checksums. The shell integration replaces one labelled block; duplicate or
malformed blocks are rejected. The observer is suspended before replacing code.

The generated launcher selects Python for both zsh and AppKit. Runtime metadata
supplies Ghostty's executable and resource paths. Legacy forwarding entry points
let already-open shells retain their session identifiers after migration.
