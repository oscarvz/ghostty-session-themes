# Ghostty session themes

Give each new Ghostty terminal a different theme family, and keep its light/dark
variant in sync with macOS. This makes windows, tabs and splits easier to tell apart.

- Rotate through ten paired theme families, or define your own list.
- Follow system appearance at an idle prompt and while a command is running.
- Keep a session's family when opening a nested zsh shell.
- Pin light/dark mode, choose the next family, or restore Ghostty's native default.
- Control everything from one settings file and the `session-theme` command.
- Back up affected files before installation, upgrade and uninstall.

The helper reads colours from your installed Ghostty themes and preserves your
Ghostty configuration. It has no Python package dependencies, login items or
LaunchAgents. One small AppKit observer is shared by all sessions.

## Requirements

- macOS with Ghostty installed as an application bundle.
- zsh for interactive terminal sessions.
- Python **3.9 or newer** and Apple's Command Line Tools (or Xcode).

```sh
python3 --version
xcrun --find clang
```

If Command Line Tools are missing, run `xcode-select --install` and finish that
installation first. The observer is compiled locally. End-to-end behaviour has
been checked on macOS 27.0.1 with Ghostty 1.3.1. Other versions should be validated
with the checks below. Linux, other shells, SSH, tmux and screen are outside this
release's supported scope.

## Install

```sh
git clone https://github.com/oscarvz/ghostty-session-themes.git
cd ghostty-session-themes
./scripts/install --check
./scripts/install
```

`--check` compiles the observer and validates theme pairs without changing installed
files. No `sudo` is needed. Open a new Ghostty terminal to load the hook, or run the
`source` command printed by the installer in an existing zsh session.

The default installation directory is:

```text
~/Library/Application Support/ghostty-session-themes/
```

It contains installed code, personal settings, state and timestamped backups. The
installer adds one labelled block to `.zshrc`, respecting an exported `ZDOTDIR` and
preserving a symlinked `.zshrc`. Code is copied; moving or deleting the checkout
does not remove the installation.

Ghostty is discovered through `PATH`, `/Applications`, or `~/Applications`.
For a custom setup:

```sh
./scripts/install --ghostty ~/Applications/Ghostty.app --zshrc ~/.config/zsh/.zshrc
```

Other options are `--prefix /installation/directory`, `--config /initial/settings.ini`
for a fresh installation, and `--legacy-dir /previous/helper/directory` for migration.
Use `--help` for details. To select Python explicitly:

```sh
GHOSTTY_SESSION_THEMES_PYTHON=/path/to/python3 ./scripts/install
```

Choose a long-lived interpreter, not a temporary virtual environment. Its absolute
path is recorded in a launcher used by both zsh and the observer.

## Commands

| Command | Effect |
| --- | --- |
| `session-theme status` | Show version, settings, this session's theme and observer status |
| `session-theme on` / `off` | Enable or disable assignment for **new** sessions |
| `session-theme next` | Give this terminal the next family |
| `session-theme default` | Restore this terminal's native Ghostty theme |
| `session-theme mode auto` | Follow macOS light/dark appearance |
| `session-theme mode light` / `dark` | Pin the variant of assigned themes |
| `session-theme live on` / `off` | Enable or disable immediate background updates |
| `session-theme config` | Print the central settings file path |
| `session-theme validate` | Check pair names, colours and light/dark classification |
| `session-theme reload` | Reapply colours and resume a paused prompt hook |

`off` leaves existing sessions on their assigned families. Sessions created while
it is off stay on Ghostty's default until `next`. `live off` stops the observer;
the prompt hook still follows appearance when the next prompt is drawn. Changing
settings in the file has the same effect as using the commands.

## Configuration

Edit the path returned by `session-theme config`:

```ini
[settings]
enabled = true
appearance = auto
live_updates = true
show_status = true

[pairs]
rose-pine = Rose Pine Moon | Rose Pine Dawn
catppuccin = Catppuccin Mocha | Catppuccin Latte
```

Each pair is `family = Dark theme name | Light theme name`. Pairs rotate in file
order. The [example](config/session-themes.conf) has Rose Pine, Catppuccin, Gruvbox,
Flexoki, TokyoNight, Solarized, Nord, Melange, Everforest and Modus. Set
`show_status = false` to hide the startup banner.

Use `ghostty +list-themes` to preview themes, or
`ghostty +list-themes --plain --color=light` and `--color=dark` to list classifications.
Run `session-theme validate` after editing. If your Ghostty version lacks an example
theme, adjust your initial settings and supply them with `--config`.

`default` restores Ghostty's own configuration. Ghostty supports a
[paired theme setting](https://ghostty.org/docs/features/theme), for example
`theme = dark:Rose Pine Moon,light:Rose Pine Dawn`. The installer does not insert
or replace that setting.

## Upgrade and migrate

```sh
git pull --ff-only
./scripts/install
```

Use `git switch --detach v0.1.0` before installing to select a specific release.
Re-running install preserves settings and session state, updates the managed shell
block once, and restarts the observer. Supply `--prefix` again if you used a custom
directory. Reinstall after moving Ghostty or replacing the selected Python.

The earlier helper stored beside Ghostty's configuration is detected automatically.
The installer backs it up, imports settings and assignments, and leaves forwarding
files for already-open shells. Older backups stay in their original location.
See [installation and recovery](docs/installation.md).

## Uninstall and restore

```sh
./scripts/uninstall
```

This stops the observer and removes the managed shell block. Settings, state,
installed files and backups are retained. A disabled marker prevents already-open
shells from restarting the observer; colours return to Ghostty's default at the
next prompt. Open a new shell to unload old functions. A running application keeps
its current colours until it returns to a prompt or is closed.

Install, upgrade and uninstall print their backup directory. To restore:

```sh
./scripts/restore '/path/printed/by/the/installer'
```

Restore verifies checksums and refuses to overwrite files edited since the operation.
It does not roll back session state. See [recovery details](docs/installation.md).

## Limitations and development

Changes cover the palette, foreground, background and cursor. Selection and
cursor-text colours remain those of the native theme. Applications using their
own truecolour backgrounds may hide the theme; applications that reset colours
may require `session-theme reload` afterwards.

Appearance changes normally arrive shortly after the system changes; settings edits
are noticed within a few seconds. If the observer exits, the next prompt restarts it.
See [troubleshooting](docs/troubleshooting.md).

Run `python3 -m unittest discover -s tests -v`. Tests use temporary directories and
synthetic themes and do not recolour your terminals. Read [development](docs/development.md),
[architecture](docs/architecture.md) and [implementation history](CHANGELOG.md).
Licensed under [MIT](LICENSE).
