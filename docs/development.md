# Development

Python uses the standard library and supports 3.9+. The macOS observer uses
Objective-C and AppKit; Linux uses the shared Python helper and `gdbus`.
No Python package installation is needed for tests.

```sh
python3 -m unittest discover -s tests -v
zsh -n src/session-themes.zsh
bash -n src/session-themes.bash
sh -n scripts/install scripts/uninstall scripts/restore
```

Build the native observer on **macOS only**:

```sh
mkdir -p build
xcrun clang -fobjc-arc -Wall -Wextra -Werror -framework AppKit \
  -o build/session-themes-observer src/session-themes-observer.m
```

Tests synthesize palettes in temporary directories. Installer tests use a fake
Ghostty bundle/compiler on macOS and an executable/share layout on Linux. CI builds
the actual observer on macOS. Linux checks exercise a synthetic portal event stream,
singleton locking, settings changes, shutdown and colour writes to a private pseudo
terminal. Tests do not load personal shell startup files, change system appearance or write to
user terminals. The original 16 tests were also reconstructed from the import
commit and run unchanged against the refactored helper and real Ghostty resources.
Maintained tests preserve those assertions with portable synthetic resources.

Bash tests run real shells on private pseudo terminals and check nested identity,
prompt callbacks, exit status, startup paths, upgrades and recovery. CI uses
`/bin/bash` explicitly so macOS checks its bundled Bash 3.2; array prompt callbacks
are tested on Bash 5.1+, where Bash supports executing them.

After compiling, `python3 tests/check_native_lifecycle.py` checks that the native
observer waits for an in-flight writer before shutting down. It needs a macOS GUI
session and uses only a synthetic writer in a temporary directory.

## Interactive release check

Use a temporary prefix and shell file to avoid migrating your own installation:

```sh
test_dir=$(mktemp -d)
./scripts/install --prefix "$test_dir/install" --zshrc "$test_dir/zshrc" \
  --legacy-dir "$test_dir/no-legacy"
```

Open two temporary Ghostty windows running `zsh -f`. Source the installed
`session-themes.zsh` using the actual temporary path in each. These shells must not
source the personal zshrc. Confirm different families.

Repeat for Bash using `--shell bash --rc-file "$test_dir/bashrc"` in a separate
prefix. Start test shells with `bash --noprofile --norc` and source the installed
`session-themes.bash`. Do not source personal startup files. Check both shell hooks
with an existing prompt customization.

1. Leave one idle and run `sleep 60` in the other.
2. Toggle system light → dark → light. Both should change variant without changing
   family or receiving input. Restore the original system appearance afterwards.
3. Exercise `next`, `default`, pinned modes and `mode auto`.
4. Check `live off`, prompt fallback, then `live on` and one active observer.
5. Reinstall and verify settings and assignments persist.
6. Uninstall the temporary prefix, verify the observer stops, then restore its backup.
7. Uninstall again, close temporary shells and remove the temporary directory.

Headless CI cannot establish real GUI appearance notification behaviour; this check
is separate. On Linux run it in the desktop session where Ghostty runs, with a
working Settings portal, on each desktop you intend to support. Test both Wayland
and X11 where available. Also verify pinned light/dark modes without `gdbus`.
For migration changes, also import a copy of the older helper and call
its forwarding entry point from a shell opened before migration.

## Releases

Edit repository source and run the installer to deploy it. Update `VERSION` and
`CHANGELOG.md`, complete automated and interactive checks, commit, then tag a release.
GitHub Actions runs after pushing. Publishing is separate from creating a local tag.

Theme files come from Ghostty and are not vendored. The example contains names only;
test palettes are synthetic. Runtime data, compiled binaries, personal settings and
backups must stay out of Git.

## Contributing from a fork

You do not need write access to this repository. Fork it on GitHub, clone your fork,
and add `https://github.com/oscarvz/ghostty-session-themes.git` as an `upstream` remote.
Create a feature branch from `upstream/main`, make the change and run the checks
above. Push the branch to your fork and open a pull request targeting
`oscarvz/ghostty-session-themes:main`. Include the platforms tested and any GUI checks
still needed. The maintainer reviews and merges the contribution.
