"""Compile an original, owned Win32 PNG window using installed Microsoft tools.

No download/install, game process access, metadata stubs, input or hooks. The
external smoke harness owns launch/cleanup through its private NativeJob.
"""
from __future__ import annotations
import hashlib
import os
from pathlib import Path
import shutil
import struct
import subprocess

SOURCE = Path(__file__).with_name('SessionWindowFixture.cs')
TITLES = {'client': 'League of Legends', 'game': 'VGA owned game fixture'}
CLASSES = {'client': 'Chrome_WidgetWin_1', 'game': 'RiotWindowClass'}
# SendMessageTimeoutW to the current verified Job-owned client HWND only, with
# wParam=lParam=0 and a pointer-sized LRESULT. Return 0 means rejected/failed;
# otherwise +74 returns the exact sink HWND and +75 returns 1 after destroying
# the sink and checking the original client is foreground. +75 without a live
# sink returns 0. The +74 HWND result proves neither ownership nor foreground
# success. Verify exact Job PID/class/title and actual foreground independently.
# Repeating +74 reuses the live sink; +75 closes it without hiding/moving client.
WM_FOCUS_OWNED_SINK = 0x8000 + 74
WM_RETURN_OWNED_CLIENT = 0x8000 + 75
FOCUS_SINK_CLASS = 'VGAOwnedFocusSink'
FOCUS_SINK_TITLE = 'VGA owned focus sink'
FOCUS_SINK_BOUNDS = (0, 0, 160, 96)
MAX_PNG_BYTES = 8 * 1024 * 1024
MAX_LOG_BYTES = 64 * 1024


def compiler_files(system_root):
    """Only fixed .NET Framework locations under the supplied Windows directory."""
    root = Path(system_root)
    if not root.is_absolute():
        raise ValueError('Expected an absolute Windows system directory')
    directories = [root / 'Microsoft.NET' / name / 'v4.0.30319' for name in ('Framework64', 'Framework')]
    compiler = directories[0] / 'csc.exe'
    if not compiler.is_file():
        raise FileNotFoundError('Existing Microsoft .NET Framework64 csc.exe is required; no installation is attempted')
    references = []
    for name in ('mscorlib.dll', 'System.dll', 'System.Drawing.dll'):
        reference = next((directory / name for directory in directories if (directory / name).is_file()), None)
        if reference is None:
            raise FileNotFoundError('Existing .NET Framework reference is missing: ' + name)
        references.append(reference)
    return compiler, references


def compile_fixture(root, *, timeout=45):
    """Return client_exe, game_exe, compiler, source_sha256 and compiler_log.

    root must be a fresh directory inside the smoke harness's temporary tree.
    No source or produced executable is copied into the application distribution.
    """
    if os.name != 'nt':
        raise OSError('Fixture compilation requires the Windows runner')
    if not 0 < timeout <= 60:
        raise ValueError('Fixture compiler timeout must be between 0 and 60 seconds')
    env = {key.upper(): value for key, value in os.environ.items()}
    compiler, references = compiler_files(env.get('SYSTEMROOT') or env.get('WINDIR') or '')
    root = Path(root).resolve()
    root.mkdir(parents=True, exist_ok=False)
    (root / 'Game').mkdir()
    output = root / 'LeagueClientUx.exe'
    command = [str(compiler), '/nologo', '/noconfig', '/nostdlib+', '/target:winexe', '/platform:x64',
               '/optimize+', '/warn:4', '/nowarn:0649', '/warnaserror+', '/out:' + str(output),
               *('/reference:' + str(path) for path in references), str(SOURCE.resolve())]
    completed = subprocess.run(command, cwd=root, capture_output=True, timeout=timeout, check=False)
    raw_log = completed.stdout + completed.stderr
    if len(raw_log) > MAX_LOG_BYTES:
        raise RuntimeError('Fixture compiler log exceeded 64 KiB')
    compiler_log = raw_log.decode('utf-8', errors='replace')
    if completed.returncode != 0:
        raise RuntimeError('Installed Framework compiler failed: ' + compiler_log)
    if not output.is_file() or not output.read_bytes().startswith(b'MZ'):
        raise RuntimeError('Compiler did not produce a Windows fixture executable')
    game = root / 'Game' / 'League of Legends.exe'
    shutil.copyfile(output, game)
    digest = hashlib.sha256(output.read_bytes()).hexdigest()
    if hashlib.sha256(game.read_bytes()).hexdigest() != digest:
        raise RuntimeError('Fixture executable copy changed bytes')
    return {'client_exe': output, 'game_exe': game, 'compiler': compiler,
            'source_sha256': hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
            'executable_sha256': digest, 'compiler_log': compiler_log}


def validate_png(path):
    """Reject non-PNG/oversized inputs before the fixture's full GDI+ PNG decode."""
    path = Path(path).resolve(strict=True)
    if not path.is_file() or not 33 <= path.stat().st_size <= MAX_PNG_BYTES:
        raise ValueError('Expected a bounded local original PNG fixture')
    with path.open('rb') as source:
        header = source.read(24)
    if header[:16] != b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR':
        raise ValueError('Expected a PNG IHDR header')
    width, height = struct.unpack('>II', header[16:24])
    if not (1 <= width <= 4096 and 1 <= height <= 4096):
        raise ValueError('PNG dimensions are outside the fixture limit')
    return path


def fixture_argv(exe, role, png, ready_json, *, x=20, y=20, width=964, height=602, lifetime=240, no_activate=False):
    """Exact command vector; NativeJob.spawn(argv[0], argv[1:], env, cwd)."""
    if role not in TITLES:
        raise ValueError('Unknown owned fixture role')
    if type(no_activate) is not bool:
        raise ValueError('Fixture no_activate must be a boolean')
    for value, low, high in ((x, 0, 4096), (y, 0, 4096), (width, 64, 1600),
                             (height, 64, 1000), (lifetime, 1, 600)):
        if not isinstance(value, int) or isinstance(value, bool) or not low <= value <= high:
            raise ValueError('Fixture geometry/lifetime is outside its bounded range')
    png = validate_png(png)
    ready = Path(ready_json).resolve()
    if ready.exists():
        raise ValueError('Ready evidence path must be fresh')
    return [str(Path(exe).resolve()), role, str(png), str(ready),
            *(str(value) for value in (x, y, width, height, lifetime)),
            *(['noactivate'] if no_activate else [])]


def validate_ready(value, *, role, pid, width, height):
    if not isinstance(value, dict):
        raise AssertionError('Owned fixture readiness must be a JSON object')
    for name, expected in (('protocol', 1), ('pid', pid), ('width', width), ('height', height)):
        if type(value.get(name)) is not int or value[name] != expected:
            raise AssertionError('Owned fixture readiness mismatch: ' + name)
    if value.get('role') != role or value.get('class_name') != CLASSES[role]:
        raise AssertionError('Owned fixture role/class mismatch')
    if type(value.get('hwnd')) is not int or value['hwnd'] <= 0:
        raise AssertionError('Owned fixture HWND is invalid')
    if type(value.get('paint_count')) is not int or value['paint_count'] <= 0:
        raise AssertionError('Owned fixture PNG was not painted')
    if value.get('per_monitor_v2') is not True:
        raise AssertionError('Owned fixture PMv2 DPI awareness was not verified')
    return {'hwnd': value['hwnd'], 'pid': value['pid']}
