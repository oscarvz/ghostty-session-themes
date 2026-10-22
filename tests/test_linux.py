"""Linux regressions with synthetic resources and private pseudo terminals."""
import os
from pathlib import Path
import pty
import json
import re
import select
import shutil
import sys
import time
import subprocess
import unittest
from unittest.mock import patch

from support import load_themes, create_palettes
import test_installer

themes = load_themes()
installer = test_installer.installer


class LinuxAppearanceTests(unittest.TestCase):
    def test_portal_values_include_no_preference_and_unknown_values(self):
        for value, expected in ((0, 'light'), (1, 'dark'), (2, 'light'), (99, 'light')):
            for output in ('(<uint32 %d>,)\n', '(<<uint32 %d>>,)\n'):
                with self.subTest(value=value, output=output):
                    response = subprocess.CompletedProcess([], 0, output % value, '')
                    with patch.object(themes.sys, 'platform', 'linux'), patch.object(
                            themes.subprocess, 'run', return_value=response):
                        self.assertEqual(themes.system_appearance(), expected)

    def test_unavailable_or_invalid_portal_is_an_actionable_error(self):
        for result in (subprocess.CompletedProcess([], 1, '', 'No portal'),
                       subprocess.CompletedProcess([], 0, '(true,)', '')):
            with patch.object(themes.sys, 'platform', 'linux'), patch.object(
                    themes.subprocess, 'run', return_value=result):
                with self.assertRaisesRegex(ValueError, 'appearance.*light.*dark'):
                    themes.system_appearance()

    def test_missing_gdbus_and_timeouts_allow_explicit_modes(self):
        for error in (FileNotFoundError('gdbus'), subprocess.TimeoutExpired('gdbus', 2)):
            with patch.object(themes.sys, 'platform', 'linux'), patch.object(
                    themes.subprocess, 'run', side_effect=error):
                with self.assertRaisesRegex(ValueError, 'appearance.*light.*dark'):
                    themes.system_appearance()

    def test_linux_rejects_nonlocal_terminal_paths_before_opening(self):
        with patch.object(themes.sys, 'platform', 'linux'), patch.object(themes.os, 'open') as opening:
            for path in ('/dev/pts/1/extra', '/dev/pts/1\n', '/dev/pts/../1', '/dev/tty', '/tmp/file'):
                with self.subTest(path=path), self.assertRaises(ValueError):
                    themes.write_terminal(path, 'ignored')
            opening.assert_not_called()

    @unittest.skipUnless(os.uname().sysname == 'Linux', 'Linux pseudo terminals')
    def test_colour_output_reaches_only_a_private_linux_pty(self):
        master, slave = pty.openpty()
        self.addCleanup(os.close, master)
        self.addCleanup(os.close, slave)
        with patch.object(themes.sys, 'platform', 'linux'):
            themes.write_terminal(os.ttyname(slave), '\x1b]11;#123456\x1b\\')
        self.assertEqual(os.read(master, 100), b'\x1b]11;#123456\x1b\\')


