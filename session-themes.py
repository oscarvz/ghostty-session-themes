#!/usr/bin/python3
"""Per-terminal Ghostty colours. Python 3.9+, standard library only."""

import configparser
import contextlib
import fcntl
import hashlib
import json
import os
from pathlib import Path
import plistlib
import re
import stat
import subprocess
import sys
import tempfile
import time
from xml.parsers.expat import ExpatError


DIRECTORY = Path(__file__).resolve().parent
RESOURCES = Path('/Applications/Ghostty.app/Contents/Resources/ghostty/themes')
GHOSTTY = '/Applications/Ghostty.app/Contents/MacOS/ghostty'
ESC = '\x1b'
RESET = ''.join(ESC + ']' + str(code) + ESC + '\\' for code in (104, 110, 111, 112))
HELP = """session-theme on/off          Enable/disable NEW sessions
session-theme status          Show global settings and this session's choice
session-theme next            Rotate this terminal to another theme
session-theme default         Restore this terminal's configured Ghostty default
session-theme mode auto|light|dark
                              Set appearance for all assigned sessions
session-theme live on|off      Enable/disable immediate background updates
session-theme validate        Check the settings and installed light/dark themes
session-theme reload          Resume the hook after fixing a settings error
session-theme config          Print the central settings file path
session-theme help            Show these commands"""


def atomic_write(path, text):
    path = Path(path)
    descriptor, temporary = tempfile.mkstemp(prefix='.' + path.name, dir=str(path.parent))
    try:
        with os.fdopen(descriptor, 'w', encoding='utf-8') as stream:
            stream.write(text)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


@contextlib.contextmanager
def locked(path):
    with open(path, 'a', encoding='utf-8') as stream:
        deadline = time.monotonic() + 0.5
        while True:
            try:
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise ValueError('Theme state is busy; run session-theme reload to retry.')
                time.sleep(0.01)
        try:
            yield
        finally:
            fcntl.flock(stream, fcntl.LOCK_UN)


def theme_colours(name, resources=RESOURCES):
    if not name or name in ('.', '..') or any(c in name for c in '/\\\x1b\n\r'):
        raise ValueError('Invalid theme name: ' + repr(name))
    values = {}
    for raw in (resources / name).read_text(encoding='utf-8').splitlines():
        line = raw.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        key, value = (part.strip() for part in line.split('=', 1))
        if key == 'palette':
            index, value = (part.strip() for part in value.split('=', 1))
            if not index.isdecimal() or not 0 <= int(index) <= 255:
                raise ValueError('Invalid palette index in ' + name)
            key = int(index)
        elif key not in ('background', 'foreground', 'cursor-color'):
            continue
        if not re.fullmatch(r'#?[0-9a-fA-F]{6}', value):
            raise ValueError('Expected a six-digit RGB colour in ' + name)
        values[key] = '#' + value.lstrip('#').lower()
    required = {'background', 'foreground'} | set(range(16))
    if not required.issubset(values):
        raise ValueError('Theme needs a background, foreground and 16 ANSI colours: ' + name)
    return values


def colour_sequence(values):
    palette = ';'.join(str(i) + ';' + values[i] for i in sorted(k for k in values if isinstance(k, int)))
    sequences = [ESC + ']4;' + palette + ESC + '\\']
    for code, key in ((10, 'foreground'), (11, 'background'), (12, 'cursor-color')):
        if key in values:
            sequences.append(ESC + ']' + str(code) + ';' + values[key] + ESC + '\\')
    return RESET + ''.join(sequences)


def system_appearance():
    # Light mode omits the key. Read a plist instead of matching defaults'
    # missing-key error text, which changes across macOS versions and locales.
    result = subprocess.run(
        ['/usr/bin/defaults', 'export', 'NSGlobalDomain', '-'],
        capture_output=True, timeout=0.5,
    )
    if result.returncode != 0:
        raise ValueError('Cannot read macOS appearance preferences. Set appearance = light or dark explicitly.')
    try:
        preferences = plistlib.loads(result.stdout)
    except (ValueError, ExpatError) as error:
        raise ValueError('Cannot read macOS appearance: invalid preference data.') from error
    if not isinstance(preferences, dict):
        raise ValueError('Cannot read macOS appearance: expected a preference dictionary.')
    appearance = preferences.get('AppleInterfaceStyle')
    if appearance == 'Dark':
        return 'dark'
    if appearance is None or appearance == 'Light':
        return 'light'
    raise ValueError('Cannot read macOS appearance: unrecognised preference value.')


