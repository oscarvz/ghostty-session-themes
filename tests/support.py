"""Synthetic theme data so unit tests need neither Ghostty nor bundled artwork."""
import atexit
import configparser
import importlib.util
from pathlib import Path
import tempfile

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / 'config/session-themes.conf'
temporary = tempfile.TemporaryDirectory(prefix='ghostty-test-palettes-')
atexit.register(temporary.cleanup)
RESOURCES = Path(temporary.name)


def create_palettes(directory):
    directory.mkdir(parents=True, exist_ok=True)
    parser = configparser.ConfigParser(interpolation=None)
    parser.read(CONFIG)
    pairs = {'dark': [], 'light': []}
    for value in parser['pairs'].values():
        for mode, name in zip(('dark', 'light'), value.split('|')):
            name = name.strip()
            pairs[mode].append(name)
            background = '#faf4ed' if name == 'Rose Pine Dawn' else ('#102030' if mode == 'dark' else '#e0f0ff')
            colours = ['background = ' + background, 'foreground = #aabbcc', 'cursor-color = #123456']
            colours += ['palette = ' + str(i) + '=#' + format(i * 0x0f0f0f, '06x') for i in range(16)]
            (directory / name).write_text('\n'.join(colours) + '\n')
    return pairs


create_palettes(RESOURCES)


def load_themes():
    spec = importlib.util.spec_from_file_location('session_themes', ROOT / 'src/session-themes.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.RESOURCES = RESOURCES
    return module
