#!/usr/bin/python3
"""Live-update regressions; never write to a real terminal."""
import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

sys.dont_write_bytecode = True
from support import CONFIG, load_themes
themes = load_themes()


class LiveTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='ghostty-live-tests-')
        self.addCleanup(temporary.cleanup)
        shutil.copy2(CONFIG, Path(temporary.name) / 'session-themes.conf')
        self.manager = themes.Themes(temporary.name)
        self.manager.set_setting('enabled', 'true')
        self.manager.set_setting('appearance', 'auto')

    def register(self, number):
        self.manager.update('_init', str(number), '/dev/ttys' + str(number).zfill(3), appearance='dark')

    def owners(self):
        # Distinct owner PID per terminal, as in real independent shells.
        state = self.manager.read_state()
        identities = {}
        for index, entry in enumerate(state['sessions'].values()):
            entry['owner_pid'] = index + 100
            identities[index + 100] = (os.getuid(), entry['tty'], entry['created'] - 1)
        self.manager.save_state(state)
        return identities

    def test_all_ten_families_switch_without_a_prompt_or_rotation(self):
        pairs = self.manager.settings()[3]
        for index in range(len(pairs)):
            self.register(index)
        identities = self.owners()
        with patch.object(themes, 'terminal_owners', return_value=identities), \
                patch.object(themes, 'write_terminal') as write:
            for mode in ('light', 'dark'):
                self.assertEqual(self.manager.broadcast(mode), (10, 0))
                entries = list(self.manager.read_state()['sessions'].values())
                for entry in entries:
                    self.assertEqual(entry['theme'], pairs[entry['family']][mode])
                self.assertTrue(all(call.args[1].startswith(themes.RESET) for call in write.call_args_list))
        self.assertEqual(self.manager.read_state()['counter'], 10)

    def test_dead_reused_or_foreign_process_is_skipped(self):
        self.register(0)
        entry = self.manager.read_state()['sessions']['0']
        for identity in (None, (os.getuid(), '/dev/ttys999', 0),
                         (os.getuid() + 1, entry['tty'], 0),
                         (os.getuid(), entry['tty'], entry['created'] + 1)):
            identities = {entry['owner_pid']: identity} if identity else {}
            with self.subTest(identity=identity), \
                    patch.object(themes, 'terminal_owners', return_value=identities), \
                    patch.object(themes, 'write_terminal') as write:
                self.assertEqual(self.manager.broadcast('light'), (0, 0))
                write.assert_not_called()

    def test_new_default_session_blocks_older_assignment_on_same_tty(self):
        self.register(0)
        self.manager.update('default', 'new', '/dev/ttys000', appearance='dark')
        with patch.object(themes, 'terminal_owners', return_value=self.owners()), \
                patch.object(themes, 'write_terminal') as write:
            self.assertEqual(self.manager.broadcast('light'), (0, 0))
            write.assert_not_called()

    def test_failed_write_is_retried_by_prompt_fallback(self):
        self.register(0)
        with patch.object(themes, 'terminal_owners', return_value=self.owners()), \
                patch.object(themes, 'write_terminal', side_effect=BlockingIOError):
            self.assertEqual(self.manager.broadcast('light'), (0, 1))
        entry = self.manager.read_state()['sessions']['0']
        self.assertIsNone(entry['applied'])
        self.assertEqual(entry['appearance'], 'dark')
        output = self.manager.update('_sync', '0', '/dev/ttys000', appearance='light')
        self.assertIn('\x1b]11;#faf4ed', output)

    def test_off_keeps_existing_sessions_and_pinned_mode_overrides_events(self):
        self.register(0)
        self.manager.set_setting('enabled', 'false')
        self.manager.set_setting('appearance', 'light')
        with patch.object(themes, 'terminal_owners', return_value=self.owners()), \
                patch.object(themes, 'write_terminal') as write:
            self.assertEqual(self.manager.broadcast('dark'), (1, 0))
            self.assertIn('\x1b]11;#faf4ed', write.call_args.args[1])

    def test_live_off_stops_worker_without_writing(self):
        self.manager.set_setting('live_updates', 'false')
        with patch.object(themes, 'Themes', return_value=self.manager), \
                patch.object(themes, 'write_terminal') as write:
            self.assertEqual(themes.main(['_broadcast', 'light']), 20)
            write.assert_not_called()

    def test_listener_status_does_not_create_or_write_files(self):
        lock = self.manager.directory / '.session-themes-observer.lock'
        self.assertFalse(self.manager.listener_running())
        self.assertFalse(lock.exists())
        with themes.locked(lock):
            self.assertTrue(self.manager.listener_running())
        self.assertFalse(self.manager.listener_running())

    def test_regular_files_and_symlinks_cannot_be_terminal_targets(self):
        with patch.object(themes.os, 'open') as opening:
            for name in ('/tmp/file', '/dev/tty', '/dev/ttys123/other', '/dev/ttys123\n'):
                with self.assertRaises(ValueError):
                    themes.write_terminal(name, 'ignored')
            opening.assert_not_called()

    def test_process_identity_uses_uid_tty_and_birth_time_only(self):
        created = time.time()
        started = time.strftime('%a %b %d %H:%M:%S %Y', time.localtime(created - 2))
        # macOS pads the lstart column, including at the end of the output line.
        result = subprocess.CompletedProcess([], 0, '123 ' + str(os.getuid()) + ' ttys001 ' + started + '    \n', '')
        with patch.object(themes.subprocess, 'run', return_value=result) as run:
            owners = themes.terminal_owners([{'owner_pid': 123}])
        self.assertTrue(themes.owns_terminal(dict(owner_pid=123, tty='/dev/ttys001', created=created), owners))
        self.assertEqual(run.call_args.args[0][-1], 'pid=,uid=,tty=,lstart=')


if __name__ == '__main__':
    unittest.main(verbosity=2)