def process_alive(pid):
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def terminal_owners(entries):
    """Read process identity, never command lines or environments."""
    pids = {entry.get('owner_pid') for entry in entries}
    pids = sorted(pid for pid in pids if isinstance(pid, int) and pid > 1)
    if not pids:
        return {}
    result = subprocess.run(
        ['/bin/ps', '-p', ','.join(map(str, pids)), '-o', 'pid=,uid=,tty=,lstart='],
        capture_output=True, text=True, timeout=2,
        env={**os.environ, 'LC_ALL': 'C'},
    )
    if result.returncode not in (0, 1) or (result.returncode and result.stderr.strip()):
        raise ValueError('Cannot verify terminal owners for live updates.')
    owners = {}
    for line in result.stdout.splitlines():
        pid, uid, tty, started = line.split(None, 3)
        owners[int(pid)] = (int(uid), '/dev/' + tty,
                            time.mktime(time.strptime(started.strip(), '%a %b %d %H:%M:%S %Y')))
    return owners


def owns_terminal(entry, owners):
    identity = owners.get(entry.get('owner_pid'))
    return bool(identity and identity[0] == os.getuid() and identity[1] == entry['tty']
                and identity[2] <= entry['created'])


def write_terminal(tty, sequence):
    """Send output only to a local, user-owned terminal. Never send input."""
    if not re.fullmatch(r'/dev/ttys[0-9]+', tty):
        raise ValueError('Not a local macOS terminal.')
    flags = os.O_WRONLY | os.O_NOCTTY | os.O_NONBLOCK | os.O_NOFOLLOW
    descriptor = os.open(tty, flags)
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISCHR(info.st_mode) or info.st_uid != os.getuid():
            raise ValueError('Terminal ownership changed.')
        payload = sequence.encode('ascii')
        if os.write(descriptor, payload) != len(payload):
            raise OSError('Incomplete terminal colour update.')
    finally:
        os.close(descriptor)


