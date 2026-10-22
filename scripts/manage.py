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
PAYLOAD = ('session-themes.py', 'session-themes.zsh', 'session-themes.bash', 'session-themes-observer',
           'session-theme', 'runtime.json')


def default_prefix():
    if sys.platform == 'linux':
        return Path(os.environ.get('XDG_DATA_HOME') or Path.home() / '.local/share') / 'ghostty-session-themes'
    return Path.home() / 'Library/Application Support/ghostty-session-themes'


def default_legacy():
    if sys.platform == 'linux':
        return Path(os.environ.get('XDG_CONFIG_HOME') or Path.home() / '.config') / 'ghostty'
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
        raise ValueError('Ambiguous Ghostty session themes block in shell configuration; fix its markers first.')
    return ''.join(lines[:starts[0]]) + replacement + ''.join(lines[ends[0] + 1:])


def hook(prefix, shell='zsh'):
    loader = shlex.quote(str(prefix / ('session-themes.' + shell)))
    source = '[[ -r ' + loader + ' ]] && source ' + loader
    if shell == 'bash':
        # A login profile may also be read by a POSIX shell such as dash.
        source = 'if [ -n "${BASH_VERSION:-}" ] && [ -r ' + loader + ' ]; then . ' + loader + '; fi'
    return (BEGIN + '\n# Controls: session-theme status | on | off | live on | live off\n'
            '# Settings: ' + str(prefix / 'session-themes.conf') + '\n'
            + source + '\n' + END + '\n')


def shell_configuration(args, runtime, *, allow_change=False):
    zshrc = getattr(args, 'zshrc', None)
    requested_shell = getattr(args, 'shell', None)
    if zshrc and requested_shell not in (None, 'zsh'):
        raise ValueError('--zshrc requires --shell zsh. Use --rc-file for Bash.')
    previous_shell = runtime.get('shell', 'zsh')
    shell = requested_shell or ('zsh' if zshrc else previous_shell if runtime else
                               Path(os.environ.get('SHELL') or 'zsh').name)
    if shell not in ('bash', 'zsh'):
        raise ValueError('Choose a supported shell with --shell bash or --shell zsh.')
    previous_files = runtime.get('rc_files') or ([runtime['zshrc']] if runtime.get('zshrc') else [])
    override = getattr(args, 'rc_file', None) or zshrc
    if override:
        files = [Path(override)]
    elif runtime and shell == previous_shell:
        files = [Path(path) for path in previous_files]
    elif shell == 'zsh':
        files = [Path(os.environ.get('ZDOTDIR') or Path.home()) / '.zshrc']
    else:
        files = [Path.home() / '.bashrc']
        profiles = [Path.home() / name for name in ('.bash_profile', '.bash_login', '.profile')]
        files.append(next((path for path in profiles if path.is_file()), profiles[0]))
    files = list(dict.fromkeys(path.expanduser().resolve() for path in files))
    changed = shell != previous_shell or list(map(str, files)) != previous_files
    if runtime and changed and not (allow_change and (args.prefix / '.disabled').exists()):
        raise ValueError('Uninstall the current shell integration before choosing another shell or startup file.')
    return shell, files


