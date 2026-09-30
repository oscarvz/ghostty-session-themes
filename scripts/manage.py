#!/usr/bin/env python3
"""Install, remove, or restore a per-user Ghostty session-themes installation."""
import argparse
import configparser
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shlex
import shutil
import stat
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location('session_themes', ROOT / 'src/session-themes.py')
themes = importlib.util.module_from_spec(spec)
spec.loader.exec_module(themes)
BEGIN = '# >>> Ghostty session themes >>>'
END = '# <<< Ghostty session themes <<<'
PAYLOAD = ('session-themes.py', 'session-themes.zsh', 'session-themes-observer',
           'session-theme', 'runtime.json')


def default_prefix():
    return Path.home() / 'Library/Application Support/ghostty-session-themes'


def default_legacy():
    return Path.home() / 'Library/Application Support/com.mitchellh.ghostty'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None


def atomic_bytes(path, data, mode=0o600):
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix='.' + path.name, dir=path.parent)
    try:
        with os.fdopen(descriptor, 'wb') as output:
            output.write(data)
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def replace_hook(text, replacement):
    lines = text.splitlines(keepends=True)
    starts = [i for i, line in enumerate(lines) if line.strip() == BEGIN]
    ends = [i for i, line in enumerate(lines) if line.strip() == END]
    if not starts and not ends:
        return text + ('\n' if text and not text.endswith('\n') else '') + replacement
    if len(starts) != 1 or len(ends) != 1 or starts[0] >= ends[0]:
        raise ValueError('Ambiguous Ghostty session themes block in zshrc; fix its markers first.')
    return ''.join(lines[:starts[0]]) + replacement + ''.join(lines[ends[0] + 1:])


def hook(prefix):
    loader = shlex.quote(str(prefix / 'session-themes.zsh'))
    return (BEGIN + '\n# Controls: session-theme status | on | off | live on | live off\n'
            '# Settings: ' + str(prefix / 'session-themes.conf') + '\n'
            '[[ -r ' + loader + ' ]] && source ' + loader + '\n' + END + '\n')


def discover_ghostty(override=None):
    candidates = [override] if override else [shutil.which('ghostty'),
        '/Applications/Ghostty.app', Path.home() / 'Applications/Ghostty.app']
    for candidate in filter(None, candidates):
        binary = Path(candidate).expanduser().resolve()
        if binary.suffix == '.app':
            binary = binary / 'Contents/MacOS/ghostty'
        resources = binary.parent.parent / 'Resources/ghostty/themes'
        if binary.is_file() and os.access(binary, os.X_OK) and resources.is_dir():
            return binary, resources
    raise ValueError('Cannot find a Ghostty macOS app bundle. Use --ghostty /path/to/Ghostty.app.')


def read_runtime(prefix):
    path = prefix / 'runtime.json'
    return json.loads(path.read_text()) if path.exists() else {}


def stop_listener(prefix):
    manager = themes.Themes(prefix)
    deadline = time.monotonic() + 8
    while manager.listener_running():
        if time.monotonic() >= deadline:
            raise ValueError('Observer did not stop; installation was not replaced. Retry after it exits.')
        time.sleep(0.1)


