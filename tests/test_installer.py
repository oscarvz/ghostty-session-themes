import argparse
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from support import ROOT, CONFIG, create_palettes

spec = importlib.util.spec_from_file_location('installer', ROOT / 'scripts/manage.py')
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


class InstallerTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='ghostty-install-tests-')
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name).resolve()
        self.prefix = self.directory / "Install with spaces and 'quotes'"
        self.zshrc = self.directory / '.zshrc'
        self.zshrc.write_text('# user configuration\nexport EXAMPLE=retained\n')
        self.original_shell = self.zshrc.read_bytes()
        self.legacy = self.directory / 'legacy'
        self.ghostty = self.directory / 'Ghostty.app'
        binary = self.ghostty / 'Contents/MacOS/ghostty'
        binary.parent.mkdir(parents=True)
        pairs = create_palettes(self.ghostty / 'Contents/Resources/ghostty/themes')
        binary.write_text('#!/usr/bin/env python3\nimport sys\npairs = ' + repr(pairs) + '\n'
                          'mode = sys.argv[-1].split("=")[-1]\nprint("\\n".join(pairs[mode]))\n')
        binary.chmod(0o700)
        self.args = argparse.Namespace(prefix=self.prefix, zshrc=self.zshrc, legacy_dir=self.legacy,
                                       ghostty=self.ghostty, config=None, check=False)
        run = subprocess.run

        def compile_or_run(arguments, **kwargs):
            if arguments[:2] == ['/usr/bin/xcrun', 'clang']:
                Path(arguments[arguments.index('-o') + 1]).write_text('#!/bin/sh\nexit 0\n')
                return subprocess.CompletedProcess(arguments, 0, '', '')
            return run(arguments, **kwargs)

        self.addCleanup(patch.stopall)
        patch.object(installer.subprocess, 'run', side_effect=compile_or_run).start()
        patch.object(installer.themes.Themes, 'ensure_listener').start()
        patch.object(installer, 'ghostty_configs', return_value=[]).start()
        self.output = io.StringIO()
        self.addCleanup(self.output.close)
        self.redirect = contextlib.redirect_stdout(self.output)
        self.redirect.__enter__()
        self.addCleanup(self.redirect.__exit__, None, None, None)

    def install(self):
        installer.install(self.args)

    def latest_backup(self):
        return sorted((self.prefix / 'backups').iterdir())[-1]

    def test_fresh_install_is_independent_of_checkout_and_repeats_without_duplicate_hooks(self):
        self.install()
        self.assertTrue((self.prefix / 'session-theme').stat().st_mode & 0o100)
        result = subprocess.run([str(self.prefix / 'session-theme'), 'status'], check=True, capture_output=True, text=True)
        self.assertIn('Version: 0.1.0', result.stdout)
        self.assertNotIn(str(ROOT), (self.prefix / 'runtime.json').read_text())
        self.install()
        self.assertEqual(self.zshrc.read_text().count(installer.BEGIN), 1)
        self.assertTrue(self.zshrc.read_bytes().startswith(self.original_shell))

    def test_upgrade_preserves_settings_state_and_later_shell_edits(self):
        self.install()
        config = self.prefix / 'session-themes.conf'
        config.write_text(config.read_text().replace('appearance = auto', 'appearance = dark'))
        state = self.prefix / 'session-themes-state.json'
        state.write_text('{"counter": 42, "sessions": {}}\n')
        self.zshrc.write_text(self.zshrc.read_text() + '# added afterwards\n')
        self.install()
        self.assertIn('appearance = dark', config.read_text())
        self.assertEqual(json.loads(state.read_text())['counter'], 42)
        self.assertTrue(self.zshrc.read_text().endswith('# added afterwards\n'))

    def test_check_and_failed_build_do_not_modify_user_files(self):
        self.args.check = True
        self.install()
        self.assertFalse(self.prefix.exists())
        self.assertEqual(self.zshrc.read_bytes(), self.original_shell)
        self.args.check = False
        with patch.object(installer, 'prepare_payload', side_effect=subprocess.CalledProcessError(1, 'clang')):
            with self.assertRaises(subprocess.CalledProcessError):
                self.install()
        self.assertFalse(self.prefix.exists())

    def test_invalid_theme_aborts_before_modifying_shell_or_installation(self):
        (self.ghostty / 'Contents/Resources/ghostty/themes/Rose Pine Dawn').unlink()
        with self.assertRaises(FileNotFoundError):
            self.install()
        self.assertEqual(self.zshrc.read_bytes(), self.original_shell)
        self.assertFalse(self.prefix.exists())

    def test_custom_initial_config_and_symlinked_zshrc(self):
        custom = self.directory / 'custom.ini'
        custom.write_text(CONFIG.read_text().replace('show_status = true', 'show_status = false'))
        self.args.config = custom
        link = self.directory / 'shell-link'
        link.symlink_to(self.zshrc)
        self.args.zshrc = link
        self.install()
        self.assertTrue(link.is_symlink())
        self.assertIn('show_status = false', (self.prefix / 'session-themes.conf').read_text())
        self.assertIn(installer.BEGIN, self.zshrc.read_text())

    def test_uninstall_retains_data_disables_old_shells_and_can_be_restored(self):
        self.install()
        config = (self.prefix / 'session-themes.conf').read_bytes()
        installer.uninstall(self.args)
        self.assertEqual(self.zshrc.read_bytes(), self.original_shell)
        self.assertTrue((self.prefix / '.disabled').exists())
        self.assertEqual((self.prefix / 'session-themes.conf').read_bytes(), config)
        result = subprocess.run([str(self.prefix / 'session-theme'), 'status'], capture_output=True, text=True, check=True)
        self.assertIn('disabled', result.stdout)
        installer.restore(argparse.Namespace(backup=self.latest_backup()))
        self.assertFalse((self.prefix / '.disabled').exists())
        self.assertIn(installer.BEGIN, self.zshrc.read_text())

    def test_backup_refuses_to_overwrite_subsequent_edits(self):
        self.install()
        installer.uninstall(self.args)
        backup = self.latest_backup()
        self.zshrc.write_text(self.zshrc.read_text() + '# keep this new edit\n')
        with self.assertRaisesRegex(ValueError, 'File changed'):
            installer.restore(argparse.Namespace(backup=backup))
        self.assertTrue(self.zshrc.read_text().endswith('# keep this new edit\n'))

    def test_fresh_install_rollback_removes_a_new_shell_hook_but_retains_disabled_data(self):
        self.zshrc.unlink()
        self.install()
        installer.restore(argparse.Namespace(backup=self.latest_backup()))
        self.assertFalse(self.zshrc.exists())
        self.assertTrue((self.prefix / '.disabled').exists())
        self.assertTrue((self.prefix / 'session-themes.conf').exists())

    def test_foreign_files_at_prefix_are_not_overwritten(self):
        self.prefix.mkdir()
        existing = self.prefix / 'session-themes.py'
        existing.write_text('unrelated user file\n')
        with self.assertRaisesRegex(ValueError, 'Unrecognised files'):
            self.install()
        self.assertEqual(existing.read_text(), 'unrelated user file\n')

    def test_readonly_ghostty_config_backup_preserves_a_symlink(self):
        original = self.directory / 'dotfiles-ghostty-config'
        original.write_text('theme = custom-default\n')
        link = self.directory / 'config.ghostty'
        link.symlink_to(original)
        with patch.object(installer, 'ghostty_configs', return_value=[link]):
            self.install()
        self.assertTrue(link.is_symlink())
        self.assertEqual(original.read_text(), 'theme = custom-default\n')
        backup = self.latest_backup()
        entry = json.loads((backup / 'manifest.json').read_text())['files'][str(link)]
        self.assertFalse(entry['managed'])
        self.assertEqual((backup / entry['copy']).read_bytes(), original.read_bytes())

    def test_already_migrated_legacy_helper_does_not_create_a_second_installation(self):
        self.legacy.mkdir()
        shutil.copyfile(CONFIG, self.legacy / 'session-themes.conf')
        (self.legacy / 'session-themes.py').write_text('# Managed compatibility entry point.\n')
        with self.assertRaisesRegex(ValueError, 'already migrated'):
            self.install()
        self.assertFalse(self.prefix.exists())

    def test_legacy_migration_keeps_assignments_and_forwards_existing_shells(self):
        self.legacy.mkdir()
        shutil.copyfile(CONFIG, self.legacy / 'session-themes.conf')
        (self.legacy / 'session-themes.py').write_text('# previous helper\n')
        (self.legacy / 'session-themes.zsh').write_text('# previous loader\n')
        state = '{"counter": 17, "sessions": {}}\n'
        (self.legacy / 'session-themes-state.json').write_text(state)
        self.zshrc.write_text(self.zshrc.read_text() + installer.hook(self.legacy))
        self.install()
        self.assertEqual((self.prefix / 'session-themes-state.json').read_text(), state)
        result = subprocess.run([str(Path(os.sys.executable)), str(self.legacy / 'session-themes.py'), 'config'],
                                capture_output=True, text=True, check=True)
        self.assertEqual(result.stdout.strip(), str(self.prefix / 'session-themes.conf'))
        self.assertEqual(self.zshrc.read_text().count(installer.BEGIN), 1)
        self.assertNotIn(str(self.legacy), self.zshrc.read_text())

    def test_install_failure_restores_the_previous_files(self):
        self.install()
        before = {name: (self.prefix / name).read_bytes() for name in installer.PAYLOAD}
        original = installer.Backup.write

        def fail_on_loader(backup, path, data, mode=0o600):
            if path == self.prefix / 'session-themes.zsh':
                raise OSError('simulated disk failure')
            return original(backup, path, data, mode)

        with patch.object(installer.Backup, 'write', fail_on_loader):
            with self.assertRaisesRegex(OSError, 'simulated disk failure'):
                self.install()
        self.assertFalse((self.prefix / '.disabled').exists())
        for name, data in before.items():
            self.assertEqual((self.prefix / name).read_bytes(), data)

    def test_malformed_managed_block_is_never_overwritten(self):
        self.zshrc.write_text(installer.BEGIN + '\n# missing end marker\n')
        before = self.zshrc.read_bytes()
        with self.assertRaisesRegex(ValueError, 'Ambiguous'):
            self.install()
        self.assertEqual(self.zshrc.read_bytes(), before)
        self.assertFalse(self.prefix.exists())


if __name__ == '__main__':
    unittest.main(verbosity=2)