class LinuxInstallerTests(test_installer.InstallerTests):
    def setUp(self):
        super().setUp()
        patch.object(installer.sys, 'platform', 'linux').start()
        self.ghostty = self.directory / 'local/bin/ghostty'
        self.ghostty.parent.mkdir(parents=True)
        pairs = create_palettes(self.directory / 'local/share/ghostty/themes')
        self.ghostty.write_text('#!/usr/bin/env python3\nimport sys\npairs = ' + repr(pairs)
                               + '\nprint("\\n".join(pairs[sys.argv[-1].split("=")[-1]]))\n')
        self.ghostty.chmod(0o700)
        self.args.ghostty = self.ghostty
        tools = self.directory / 'tools'
        tools.mkdir()
        gdbus = tools / 'gdbus'
        gdbus.write_text('#!/bin/sh\nprintf "(<<uint32 1>>,)\\n"\n')
        gdbus.chmod(0o700)
        patch.dict(os.environ, {'PATH': str(tools) + os.pathsep + os.environ['PATH']}).start()
        patch.dict(os.environ, {'GHOSTTY_RESOURCES_DIR': str(self.directory / 'local/share/ghostty')}).start()

    def test_xdg_install_directory_and_environment_resources(self):
        with patch.dict(os.environ, {'XDG_DATA_HOME': str(self.directory / 'data')}):
            self.assertEqual(installer.default_prefix(), self.directory / 'data/ghostty-session-themes')
        custom = self.directory / 'custom-resources'
        create_palettes(custom / 'themes')
        with patch.dict(os.environ, {'GHOSTTY_RESOURCES_DIR': str(custom)}):
            self.assertEqual(installer.discover_ghostty(self.ghostty)[1], custom / 'themes')

    def test_explicit_resources_for_nonstandard_packages(self):
        custom = self.directory / 'custom-themes'
        create_palettes(custom)
        self.args.resources = custom
        self.install()
        self.assertEqual(installer.read_runtime(self.prefix)['resources'], str(custom))
        self.args.resources = None
        self.install()
        self.assertEqual(installer.read_runtime(self.prefix)['resources'], str(custom))

    def test_upgrade_rediscovers_resources_for_a_replacement_ghostty(self):
        with patch.dict(os.environ, {'GHOSTTY_RESOURCES_DIR': ''}):
            self.install()
            replacement = self.directory / 'replacement/bin/ghostty'
            replacement.parent.mkdir(parents=True)
            shutil.copy2(self.ghostty, replacement)
            resources = self.directory / 'replacement/share/ghostty/themes'
            create_palettes(resources)
            self.args.ghostty = replacement
            self.install()
        self.assertEqual(installer.read_runtime(self.prefix)['resources'], str(resources))

    def test_pinned_install_works_without_gdbus(self):
        custom = self.directory / 'pinned.conf'
        custom.write_text(test_installer.CONFIG.read_text().replace('appearance = auto', 'appearance = dark'))
        self.args.config = custom
        (self.directory / 'tools/gdbus').write_text('#!/bin/sh\nexit 99\n')
        self.install()
        self.assertIn('appearance = dark', (self.prefix / 'session-themes.conf').read_text())

    @unittest.skipUnless(shutil.which('zsh'), 'zsh is needed for shell integration')
    def test_zsh_assigns_distinct_sessions_and_inherits_in_nested_shells(self):
        self.install()
        manager = installer.themes.Themes(self.prefix)
        manager.set_setting('appearance', 'dark')
        manager.set_setting('live_updates', 'false')
        environment = {key: value for key, value in os.environ.items() if key not in
                       ('SSH_CONNECTION', 'TMUX', 'STY', 'GHOSTTY_SESSION_THEME_ID', 'GHOSTTY_SESSION_THEME_TTY')}
        environment['TERM_PROGRAM'] = 'ghostty'
        identifiers = []
        for _ in range(2):
            master, slave = pty.openpty()
            try:
                command = ('source "$1"; print -r -- "OUTER:$GHOSTTY_SESSION_THEME_ID"; '
                           '"$2" -fic \'source "$1"; print -r -- "INNER:$GHOSTTY_SESSION_THEME_ID"\' nested "$1"')
                zsh = shutil.which('zsh')
                process = subprocess.Popen([zsh, '-fic', command, 'outer',
                    str(self.prefix / 'session-themes.zsh'), zsh],
                    stdin=slave, stdout=slave, stderr=slave, env=environment)
                self.assertEqual(process.wait(timeout=5), 0)
                output = b''
                while select.select([master], [], [], 0)[0]:
                    output += os.read(master, 4096)
                outer = re.search(rb'OUTER:([a-f0-9-]{36})', output)
                inner = re.search(rb'INNER:([a-f0-9-]{36})', output)
                self.assertIsNotNone(outer, output)
                self.assertIsNotNone(inner, output)
                self.assertEqual(outer[1], inner[1])
                identifiers.append(outer[1])
            finally:
                os.close(master)
                os.close(slave)
        self.assertNotEqual(*identifiers)
        self.assertEqual(manager.read_state()['counter'], 2)

    def test_linux_executable_symlink_keeps_its_invocation_name(self):
        wrapper = self.directory / 'wrapped-ghostty'
        wrapper.symlink_to(self.ghostty)
        with patch.dict(os.environ, {'GHOSTTY_RESOURCES_DIR': str(self.directory / 'local/share/ghostty')}):
            self.assertEqual(installer.discover_ghostty(wrapper)[0], wrapper)

    def test_invalid_theme_aborts_before_modifying_shell_or_installation(self):
        (self.directory / 'local/share/ghostty/themes/Rose Pine Dawn').unlink()
        with self.assertRaises(FileNotFoundError):
            self.install()
        self.assertEqual(self.zshrc.read_bytes(), self.original_shell)
        self.assertFalse(self.prefix.exists())

    @unittest.skipUnless(os.uname().sysname == 'Linux', 'Linux observer')
    def test_observer_handles_portal_events_pinning_singleton_and_shutdown(self):
        self.install()
        master, slave = pty.openpty()
        self.addCleanup(os.close, master)
        self.addCleanup(os.close, slave)
        owner = subprocess.Popen([sys.executable, '-c',
            'import fcntl, termios, time; fcntl.ioctl(0, termios.TIOCSCTTY, 0); '
            'print("ready", flush=True); time.sleep(30)'],
            stdin=slave, stdout=subprocess.PIPE, start_new_session=True)
        def stop_owner():
            owner.terminate()
            owner.wait(timeout=5)
            owner.stdout.close()
        self.addCleanup(stop_owner)
        self.assertEqual(owner.stdout.readline(), b'ready\n')
        manager = installer.themes.Themes(self.prefix)
        manager.update('_init', 'one', os.ttyname(slave), appearance='dark')
        state = manager.read_state()
        state['sessions']['one']['owner_pid'] = owner.pid
        manager.save_state(state)
        appearance = self.directory / 'appearance'
        appearance.write_text('1')
        gdbus = self.directory / 'tools/gdbus'
        gdbus.write_text('#!' + sys.executable + '\n'
            'import pathlib, sys, time\n'
            'path = pathlib.Path(' + repr(str(appearance)) + ')\n'
            'if sys.argv[1] == "call":\n'
            '    print("(<<uint32 " + path.read_text() + ">>,)")\n'
            'else:\n'
            '    previous = None\n'
            '    while True:\n'
            '        value = path.read_text()\n'
            '        if value != previous:\n'
            '            print("/org/freedesktop/portal/desktop: org.freedesktop.portal.Settings.SettingChanged '
            '(\\\'org.freedesktop.appearance\\\', \\\'color-scheme\\\', <uint32 " + value + ">)", flush=True)\n'
            '            previous = value\n'
            '        time.sleep(0.05)\n')
        process = subprocess.Popen([str(self.prefix / 'session-themes-observer')])
        def stop():
            (self.prefix / '.disabled').touch()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.terminate()
                process.wait(timeout=5)
        self.addCleanup(stop)
        status = self.prefix / 'session-themes-listener-status.json'
        def wait_mode(mode):
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                if status.exists() and json.loads(status.read_text()).get('appearance') == mode:
                    return
                if process.poll() is not None:
                    self.fail('Observer exited before applying ' + mode)
                time.sleep(0.05)
            self.fail('Observer did not apply ' + mode)
        wait_mode('dark')
        self.assertIn(b'\x1b]11;', os.read(master, 4096))
        duplicate = subprocess.run([str(self.prefix / 'session-themes-observer')], timeout=3)
        self.assertEqual(duplicate.returncode, 0)
        appearance.write_text('2')
        wait_mode('light')
        self.assertEqual(manager.read_state()['sessions']['one']['theme'], 'Rose Pine Dawn')
        self.assertIn(b'\x1b]11;#faf4ed', os.read(master, 4096))
        self.assertEqual(manager.read_state()['counter'], 1)
        manager.set_setting('appearance', 'dark')
        wait_mode('dark')
        manager.set_setting('live_updates', 'false')
        self.assertEqual(process.wait(timeout=5), 0)
        self.assertFalse(manager.listener_running())


if __name__ == '__main__':
    unittest.main()