class Backup:
    """Journal exactly the files we change; leave unrelated shell edits alone."""
    def __init__(self, prefix, action, zshrc, legacy=None):
        self.directory = prefix / 'backups' / (datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f') + '-' + action)
        self.directory.mkdir(parents=True, mode=0o700)
        self.manifest = dict(format=1, action=action, prefix=str(prefix), zshrc=str(zshrc),
                             legacy=str(legacy) if legacy else None,
                             installed_before=(prefix / 'runtime.json').exists(), files={})
        self.flush()

    def flush(self):
        themes.atomic_write(self.directory / 'manifest.json', json.dumps(self.manifest, indent=2) + '\n')

    def snapshot(self, path, *, managed=False):
        key = str(path)
        if managed and path.is_symlink():
            raise ValueError('Refusing to replace a symlink in the installation: ' + str(path))
        if key in self.manifest['files']:
            self.manifest['files'][key]['managed'] |= managed
            return
        entry = dict(before=digest(path), after=digest(path), managed=managed,
                     mode=stat.S_IMODE(path.stat().st_mode) if path.exists() else 0o600)
        if path.exists():
            entry['copy'] = str(len(self.manifest['files'])) + '-' + path.name
            shutil.copyfile(path, self.directory / entry['copy'])
            os.chmod(self.directory / entry['copy'], 0o600)
        self.manifest['files'][key] = entry
        self.flush()

    def write(self, path, data, mode=0o600):
        self.snapshot(path, managed=True)
        atomic_bytes(path, data.encode() if isinstance(data, str) else data, mode)
        self.manifest['files'][str(path)]['after'] = digest(path)
        self.flush()

    def remove(self, path):
        self.snapshot(path, managed=True)
        path.unlink(missing_ok=True)
        self.manifest['files'][str(path)]['after'] = None
        self.flush()

    def undo(self):
        for name, entry in reversed(list(self.manifest['files'].items())):
            if not entry['managed']:
                continue
            path = Path(name)
            if digest(path) != entry['after']:
                raise ValueError('File edited during installation; restore it manually from ' + str(self.directory))
            if entry['before'] is None:
                path.unlink(missing_ok=True)
            else:
                atomic_bytes(path, (self.directory / entry['copy']).read_bytes(), entry['mode'])


def ghostty_configs():
    xdg = Path(os.environ.get('XDG_CONFIG_HOME', str(Path.home() / '.config')))
    return [directory / name for directory in (xdg / 'ghostty', default_legacy())
            for name in ('config.ghostty', 'config') if (directory / name).is_file()]


def launcher(python, helper):
    return '#!/bin/sh\nexec ' + shlex.quote(str(python)) + ' ' + shlex.quote(str(helper)) + ' "$@"\n'


def prepare_payload(stage, prefix, runtime, configuration):
    for name in ('session-themes.py', 'session-themes.zsh'):
        shutil.copyfile(ROOT / 'src' / name, stage / name)
    (stage / 'runtime.json').write_text(json.dumps(runtime, indent=2) + '\n')
    (stage / 'session-themes.conf').write_text(configuration)
    (stage / 'session-theme').write_text(launcher(runtime['python'], prefix / 'session-themes.py'))
    subprocess.run(['/usr/bin/xcrun', 'clang', '-fobjc-arc', '-Wall', '-Wextra', '-Werror',
                    '-framework', 'AppKit', '-o', str(stage / 'session-themes-observer'),
                    str(ROOT / 'src/session-themes-observer.m')], check=True, capture_output=True, text=True)
    themes.Themes(stage).validate()


def install(args):
    prefix = args.prefix
    runtime = read_runtime(prefix)
    if not runtime and any((prefix / name).exists() for name in PAYLOAD):
        raise ValueError('Unrecognised files in the installation directory; choose a different --prefix.')
    zshrc = args.zshrc or (Path(runtime['zshrc']) if runtime else None)
    if zshrc is None:
        zshrc = Path(os.environ.get('ZDOTDIR', str(Path.home()))) / '.zshrc'
    zshrc = zshrc.expanduser().resolve()
    if runtime and zshrc != Path(runtime['zshrc']):
        raise ValueError('Uninstall the current shell integration before choosing a different --zshrc.')
    legacy = args.legacy_dir
    if runtime or not all((legacy / name).is_file() for name in ('session-themes.py', 'session-themes.conf')):
        legacy = None
    if legacy == prefix:
        raise ValueError('Choose a new installation directory to migrate the legacy helper.')
    if legacy and '# Managed compatibility entry point.' in (legacy / 'session-themes.py').read_text():
        raise ValueError('The legacy helper was already migrated. Upgrade its existing --prefix instead.')
    binary, resources = discover_ghostty(args.ghostty or runtime.get('ghostty'))
    config_path = prefix / 'session-themes.conf'
    if config_path.exists() and args.config:
        raise ValueError('Existing settings are preserved. Edit them with session-theme config instead of --config.')
    source_config = config_path if config_path.exists() else (
        args.config or (legacy / 'session-themes.conf' if legacy else ROOT / 'config/session-themes.conf'))
    configuration = source_config.read_text()
    parser = configparser.ConfigParser(interpolation=None, delimiters=('=',))
    parser.read_string(configuration)
    if not parser.has_option('settings', 'live_updates'):
        configuration = configuration.replace('[settings]', '[settings]\nlive_updates = true', 1)
    shell_text = zshrc.read_text() if zshrc.exists() else ''
    new_shell_text = replace_hook(shell_text, hook(prefix))
    unchanged = {path: digest(path) for path in (zshrc, source_config, prefix / 'runtime.json')}
    runtime = dict(version=(ROOT / 'VERSION').read_text().strip(), python=str(Path(sys.executable).resolve()),
                   ghostty=str(binary), resources=str(resources), zshrc=str(zshrc),
                   legacy_dir=str(legacy) if legacy else runtime.get('legacy_dir'))
    with tempfile.TemporaryDirectory(prefix='ghostty-session-themes-build-') as temporary:
        stage = Path(temporary)
        prepare_payload(stage, prefix, runtime, configuration)
        print('Theme rotation validated; observer compiled successfully.')
        print('Installation:', prefix)
        print('Shell integration:', zshrc)
        if legacy:
            print('Migrate existing helper:', legacy)
        if args.check:
            print('Check complete; no installed files were changed.')
            return
        prefix.mkdir(parents=True, exist_ok=True, mode=0o700)
        with themes.locked(prefix / '.install.lock'):
            if any(digest(path) != checksum for path, checksum in unchanged.items()):
                raise ValueError('Settings or shell configuration changed during preparation; run the installer again.')
            backup = Backup(prefix, 'install', zshrc, legacy)
            for path in ghostty_configs():
                backup.snapshot(path)
            backup.snapshot(prefix / 'session-themes-state.json')
            try:
                backup.write(prefix / '.disabled', 'Installation in progress\n')
                stop_listener(prefix)
                if legacy:
                    old = themes.Themes(legacy)
                    with themes.locked(old.lock_path):
                        if old.live_updates() and (legacy / 'session-themes-observer').exists():
                            backup.write(old.config.resolve(), themes.setting_text(old.config.read_text(), 'live_updates', 'false'))
                    stop_listener(legacy)
                    with themes.locked(old.lock_path):
                        backup.snapshot(old.state_path)
                        if old.state_path.exists() and not (prefix / old.state_path.name).exists():
                            atomic_bytes(prefix / old.state_path.name, old.state_path.read_bytes())
                for name in PAYLOAD:
                    mode = 0o700 if name in ('session-theme', 'session-themes-observer') else 0o600
                    backup.write(prefix / name, (stage / name).read_bytes(), mode)
                if not config_path.exists():
                    backup.write(config_path, configuration)
                backup.write(zshrc, new_shell_text, stat.S_IMODE(zshrc.stat().st_mode) if zshrc.exists() else 0o600)
                if legacy:
                    # Old shells already hold the legacy helper path; forward them without a restart.
                    forward = ('#!/usr/bin/env python3\n# Managed compatibility entry point.\n'
                               'import os, sys\nos.execv(' + repr(str(prefix / 'session-theme')) + ', ['
                               + repr(str(prefix / 'session-theme')) + '] + sys.argv[1:])\n')
                    backup.write(legacy / 'session-themes.py', forward)
                    backup.write(legacy / 'session-themes.zsh', 'source ' + shlex.quote(str(prefix / 'session-themes.zsh')) + '\n')
                backup.remove(prefix / '.disabled')
            except Exception:
                backup.undo()
                for directory in (prefix, legacy):
                    if directory and (directory / 'session-themes.conf').exists():
                        themes.Themes(directory).ensure_listener()
                raise
        themes.Themes(prefix).ensure_listener()
        print('Backup:', backup.directory)
        print('Installed ' + runtime['version'] + '. Open a new Ghostty shell, or source ' + shlex.quote(str(prefix / 'session-themes.zsh')))


def uninstall(args):
    prefix = args.prefix
    runtime = read_runtime(prefix)
    if not runtime:
        raise ValueError('No installed runtime at ' + str(prefix))
    zshrc = (args.zshrc or Path(runtime['zshrc'])).expanduser().resolve()
    with themes.locked(prefix / '.install.lock'):
        backup = Backup(prefix, 'uninstall', zshrc)
        try:
            backup.write(prefix / '.disabled', 'Uninstalled; retained for already-open shells.\n')
            stop_listener(prefix)
            if zshrc.exists():
                backup.write(zshrc, replace_hook(zshrc.read_text(), ''), stat.S_IMODE(zshrc.stat().st_mode))
        except Exception:
            backup.undo()
            themes.Themes(prefix).ensure_listener()
            raise
    print('Integration removed; observer stopped. Settings, files and backups retained at', prefix)
    print('Already-open shells restore native colours at their next prompt. Open a new shell to unload the hook.')
    print('Backup:', backup.directory)


def restore(args):
    directory = args.backup.expanduser().resolve()
    manifest = json.loads((directory / 'manifest.json').read_text())
    if manifest.get('format') != 1:
        raise ValueError('Unsupported backup format.')
    prefix = Path(manifest['prefix'])
    with themes.locked(prefix / '.install.lock'):
        for name, entry in manifest['files'].items():
            if entry.get('copy') and digest(directory / entry['copy']) != entry['before']:
                raise ValueError('Backup checksum mismatch: ' + name)
            if entry['managed'] and digest(Path(name)) != entry['after']:
                raise ValueError('File changed since this backup; refusing to overwrite: ' + name)
        themes.atomic_write(prefix / '.disabled', 'Restore in progress\n')
        stop_listener(prefix)
        for name, entry in reversed(list(manifest['files'].items())):
            path = Path(name)
            if not entry['managed'] or path == prefix / '.disabled':
                continue
            if entry['before'] is not None:
                atomic_bytes(path, (directory / entry['copy']).read_bytes(), entry['mode'])
            elif manifest['installed_before'] or prefix not in path.parents:
                path.unlink(missing_ok=True)
            # A fresh-install rollback retains a disabled copy for already-open shells.
        previous_disabled = manifest['files'].get(str(prefix / '.disabled'), {})
        if manifest['installed_before'] and previous_disabled.get('before') is None:
            (prefix / '.disabled').unlink(missing_ok=True)
            themes.Themes(prefix).ensure_listener()
        if manifest.get('legacy'):
            themes.Themes(manifest['legacy']).ensure_listener()
    print('Restored managed files; personal session state was retained.')


def main(argv=None):
    if sys.version_info < (3, 9):
        raise SystemExit('Python 3.9 or newer is required.')
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    for command in ('install', 'uninstall'):
        sub = commands.add_parser(command)
        sub.add_argument('--prefix', type=Path, default=default_prefix())
        sub.add_argument('--zshrc', type=Path)
        if command == 'install':
            sub.add_argument('--ghostty', type=Path, help='Ghostty .app bundle or executable')
            sub.add_argument('--config', type=Path, help='Initial settings for a fresh installation')
            sub.add_argument('--legacy-dir', type=Path, default=default_legacy())
            sub.add_argument('--check', action='store_true', help='Build and validate without installing')
    sub = commands.add_parser('restore')
    sub.add_argument('backup', type=Path)
    args = parser.parse_args(argv)
    if sys.platform != 'darwin':
        parser.error('The installer supports macOS only.')
    if hasattr(args, 'prefix'):
        args.prefix = args.prefix.expanduser().resolve()
    if getattr(args, 'legacy_dir', None):
        args.legacy_dir = args.legacy_dir.expanduser().resolve()
    if getattr(args, 'config', None):
        args.config = args.config.expanduser().resolve()
    try:
        dict(install=install, uninstall=uninstall, restore=restore)[args.command](args)
    except (OSError, ValueError, configparser.Error, subprocess.SubprocessError) as error:
        print('Session themes: ' + str(error), file=sys.stderr)
        if isinstance(error, subprocess.CalledProcessError) and error.stderr:
            print(error.stderr, file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