class Themes:
    def __init__(self, directory=DIRECTORY, resources=RESOURCES):
        self.directory = Path(directory)
        self.resources = Path(resources)
        self.config = self.directory / 'session-themes.conf'
        self.state_path = self.directory / 'session-themes-state.json'
        self.lock_path = self.directory / '.session-themes.lock'

    def configuration(self):
        parser = configparser.ConfigParser(interpolation=None, delimiters=('=',))
        parser.read_string(self.config.read_text(encoding='utf-8'))
        if set(parser.sections()) != {'settings', 'pairs'}:
            raise ValueError('Settings must contain [settings] and [pairs] sections.')
        settings = parser['settings']
        required = {'enabled', 'appearance', 'show_status'}
        if not required.issubset(settings) or set(settings) - required - {'live_updates'}:
            raise ValueError('[settings] needs enabled, appearance, show_status and optional live_updates.')
        settings.getboolean('live_updates', fallback=True)
        return parser

    def live_updates(self):
        return self.configuration()['settings'].getboolean('live_updates', fallback=True)

    def settings(self):
        parser = self.configuration()
        settings = parser['settings']
        enabled = settings.getboolean('enabled')
        show_status = settings.getboolean('show_status')
        mode = settings['appearance'].strip()
        if mode not in ('auto', 'light', 'dark'):
            raise ValueError('appearance must be auto, light or dark.')
        pairs = {}
        for family, value in parser['pairs'].items():
            if not re.fullmatch(r'[a-z0-9-]+', family):
                raise ValueError('Use lowercase letters, numbers and hyphens for family names.')
            names = [part.strip() for part in value.split('|')]
            if len(names) != 2 or not all(names):
                raise ValueError('Each pair needs Dark theme name | Light theme name: ' + family)
            pairs[family] = dict(zip(('dark', 'light'), names))
        if not pairs:
            raise ValueError('At least one light/dark pair is required.')
        return enabled, mode, show_status, pairs

    def read_state(self):
        if not self.state_path.exists():
            return {'counter': 0, 'sessions': {}}
        state = json.loads(self.state_path.read_text(encoding='utf-8'))
        if not isinstance(state.get('counter'), int) or not isinstance(state.get('sessions'), dict):
            raise ValueError('Invalid theme state; rename session-themes-state.json and reload.')
        return state

    def save_state(self, state):
        atomic_write(self.state_path, json.dumps(state, indent=2) + '\n')

    def set_setting(self, key, value):
        with locked(self.lock_path):
            text = self.config.read_text(encoding='utf-8')
            section = False
            lines = text.splitlines(keepends=True)
            for index, line in enumerate(lines):
                if line.strip().startswith('['):
                    section = line.strip() == '[settings]'
                if section and re.match(r'^\s*' + key + r'\s*=', line):
                    lines[index] = key + ' = ' + value + '\n'
                    atomic_write(self.config, ''.join(lines))
                    return
            raise ValueError('Missing setting: ' + key)

    def validate(self):
        _, _, _, pairs = self.settings()
        for mode in ('dark', 'light'):
            result = subprocess.run(
                [GHOSTTY, '+list-themes', '--plain', '--color=' + mode],
                text=True, capture_output=True, timeout=5, check=True,
            )
            names = {re.sub(r' \([^)]*\)$', '', line) for line in result.stdout.splitlines()}
            for pair in pairs.values():
                if pair[mode] not in names:
                    raise ValueError(pair[mode] + ' is not an installed ' + mode + ' theme.')
                theme_colours(pair[mode], self.resources)
        return len(pairs)

    @staticmethod
    def choose(state, pairs, previous=None):
        families = list(pairs)
        family = families[state['counter'] % len(families)]
        state['counter'] += 1
        if family == previous and len(families) > 1:
            family = families[state['counter'] % len(families)]
            state['counter'] += 1
        return family

    def render(self, entry, pairs, appearance):
        family = entry['family']
        if family is not None and family not in pairs:
            raise ValueError('This session\'s family was removed. Run session-theme default or next.')
        name = pairs[family][appearance] if family else 'default (Ghostty config)'
        sequence = colour_sequence(theme_colours(name, self.resources)) if family else RESET
        signature = hashlib.sha256(sequence.encode()).hexdigest()
        return sequence, dict(applied=signature, theme=name, appearance=appearance)

    def update(self, action, session_id, tty, appearance=None):
        enabled, mode, show_status, pairs = self.settings()
        appearance = appearance or (system_appearance() if mode == 'auto' else mode)
        with locked(self.lock_path):
            state = self.read_state()
            before = json.dumps(state, sort_keys=True)
            entry = state['sessions'].get(session_id)
            created = entry is None
            if created:
                # A UUID distinguishes new sessions even when macOS reuses a TTY.
                cutoff = time.time() - 30 * 86400
                state['sessions'] = {key: value for key, value in state['sessions'].items()
                                     if value['created'] >= cutoff or process_alive(value['owner_pid'])}
                entry = {'family': self.choose(state, pairs) if enabled and action != 'next' else None,
                         'tty': tty, 'created': time.time(), 'owner_pid': os.getppid(), 'applied': None}
                state['sessions'][session_id] = entry
            if entry['tty'] != tty:
                raise ValueError('Session belongs to another terminal; open a new Ghostty session.')
            if action == 'next':
                entry['family'] = self.choose(state, pairs, entry['family'])
            elif action == 'default':
                entry['family'] = None
            sequence, rendered = self.render(entry, pairs, appearance)
            force = action in ('_init', 'next', 'default')
            output = sequence if force or entry['applied'] != rendered['applied'] else ''
            entry.update(rendered)
            if json.dumps(state, sort_keys=True) != before:
                self.save_state(state)
            message = ''
            if (created and show_status) or action in ('next', 'default'):
                message = 'Session themes: ' + ('ON' if enabled else 'OFF') + ' · ' + rendered['theme']
            return output + (message + '\n' if message else '')

    def broadcast(self, appearance):
        """Apply one appearance event to live, assigned terminals under the state lock."""
        if appearance not in ('light', 'dark'):
            raise ValueError('Invalid appearance event.')
        _, mode, _, pairs = self.settings()
        appearance = appearance if mode == 'auto' else mode
        updated = failed = 0
        with locked(self.lock_path):
            state = self.read_state()
            before = json.dumps(state, sort_keys=True)
            # The most recent session on a TTY wins, including sessions on default.
            terminals = {}
            for entry in sorted(state['sessions'].values(), key=lambda item: item['created']):
                terminals[entry['tty']] = entry
            assigned = [entry for entry in terminals.values() if entry['family'] is not None]
            owners = terminal_owners(assigned)
            for entry in assigned:
                if not owns_terminal(entry, owners):
                    continue
                try:
                    sequence, rendered = self.render(entry, pairs, appearance)
                    write_terminal(entry['tty'], sequence)
                except (OSError, ValueError):
                    # Preserve the prompt fallback after a busy/closed terminal or bad theme.
                    entry['applied'] = None
                    failed += 1
                    continue
                entry.update(rendered)
                updated += 1
            if json.dumps(state, sort_keys=True) != before:
                self.save_state(state)
        return updated, failed

    def listener_running(self):
        try:
            stream = open(self.directory / '.session-themes-observer.lock', 'r')
        except FileNotFoundError:
            return False
        with stream:
            try:
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return True
            fcntl.flock(stream, fcntl.LOCK_UN)
        return False

    def ensure_listener(self):
        if self.live_updates() and not self.listener_running():
            subprocess.Popen([str(self.directory / 'session-themes-observer')],
                             stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL, start_new_session=True, close_fds=True)

    def broadcast_status(self, **values):
        atomic_write(self.directory / 'session-themes-listener-status.json',
                     json.dumps(dict(time=time.time(), **values), indent=2) + '\n')

    def status(self, session_id):
        enabled, mode, _, pairs = self.settings()
        state = self.read_state()
        entry = state['sessions'].get(session_id)
        current = entry['theme'] if entry else 'not assigned in this shell'
        live = 'OFF (prompt fallback only)'
        if self.live_updates():
            live = 'ON (' + ('listener running' if self.listener_running() else 'starts at next prompt') + ')'
        health = self.directory / 'session-themes-listener-status.json'
        if health.exists() and self.live_updates():
            health = json.loads(health.read_text(encoding='utf-8'))
            if health.get('error'):
                live += ' — ' + health['error']
        return '\n'.join((
            'New sessions: ' + ('ON' if enabled else 'OFF'),
            'Appearance: ' + mode,
            'Live updates: ' + live,
            'This session: ' + current,
            'Rotation: ' + ', '.join(pairs),
            'Settings: ' + str(self.config),
        ))


