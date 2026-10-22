"""Bash integration against real shells and synthetic Ghostty resources."""
import json
import os
import pty
import re
import select
import shutil
import subprocess
import unittest
from unittest.mock import patch

import test_installer

installer = test_installer.installer
BASH = os.environ.get('BASH_TEST_BINARY') or shutil.which('bash')


class BashInstallerTests(test_installer.InstallerTests):
    def setUp(self):
        super().setUp()
        self.args.shell = 'bash'
        self.args.rc_file = self.zshrc
        self.args.zshrc = None
        patch.object(installer.Path, 'home', return_value=self.directory).start()
        patch.dict(os.environ, {'ZDOTDIR': str(self.directory)}).start()

    def test_default_bash_install_covers_login_and_interactive_startup(self):
        self.args.rc_file = None
        profile = self.directory / '.profile'
        profile.write_text('# existing login settings\n')
        with patch.object(installer.Path, 'home', return_value=self.directory), patch.dict(
                os.environ, {'SHELL': '/bin/bash'}):
            self.install()
        for path in (self.directory / '.bashrc', profile):
            self.assertIn('session-themes.bash', path.read_text())
        self.assertTrue(profile.read_text().startswith('# existing login settings\n'))
        self.args.shell = None
        with patch.dict(os.environ, {'SHELL': '/bin/zsh'}):
            self.install()
        self.assertEqual(installer.read_runtime(self.prefix)['shell'], 'bash')
        installer.uninstall(self.args)
        self.assertEqual(profile.read_text(), '# existing login settings\n')

    def test_selected_shell_is_reported_and_upgrade_keeps_bash(self):
        self.install()
        self.assertIn('session-themes.bash', self.zshrc.read_text())
        self.assertEqual(installer.read_runtime(self.prefix)['shell'], 'bash')
        self.args.shell = None
        self.install()
        self.assertEqual(self.zshrc.read_text().count(installer.BEGIN), 1)

    def test_custom_initial_config_and_symlinked_zshrc(self):
        custom = self.directory / 'custom.ini'
        custom.write_text(test_installer.CONFIG.read_text().replace('show_status = true', 'show_status = false'))
        link = self.directory / 'bashrc-link'
        link.symlink_to(self.zshrc)
        self.args.rc_file = link
        self.args.config = custom
        self.install()
        self.assertTrue(link.is_symlink())
        self.assertIn('show_status = false', (self.prefix / 'session-themes.conf').read_text())
        self.assertIn('session-themes.bash', self.zshrc.read_text())

    def test_existing_zsh_runtime_without_shell_metadata_stays_zsh(self):
        self.args.shell = 'zsh'
        self.install()
        path = self.prefix / 'runtime.json'
        runtime = json.loads(path.read_text())
        runtime.pop('shell')
        runtime.pop('rc_files')
        runtime['zshrc'] = str(self.zshrc)
        path.write_text(json.dumps(runtime))
        self.args.shell = None
        with patch.dict(os.environ, {'SHELL': '/bin/bash'}):
            self.install()
        self.assertEqual(installer.read_runtime(self.prefix)['shell'], 'zsh')

    def test_both_startup_files_are_restored_after_uninstall(self):
        self.args.rc_file = None
        self.install()
        installer.uninstall(self.args)
        installer.restore(type(self.args)(backup=self.latest_backup()))
        for name in ('.bashrc', '.bash_profile'):
            self.assertEqual((self.directory / name).read_text().count(installer.BEGIN), 1)

    def test_second_startup_file_failure_restores_the_first(self):
        self.args.rc_file = None
        rc_file = self.directory / '.bashrc'
        rc_file.write_text('# retained Bash configuration\n')
        original = installer.Backup.write
        def fail_on_profile(backup, path, data, mode=0o600):
            if path == self.directory / '.bash_profile':
                raise OSError('simulated profile write failure')
            return original(backup, path, data, mode)
        with patch.object(installer.Backup, 'write', fail_on_profile):
            with self.assertRaisesRegex(OSError, 'simulated profile'):
                self.install()
        self.assertEqual(rc_file.read_text(), '# retained Bash configuration\n')

    def test_switching_shell_requires_uninstall_and_preserves_settings(self):
        self.install()
        self.args.shell = 'zsh'
        with self.assertRaisesRegex(ValueError, 'Uninstall'):
            self.install()
        self.args.shell = None
        installer.uninstall(self.args)
        self.args.shell = 'zsh'
        self.install()
        self.assertIn('session-themes.zsh', self.zshrc.read_text())

    def test_uninstall_cannot_target_another_shell_after_disabling(self):
        self.install()
        installer.uninstall(self.args)
        self.args.shell = 'zsh'
        with self.assertRaisesRegex(ValueError, 'Uninstall'):
            installer.uninstall(self.args)

    # This case specifically exercises the zsh-only legacy migration path.
    def test_legacy_migration_keeps_assignments_and_forwards_existing_shells(self):
        self.args.shell = 'zsh'
        super().test_legacy_migration_keeps_assignments_and_forwards_existing_shells()

    @unittest.skipUnless(BASH, 'Bash is required')
    def run_bash(self, commands, *, ghostty=True, interactive=True):
        environment = {key: value for key, value in os.environ.items() if key not in
                       ('SSH_CONNECTION', 'TMUX', 'STY', 'GHOSTTY_SESSION_THEME_ID',
                        'GHOSTTY_SESSION_THEME_TTY', 'PROMPT_COMMAND', 'BASH_ENV', 'ENV')}
        environment['TERM_PROGRAM'] = 'ghostty' if ghostty else 'other'
        master, slave = pty.openpty()
        try:
            process = subprocess.Popen([BASH, '--noprofile', '--norc'] + (['-i'] if interactive else [])
                + ['-c', commands, 'test', str(self.prefix / 'session-themes.bash'), BASH],
                stdin=slave, stdout=slave, stderr=slave, env=environment)
            try:
                result = process.wait(timeout=5)
            finally:
                if process.poll() is None:
                    process.terminate()
                    process.wait(timeout=5)
            output = b''
            while select.select([master], [], [], 0)[0]:
                output += os.read(master, 8192)
            self.assertEqual(result, 0, output)
            return output
        finally:
            os.close(master)
            os.close(slave)

    def prepare_shell(self):
        self.install()
        manager = installer.themes.Themes(self.prefix)
        manager.set_setting('appearance', 'dark')
        manager.set_setting('live_updates', 'false')
        return manager

    def test_bash_assigns_distinct_sessions_and_inherits_nested_identity(self):
        manager = self.prepare_shell()
        identifiers = []
        for _ in range(2):
            output = self.run_bash('source "$1"; printf "OUTER:%s\\n" "$GHOSTTY_SESSION_THEME_ID"; '
                '"$2" --noprofile --norc -ic \'source "$1"; printf "INNER:%s\\n" "$GHOSTTY_SESSION_THEME_ID"\' nested "$1"')
            outer = re.search(rb'OUTER:([a-f0-9-]{36})', output)
            inner = re.search(rb'INNER:([a-f0-9-]{36})', output)
            self.assertIsNotNone(outer, output)
            self.assertIsNotNone(inner, output)
            self.assertEqual(outer[1], inner[1])
            identifiers.append(outer[1])
        self.assertNotEqual(*identifiers)
        self.assertEqual(manager.read_state()['counter'], 2)

    def test_scalar_prompt_commands_and_exit_status_survive_repeated_sourcing(self):
        manager = self.prepare_shell()
        output = self.run_bash('PROMPT_COMMAND=\'printf "EXISTING:%s\\n" "$?" # trailing comment\'; '
            'source "$1"; source "$1"; false; eval "$PROMPT_COMMAND"; '
            'false; _ghostty_session_theme_precmd; printf "STATUS:%s\\n" "$?"; session-theme next')
        self.assertEqual(output.count(b'EXISTING:'), 1, output)
        self.assertIn(b'EXISTING:1', output)
        self.assertIn(b'STATUS:1', output)
        self.assertEqual(manager.read_state()['sessions'].popitem()[1]['family'], 'catppuccin')

    def test_array_prompt_commands_are_preserved(self):
        version = subprocess.check_output([BASH, '-c', 'printf "%s.%s" "${BASH_VERSINFO[0]}" "${BASH_VERSINFO[1]}"'], text=True)
        if tuple(map(int, version.split('.'))) < (5, 1):
            self.skipTest('Bash before 5.1 does not execute PROMPT_COMMAND arrays')
        self.prepare_shell()
        output = self.run_bash('PROMPT_COMMAND=(\'printf "FIRST\\n"\' \'printf "SECOND\\n"\'); '
            'source "$1"; source "$1"; printf "LENGTH:%s\\n" "${#PROMPT_COMMAND[@]}"; '
            'for callback in "${PROMPT_COMMAND[@]}"; do eval "$callback"; done')
        self.assertIn(b'LENGTH:3', output)
        self.assertEqual(output.count(b'FIRST'), 1, output)
        self.assertEqual(output.count(b'SECOND'), 1, output)

    def test_non_ghostty_and_noninteractive_shells_do_not_register(self):
        manager = self.prepare_shell()
        for options in ({'ghostty': False}, {'interactive': False}):
            self.run_bash('source "$1"', **options)
            self.assertFalse(manager.state_path.exists())


if __name__ == '__main__':
    unittest.main()
