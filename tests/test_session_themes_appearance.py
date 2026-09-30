#!/usr/bin/python3
"""Regression checks for macOS appearance detection and per-session switching."""
import importlib.util
from pathlib import Path
import plistlib
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.dont_write_bytecode = True
from support import CONFIG, load_themes
themes = load_themes()
EXPORT = ['/usr/bin/defaults', 'export', 'NSGlobalDomain', '-']


def exported(preferences, fmt=plistlib.FMT_XML):
    return subprocess.CompletedProcess(EXPORT, 0, plistlib.dumps(preferences, fmt=fmt), b'')


class AppearanceTests(unittest.TestCase):
    def test_macos_27_missing_key_regression(self):
        def upgraded_defaults(command, **kwargs):
            if command == EXPORT:
                return exported({'AppleAccentColor': 4})
            return subprocess.CompletedProcess(command, 1, '',
                "Error: Could not find key 'AppleInterfaceStyle' in domain 'kCFPreferencesAnyApplication'.\n")
        with patch.object(themes.subprocess, 'run', side_effect=upgraded_defaults) as run:
            self.assertEqual(themes.system_appearance(), 'light')
        self.assertEqual(run.call_count, 1)
        self.assertEqual(run.call_args.args[0], EXPORT)

    def test_light_dark_and_missing_key_in_xml_and_binary_plists(self):
        for fmt in (plistlib.FMT_XML, plistlib.FMT_BINARY):
            for preferences, expected in (({}, 'light'), ({'AppleInterfaceStyle': 'Light'}, 'light'),
                                          ({'AppleInterfaceStyle': 'Dark'}, 'dark')):
                with self.subTest(fmt=fmt, preferences=preferences):
                    with patch.object(themes.subprocess, 'run', return_value=exported(preferences, fmt)):
                        self.assertEqual(themes.system_appearance(), expected)

    def test_real_command_errors_are_not_misclassified_as_light_mode(self):
        for message in (b'Permission denied', b'Could not find domain', b'domain does not exist'):
            failed = subprocess.CompletedProcess(EXPORT, 1, b'', message)
            with self.subTest(message=message):
                with patch.object(themes.subprocess, 'run', return_value=failed):
                    with self.assertRaisesRegex(ValueError, 'Cannot read macOS appearance'):
                        themes.system_appearance()

    def test_invalid_preferences_fail_clearly(self):
        for payload in (b'not a plist', b'<?xml version="1.0"?><plist><dict>',
                        plistlib.dumps([]), plistlib.dumps({'AppleInterfaceStyle': 'Unknown'})):
            response = subprocess.CompletedProcess(EXPORT, 0, payload, b'')
            with self.subTest(payload=payload):
                with patch.object(themes.subprocess, 'run', return_value=response):
                    with self.assertRaisesRegex(ValueError, 'Cannot read macOS appearance'):
                        themes.system_appearance()

    def test_command_timeout_is_bounded(self):
        with patch.object(themes.subprocess, 'run', side_effect=subprocess.TimeoutExpired(EXPORT, 0.5)) as run:
            with self.assertRaises(subprocess.TimeoutExpired):
                themes.system_appearance()
        self.assertEqual(run.call_args.kwargs['timeout'], 0.5)

    def test_all_families_follow_system_changes_without_changing_rotation(self):
        with tempfile.TemporaryDirectory(prefix='ghostty-appearance-regression-') as directory:
            shutil.copy2(CONFIG, Path(directory) / 'session-themes.conf')
            manager = themes.Themes(directory)
            manager.set_setting('enabled', 'true')
            manager.set_setting('appearance', 'auto')
            pairs = manager.settings()[3]
            with patch.object(themes.subprocess, 'run', return_value=exported({'AppleInterfaceStyle': 'Dark'})):
                for index, family in enumerate(pairs):
                    manager.update('_init', family, '/dev/test-' + str(index))
            for preferences, mode in (({}, 'light'), ({'AppleInterfaceStyle': 'Dark'}, 'dark')):
                with patch.object(themes.subprocess, 'run', return_value=exported(preferences)):
                    for index, (family, names) in enumerate(pairs.items()):
                        output = manager.update('_sync', family, '/dev/test-' + str(index))
                        self.assertIn('\x1b]11;', output)
                        entry = manager.read_state()['sessions'][family]
                        self.assertEqual(entry['family'], family)
                        self.assertEqual(entry['theme'], names[mode])
                        self.assertEqual(manager.update('_sync', family, '/dev/test-' + str(index)), '')
                self.assertEqual(manager.read_state()['counter'], len(pairs))

    def test_forced_appearance_still_works_without_querying_macos(self):
        with tempfile.TemporaryDirectory(prefix='ghostty-forced-appearance-') as directory:
            shutil.copy2(CONFIG, Path(directory) / 'session-themes.conf')
            manager = themes.Themes(directory)
            manager.set_setting('enabled', 'true')
            manager.set_setting('appearance', 'light')
            with patch.object(themes.subprocess, 'run', side_effect=AssertionError('Unexpected macOS query')):
                output = manager.update('_init', 'one', '/dev/test')
            self.assertIn('\x1b]11;#faf4ed\x1b\\', output)


if __name__ == '__main__':
    unittest.main(verbosity=2)