def current_terminal():
    if (os.environ.get('TERM_PROGRAM') != 'ghostty'
            or any(os.environ.get(key) for key in ('SSH_CONNECTION', 'TMUX', 'STY'))
            or not sys.stdin.isatty() or not sys.stdout.isatty()):
        return None
    tty = os.ttyname(sys.stdin.fileno())
    session_id = os.environ.get('GHOSTTY_SESSION_THEME_ID', '')
    if (os.environ.get('GHOSTTY_SESSION_THEME_TTY') != tty
            or not re.fullmatch(r'[A-Fa-f0-9-]{36}', session_id)):
        return None
    return session_id, tty


def main(arguments):
    os.umask(0o077)
    manager = Themes()
    action = arguments[0] if arguments else 'status'
    terminal = current_terminal()
    try:
        if action == '_broadcast':
            if not manager.live_updates():
                return 20
            if len(arguments) != 2:
                raise ValueError('Missing appearance event.')
            updated, failed = manager.broadcast(arguments[1])
            manager.broadcast_status(updated=updated, failed=failed,
                                     error=(str(failed) + ' terminal update(s) failed; prompt fallback remains active.') if failed else None)
        elif action == 'live':
            if len(arguments) != 2 or arguments[1] not in ('on', 'off'):
                raise ValueError('Usage: session-theme live on|off')
            manager.set_setting('live_updates', 'true' if arguments[1] == 'on' else 'false')
            manager.ensure_listener()
            print('Live updates: ' + arguments[1].upper() + '. Changes take effect within a few seconds.')
        elif action == 'mode':
            if len(arguments) != 2 or arguments[1] not in ('auto', 'light', 'dark'):
                raise ValueError('Usage: session-theme mode auto|light|dark')
            manager.set_setting('appearance', arguments[1])
            manager.ensure_listener()
            print('Appearance: ' + arguments[1] + '. Sessions update live, or at their next prompt when live updates are off.')
        elif len(arguments) > 1:
            raise ValueError('Unexpected arguments. Run session-theme help.')
        elif action in ('on', 'off'):
            if action == 'on':
                manager.validate()
            manager.set_setting('enabled', 'true' if action == 'on' else 'false')
            print('New sessions: ' + action.upper() + '. Existing sessions keep their choice.')
        elif action in ('_init', '_sync', 'next', 'default'):
            if not terminal:
                if action.startswith('_'):
                    return 0
                raise ValueError('Run this directly in an interactive Ghostty shell (without piping).')
            print(manager.update(action, *terminal), end='', flush=True)
            try:
                manager.ensure_listener()
            except OSError as error:
                manager.broadcast_status(error='Listener unavailable: ' + str(error))
        elif action == 'status':
            print(manager.status(terminal[0] if terminal else None))
        elif action == 'validate':
            print('Valid: ' + str(manager.validate()) + ' installed light/dark pairs.')
        elif action == 'config':
            print(manager.config)
        elif action in ('help', '--help', '-h'):
            print(HELP)
        else:
            raise ValueError('Unknown command. Run session-theme help.')
        return 0
    except (OSError, ValueError, KeyError, configparser.Error, subprocess.SubprocessError) as error:
        if action == '_broadcast':
            manager.broadcast_status(error=str(error))
            return 1
        if terminal and action in ('_init', '_sync', 'default'):
            print(RESET, end='', flush=True)
        print('Session themes: ' + str(error), file=sys.stderr)
        if action in ('_init', '_sync'):
            print('Using Ghostty default; fix settings, then run session-theme reload.', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