def discover_ghostty(override=None, resources_override=None):
    candidates = [override] if override else [shutil.which('ghostty'),
        '/Applications/Ghostty.app', Path.home() / 'Applications/Ghostty.app']
    for candidate in filter(None, candidates):
        # Preserve executable wrappers such as /snap/bin/ghostty -> /usr/bin/snap.
        binary = Path(candidate).expanduser().absolute()
        if binary.suffix == '.app':
            binary = binary / 'Contents/MacOS/ghostty'
        if not binary.is_file() or not os.access(binary, os.X_OK):
            continue
        if resources_override:
            resources = [Path(resources_override).expanduser()]
        elif sys.platform == 'linux':
            resources = []
            if os.environ.get('GHOSTTY_RESOURCES_DIR'):
                resources.append(Path(os.environ['GHOSTTY_RESOURCES_DIR']) / 'themes')
            resources.extend(path.parent.parent / 'share/ghostty/themes' for path in (binary, binary.resolve()))
            if binary == Path('/snap/bin/ghostty'):
                resources.append(Path('/snap/ghostty/current/share/ghostty/themes'))
            data_home = Path(os.environ.get('XDG_DATA_HOME') or Path.home() / '.local/share')
            resources.extend(path / 'ghostty/themes' for path in
                             [data_home] + [Path(p) for p in os.environ.get('XDG_DATA_DIRS', '/usr/local/share:/usr/share').split(':') if p])
        else:
            resources = [binary.resolve().parent.parent / 'Resources/ghostty/themes']
        for directory in resources:
            if directory.is_dir():
                return binary, directory.absolute()
    raise ValueError('Cannot find Ghostty and its themes. Use --ghostty /path/to/ghostty '
                     '(or /path/to/Ghostty.app on macOS) and --resources /path/to/ghostty/themes.')


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
    def __init__(self, prefix, action, rc_files, legacy=None):
        self.directory = prefix / 'backups' / (datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f') + '-' + action)
        self.directory.mkdir(parents=True, mode=0o700)
        self.manifest = dict(format=1, action=action, prefix=str(prefix), rc_files=list(map(str, rc_files)),
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
    for name in ('session-themes.py', 'session-themes.zsh', 'session-themes.bash'):
        shutil.copyfile(ROOT / 'src' / name, stage / name)
    (stage / 'runtime.json').write_text(json.dumps(runtime, indent=2) + '\n')
    (stage / 'session-themes.conf').write_text(configuration)
    (stage / 'session-theme').write_text(launcher(runtime['python'], prefix / 'session-themes.py'))
    if sys.platform == 'darwin':
        subprocess.run(['/usr/bin/xcrun', 'clang', '-fobjc-arc', '-Wall', '-Wextra', '-Werror',
                        '-framework', 'AppKit', '-o', str(stage / 'session-themes-observer'),
                        str(ROOT / 'src/session-themes-observer.m')], check=True, capture_output=True, text=True)
    else:
        (stage / 'session-themes-observer').write_text(
            '#!/bin/sh\nexec ' + shlex.quote(str(prefix / 'session-theme')) + ' _observe\n')
        settings = themes.Themes(stage).settings()
        if settings[1] == 'auto':
            themes.system_appearance()
    themes.Themes(stage).validate()


def install(args):
    prefix = args.prefix
    runtime = read_runtime(prefix)
    if not runtime and any((prefix / name).exists() for name in PAYLOAD):
        raise ValueError('Unrecognised files in the installation directory; choose a different --prefix.')
    shell, rc_files = shell_configuration(args, runtime, allow_change=True)
    legacy = args.legacy_dir
    if runtime or not all((legacy / name).is_file() for name in ('session-themes.py', 'session-themes.conf')):
        legacy = None
    if legacy == prefix:
        raise ValueError('Choose a new installation directory to migrate the legacy helper.')
    if legacy and '# Managed compatibility entry point.' in (legacy / 'session-themes.py').read_text():
        raise ValueError('The legacy helper was already migrated. Upgrade its existing --prefix instead.')
    if legacy and shell != 'zsh':
        raise ValueError('Migrate the legacy zsh helper with --shell zsh first, then uninstall before switching shells.')
    resources_override = getattr(args, 'resources', None) or runtime.get('resources_override')
    binary, resources = discover_ghostty(args.ghostty or runtime.get('ghostty'), resources_override)
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
    shell_texts = {path: replace_hook(path.read_text() if path.exists() else '', hook(prefix, shell))
                   for path in rc_files}
    unchanged = {path: digest(path) for path in [*rc_files, source_config, prefix / 'runtime.json']}
    runtime = dict(version=(ROOT / 'VERSION').read_text().strip(), python=str(Path(sys.executable).resolve()),
                   ghostty=str(binary), resources=str(resources), shell=shell, rc_files=list(map(str, rc_files)),
                   resources_override=str(resources) if resources_override else None,
                   legacy_dir=str(legacy) if legacy else runtime.get('legacy_dir'))
    with tempfile.TemporaryDirectory(prefix='ghostty-session-themes-build-') as temporary:
        stage = Path(temporary)
        prepare_payload(stage, prefix, runtime, configuration)
        print('Theme rotation validated; ' + ('AppKit observer compiled.' if sys.platform == 'darwin'
                                              else 'Linux observer prepared.'))
        print('Installation:', prefix)
        print('Shell integration (' + shell + '):', ', '.join(map(str, rc_files)))
        if legacy:
            print('Migrate existing helper:', legacy)
        if args.check:
            print('Check complete; no installed files were changed.')
            return
        prefix.mkdir(parents=True, exist_ok=True, mode=0o700)
        with themes.locked(prefix / '.install.lock'):
            if any(digest(path) != checksum for path, checksum in unchanged.items()):
                raise ValueError('Settings or shell configuration changed during preparation; run the installer again.')
            backup = Backup(prefix, 'install', rc_files, legacy)
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
                for path, text in shell_texts.items():
                    backup.write(path, text, stat.S_IMODE(path.stat().st_mode) if path.exists() else 0o600)
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
        print('Installed ' + runtime['version'] + '. Open a new Ghostty shell, or source '
              + shlex.quote(str(prefix / ('session-themes.' + shell))))


def uninstall(args):
    prefix = args.prefix
    runtime = read_runtime(prefix)
    if not runtime:
        raise ValueError('No installed runtime at ' + str(prefix))
    _, rc_files = shell_configuration(args, runtime)
    with themes.locked(prefix / '.install.lock'):
        backup = Backup(prefix, 'uninstall', rc_files)
        try:
            backup.write(prefix / '.disabled', 'Uninstalled; retained for already-open shells.\n')
            stop_listener(prefix)
            for path in rc_files:
                if path.exists():
                    backup.write(path, replace_hook(path.read_text(), ''), stat.S_IMODE(path.stat().st_mode))
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
        sub.add_argument('--shell', choices=('bash', 'zsh'), help='Shell to integrate (default: $SHELL, or previous installation)')
        target = sub.add_mutually_exclusive_group()
        target.add_argument('--rc-file', type=Path, help='Use one custom shell startup file')
        target.add_argument('--zshrc', type=Path, help='Compatibility alias for --shell zsh --rc-file')
        if command == 'install':
            sub.add_argument('--ghostty', type=Path, help='Ghostty .app bundle or executable')
            sub.add_argument('--resources', type=Path, help='Directory containing Ghostty theme files')
            sub.add_argument('--config', type=Path, help='Initial settings for a fresh installation')
            sub.add_argument('--legacy-dir', type=Path, default=default_legacy())
            sub.add_argument('--check', action='store_true', help='Build and validate without installing')
    sub = commands.add_parser('restore')
    sub.add_argument('backup', type=Path)
    args = parser.parse_args(argv)
    if sys.platform not in ('darwin', 'linux'):
        parser.error('The installer supports macOS and Linux only.')
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
