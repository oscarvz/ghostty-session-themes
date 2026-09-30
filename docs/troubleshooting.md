# Troubleshooting

Start with `session-theme status` and `session-theme validate`.

| Symptom | Action |
| --- | --- |
| Command not found | Open an interactive zsh shell or source the installed `session-themes.zsh`. Check the target zshrc. |
| New sessions use the default | Run `on`. Existing default sessions need `next` to join the rotation. |
| Changes only happen at prompts | Set `live on` and `mode auto`; check observer status for errors. |
| Mode stays light or dark | `mode auto` restores system tracking for assigned families. |
| A theme was renamed or removed | Edit `session-theme config`, then run `validate` and `reload`. |
| Appearance error after a macOS upgrade | Check the installed version. The fallback parses a plist; it does not match error text. Pin `mode light` or `mode dark` temporarily if needed. |
| A program reset colours | Run `reload` after it exits. |
| A program paints its own background | Configure that application's theme separately. |
| Python was moved or removed | Reinstall with `GHOSTTY_SESSION_THEMES_PYTHON=/new/path/python3`. |
| Ghostty was moved | Reinstall with `--ghostty /new/path/Ghostty.app`. |
| Unknown files at the prefix | Inspect them or choose a clean prefix; unrelated files are not overwritten. |
| Restore refuses a changed file | Compare it with the backup and preserve later edits manually. |

The abbreviated commands above are arguments to `session-theme`. Outside a shell
that has loaded the function, use the installed launcher:

```sh
"$HOME/Library/Application Support/ghostty-session-themes/session-theme" status
```

`session-themes-listener-status.json` records the last background result. A lock
file existing does not mean the observer is running: status checks the process-held
lock. Do not delete a lock file held by a running observer, since that could allow
a duplicate process.

Invalid settings leave shells usable. A failing prompt hook restores native colours
and pauses to avoid repeated warnings. Fix settings and run `session-theme reload`.
Background failures are retried on the next settings or appearance event.
