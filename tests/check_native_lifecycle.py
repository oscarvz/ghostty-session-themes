#!/usr/bin/env python3
"""Optional macOS GUI-session check: the observer waits for an in-flight writer."""
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parent.parent


def main():
    binary = ROOT / 'build/session-themes-observer'
    if not binary.exists():
        raise SystemExit('Build the observer first; see docs/development.md.')
    with tempfile.TemporaryDirectory(prefix='ghostty-native-lifecycle-') as temporary:
        directory = Path(temporary)
        shutil.copy2(binary, directory / binary.name)
        (directory / 'session-themes.conf').write_text('# test settings\n')
        (directory / 'writer.py').write_text(
            'from pathlib import Path\nimport time\n'
            'root = Path(__file__).resolve().parent\n'
            '(root / "started").touch()\ntime.sleep(4)\n(root / "finished").touch()\n')
        launch = '#!/bin/sh\nexec ' + shlex.quote(sys.executable) + ' ' + shlex.quote(str(directory / 'writer.py')) + '\n'
        (directory / 'session-theme').write_text(launch)
        (directory / 'session-theme').chmod(0o700)
        process = subprocess.Popen([str(directory / binary.name)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            deadline = time.monotonic() + 6
            while not (directory / 'started').exists() and time.monotonic() < deadline:
                time.sleep(0.05)
            assert (directory / 'started').exists(), 'Native observer did not start its helper'
            (directory / '.disabled').touch()
            time.sleep(2.2)
            assert process.poll() is None, 'Observer released its lock while the writer was still running'
            assert not (directory / 'finished').exists()
            assert process.wait(timeout=8) == 0
            assert (directory / 'finished').exists(), 'Writer was interrupted by observer shutdown'
            print('Native observer waits for its writer before shutdown: PASS')
        finally:
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=5)
            # The synthetic writer finishes within four seconds even if a check fails.
            if (directory / 'started').exists() and not (directory / 'finished').exists():
                time.sleep(4)


if __name__ == '__main__':
    main()
