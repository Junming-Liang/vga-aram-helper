"""External, fail-closed walkthrough of the exact public EXE's normal Windows UI.

No application test switches, HTTP API, in-process Qt access, injected code, input
hooks, remote desktop changes, or capture-protection bypass. The only fixture is
an original WinForms mock game displaying three public augment names. Evidence is
bounded OS screen-region PNGs plus read-only UI Automation/Win32 observations.
A failed interactive-desktop gate is a failed test, never native GUI proof.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import ctypes
from ctypes import wintypes as W
import json
import os
import platform
from pathlib import Path
import secrets
import shutil
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tests'))
sys.path.insert(0, str(ROOT / 'scripts'))
from windows_exe_smoke import isolated_windows_environment, smoke_workspace
from windows_ota_smoke import NativeJob, Deadline, sha256, read_json, write_json, CONTROL_TITLE, OVERLAY_TITLE
from fetch_ota_fixture import FIXTURE_MANIFEST

EXPECTED_SHA256 = FIXTURE_MANIFEST['sha256']
EXPECTED_SIZE = FIXTURE_MANIFEST['size']
MAX_SECONDS = 240  # Reserve up to 45 seconds for job and temporary-directory cleanup.
MAX_SCREENSHOTS = 5
MAX_SCREENSHOT_BYTES = 6 * 1024 * 1024
NAMES = ['珠光护手', '炼狱导管', '双刀流']
HERO = '战争之影'
STAGES = ('artifact', 'interactive_desktop', 'normal_startup', 'target_and_hero',
          'start_and_ocr', 'manual_confirmation', 'overlay_clickthrough', 'stop', 'close')

# Only the fixture process contains this code. It never loads the application's
# assemblies or calls application functions. UIA operations are read-only.
POWERSHELL_HELPER = r'''
param([string]$Config)
$ErrorActionPreference = 'Stop'
trap {
  $message=$_.Exception.ToString()
  if($message.Length -gt 1800) { $message=$message.Substring(0,1800) }
  [IO.File]::WriteAllText(($Config+'.error.json'),(@{error=$message} | ConvertTo-Json -Compress),[Text.UTF8Encoding]::new($false))
  exit 1
}
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
$c = Get-Content -LiteralPath $Config -Raw -Encoding UTF8 | ConvertFrom-Json
function Write-Json($path, $value) {
  $temporary = "$path.tmp"
  [IO.File]::WriteAllText($temporary, ($value | ConvertTo-Json -Depth 12 -Compress), [Text.UTF8Encoding]::new($false))
  Move-Item -LiteralPath $temporary -Destination $path -Force
}
Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public static class FixtureNative {
  [StructLayout(LayoutKind.Sequential)] public struct Rect { public int Left, Top, Right, Bottom; }
  [DllImport("user32.dll")] public static extern bool SetProcessDpiAwarenessContext(IntPtr context);
  [DllImport("user32.dll")] public static extern IntPtr GetThreadDpiAwarenessContext();
  [DllImport("user32.dll")] public static extern int GetAwarenessFromDpiAwarenessContext(IntPtr context);
  [DllImport("user32.dll")] public static extern bool AreDpiAwarenessContextsEqual(IntPtr a, IntPtr b);
  [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr hwnd);
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr hwnd, out Rect rectangle);
  [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr hwnd, out uint pid);
  [DllImport("user32.dll")] public static extern IntPtr GetWindowLongPtrW(IntPtr hwnd, int index);
}
'@
[void][FixtureNative]::SetProcessDpiAwarenessContext([IntPtr](-4))
$dpiContext=[FixtureNative]::GetThreadDpiAwarenessContext()
$dpiAwareness=[FixtureNative]::GetAwarenessFromDpiAwarenessContext($dpiContext)
if($dpiAwareness -ne 2 -or -not [FixtureNative]::AreDpiAwarenessContextsEqual($dpiContext,[IntPtr](-4))) {
  throw 'Fixture capture process is not verified per-monitor-v2 DPI aware'
}
[Windows.Forms.Application]::EnableVisualStyles()
$script:clicks = 0; $script:keys = 0; $script:lastClick = @(); $script:lastKey = ''
$script:overlayWatch=$null; $script:clickOverlay=$null
$f = New-Object Windows.Forms.Form
$f.Text = $c.title
$f.StartPosition = 'CenterScreen'
$f.ClientSize = New-Object Drawing.Size(1000,680)
$f.MinimumSize = New-Object Drawing.Size(760,560)
$f.BackColor = [Drawing.Color]::FromArgb(15,29,39)
$f.KeyPreview = $true
$f.Add_MouseDown({
  param($sender,$event)
  $script:clicks++; $script:lastClick = @($event.X,$event.Y)
  $script:clickOverlay=$null
  if($null -ne $script:overlayWatch) {
    $h=[IntPtr][long]$script:overlayWatch.hwnd;[uint32]$ownerPid=0
    [void][FixtureNative]::GetWindowThreadProcessId($h,[ref]$ownerPid)
    if($ownerPid -eq [int]$script:overlayWatch.pid) {
      $r=New-Object FixtureNative+Rect
      if([FixtureNative]::GetWindowRect($h,[ref]$r)) {
        $point=$f.PointToScreen((New-Object Drawing.Point($event.X,$event.Y)))
        $style=[FixtureNative]::GetWindowLongPtrW($h,-20).ToInt64()
        $script:clickOverlay=@{hwnd=$h.ToInt64();pid=$ownerPid;visible=[FixtureNative]::IsWindowVisible($h);
          rect=@($r.Left,$r.Top,($r.Right-$r.Left),($r.Bottom-$r.Top));extended_style=$style;
          click_screen=@($point.X,$point.Y);contains_click=($point.X -ge $r.Left -and $point.X -lt $r.Right -and $point.Y -ge $r.Top -and $point.Y -lt $r.Bottom);
          transparent_input=(($style -band 0x20) -ne 0);observed_at='actual fixture MouseDown event'}
      }
    }
  }
})
$f.Add_KeyDown({
  param($sender,$event)
  $script:keys++; $script:lastKey = $event.KeyCode.ToString()
})
$f.Add_Paint({
  param($sender,$event)
  $g=$event.Graphics; $width=$f.ClientSize.Width; $height=$f.ClientSize.Height
  $titleFont=New-Object Drawing.Font('Microsoft YaHei',17)
  $nameFont=New-Object Drawing.Font('Microsoft YaHei',27,[Drawing.FontStyle]::Bold)
  $smallFont=New-Object Drawing.Font('Microsoft YaHei',12)
  try {
    $g.DrawString('VGA PUBLIC TEXT FIXTURE / OWNED SYNTHETIC WINDOW',$titleFont,[Drawing.Brushes]::White,20,20)
    $g.DrawString('Public augment names. No game client, account, or player data.',$smallFont,[Drawing.Brushes]::LightGray,20,60)
    $colors=@([Drawing.Color]::FromArgb(37,78,108),[Drawing.Color]::FromArgb(67,70,126),[Drawing.Color]::FromArgb(40,102,79))
    for($i=0;$i -lt 3;$i++) {
      $x=[int]($width*(.155+$i*.233)); $y=[int]($height*.27)
      $brush=New-Object Drawing.SolidBrush($colors[$i])
      try { $g.FillRectangle($brush,$x,$y,[int]($width*.22),[int]($height*.28)) } finally { $brush.Dispose() }
      $g.DrawString([string]$c.names[$i],$nameFont,[Drawing.Brushes]::White,($x+8),($y+40))
    }
    $g.FillRectangle([Drawing.Brushes]::Orange,20,($height-60),40,30)
    $g.FillRectangle([Drawing.Brushes]::Cyan,65,($height-60),40,30)
    $g.DrawString('Owned click/key acknowledgment surface',$smallFont,[Drawing.Brushes]::LightGray,120,($height-58))
  } finally { $titleFont.Dispose();$nameFont.Dispose();$smallFont.Dispose() }
})
$timer=New-Object Windows.Forms.Timer
$timer.Interval=50
$timer.Add_Tick({
  if(-not (Test-Path -LiteralPath $c.request)) { return }
  try {
    $q=Get-Content -LiteralPath $c.request -Raw -Encoding UTF8 | ConvertFrom-Json
    Remove-Item -LiteralPath $c.request
    $value=$null
    switch([string]$q.op) {
      'status' { $value=@{clicks=$script:clicks;keys=$script:keys;last_click=$script:lastClick;last_key=$script:lastKey;click_overlay=$script:clickOverlay} }
      'observe_overlay' { $script:overlayWatch=@{hwnd=[long]$q.hwnd;pid=[int]$q.pid};$value=@{watching=$true} }
      'snapshot' {
        $root=[Windows.Automation.AutomationElement]::FromHandle([IntPtr][long]$q.hwnd)
        if($null -eq $root -or $root.Current.ProcessId -ne [int]$q.pid) { throw 'UIA root PID changed' }
        $all=$root.FindAll([Windows.Automation.TreeScope]::Descendants,[Windows.Automation.Condition]::TrueCondition)
        if($all.Count -gt 400) { throw 'UIA tree exceeds bounded element count' }
        $nodes=@()
        for($i=0;$i -lt $all.Count;$i++) {
          $e=$all.Item($i);$p=$e.Current
          if($p.ProcessId -ne [int]$q.pid) { throw 'UIA descendant is outside owned process' }
          $r=$p.BoundingRectangle;$v=$null;$pattern=$null
          $bounds=@(0,0,0,0)
          if(-not $r.IsEmpty -and -not [double]::IsInfinity($r.X) -and -not [double]::IsInfinity($r.Y)) { $bounds=@($r.X,$r.Y,$r.Width,$r.Height) }
          if($e.TryGetCurrentPattern([Windows.Automation.ValuePattern]::Pattern,[ref]$pattern)) { $v=$pattern.Current.Value }
          $nodes+=@{name=[string]$p.Name;type=[string]$p.ControlType.ProgrammaticName;enabled=$p.IsEnabled;offscreen=$p.IsOffscreen;
            rect=$bounds;value=$v}
        }
        $value=@{hwnd=[long]$q.hwnd;pid=[int]$q.pid;nodes=$nodes}
      }
      'capture' {
        $r=$q.rect
        if($r.Count -ne 4 -or $r[2] -lt 64 -or $r[3] -lt 64 -or $r[2]*$r[3] -gt 8000000) { throw 'Capture bounds invalid' }
        $bitmap=New-Object Drawing.Bitmap([int]$r[2],[int]$r[3])
        $g=[Drawing.Graphics]::FromImage($bitmap)
        try {
          $g.CopyFromScreen([int]$r[0],[int]$r[1],0,0,$bitmap.Size,[Drawing.CopyPixelOperation]::SourceCopy)
          $colors=New-Object 'Collections.Generic.HashSet[int]'
          for($x=0;$x -lt $bitmap.Width;$x += [Math]::Max(1,[int]($bitmap.Width/60))) {
            for($y=0;$y -lt $bitmap.Height;$y += [Math]::Max(1,[int]($bitmap.Height/40))) { [void]$colors.Add($bitmap.GetPixel($x,$y).ToArgb()) }
          }
          if($colors.Count -lt 8) { throw 'OS screen capture is blank or lacks fixture detail' }
          $bitmap.Save([string]$q.path,[Drawing.Imaging.ImageFormat]::Png)
          $value=@{method='System.Drawing.Graphics.CopyFromScreen';copy_operation='SourceCopy (0x00CC0020), without CAPTUREBLT';rect=$r;sampled_colors=$colors.Count}
        } finally { $g.Dispose();$bitmap.Dispose() }
      }
      'close' { $value=@{closing=$true} }
      default { throw 'Unknown fixture operation' }
    }
    Write-Json $c.response @{id=$q.id;ok=$true;value=$value}
    if($q.op -eq 'close') { $f.Close() }
  } catch {
    Write-Json $c.response @{id=$q.id;ok=$false;error=$_.Exception.Message}
  }
})
$f.Add_Shown({
  Write-Json $c.ready @{hwnd=$f.Handle.ToInt64();pid=$PID;title=$f.Text;dpi_awareness=$dpiAwareness;per_monitor_v2=$true}
  $timer.Start()
})
try { [Windows.Forms.Application]::Run($f) } finally { $timer.Stop();$timer.Dispose();$f.Dispose() }
'''


def normal_environment(environ, work):
    env = isolated_windows_environment(environ, work)
    for key in tuple(env):
        if key.startswith(('_PYI_', 'VGA_', 'QT_', 'PYSIDE_')):
            env.pop(key)
    env['VGA_STATE_DIR'] = str(work / 'state')
    temporary = work / 'temporary'
    temporary.mkdir(parents=True, exist_ok=True)
    env.update(TEMP=str(temporary), TMP=str(temporary), PYINSTALLER_RESET_ENVIRONMENT='1')
    # Normal public networking is retained. No rejecting proxy, data injection,
    # fabricated cache, backend override, update-disable flag or readiness hook.
    return env


def validate_executable(path):
    path = Path(path)
    if path.suffix.lower() != '.exe' or not path.is_file():
        raise AssertionError('Expected the exact public Windows EXE fixture')
    if path.stat().st_size != EXPECTED_SIZE or sha256(path) != EXPECTED_SHA256:
        raise AssertionError('Published EXE size/SHA256 mismatch; refusing execution')
    return {'sha256': EXPECTED_SHA256, 'size': EXPECTED_SIZE, 'version': FIXTURE_MANIFEST['version'],
            'source': FIXTURE_MANIFEST['url'], 'arguments': []}



def validate_public_cache(cache_dir):
    # Observe the application's own normal download; never create/modify a cache
    # or use it instead of visible GUI selection and production OCR.
    from data_updates import load_cached_data
    from engine import normalize
    envelope=load_cached_data(cache_dir)
    if not envelope or envelope.get('status',{}).get('usingCached') is not False:
        raise AssertionError('Fresh normal-startup public data cache was not verified')
    data=normalize(envelope['data'])
    if data.get('metadata',{}).get('isDemo') is not False or HERO not in data.get('heroes',{}):
        raise AssertionError('Normal public catalog does not include the expected real hero')
    if any(name not in data.get('augments',{}) for name in NAMES):
        raise AssertionError('Public augment catalog changed; refusing synthetic substitutions')
    status=envelope['status']
    return {key:status.get(key) for key in ('sourceMode','wikiBaseUrl','version','gamePatch','sourceDataDate','sha256','usingCached')}


def intersects(a, b):
    return a[0] < b[0] + b[2] and b[0] < a[0] + a[2] and a[1] < b[1] + b[3] and b[1] < a[1] + a[3]


def element(nodes, caption=None, kind=None):
    matches = [n for n in nodes if (caption is None or n['name'] == caption)
               and (kind is None or n['type'] == 'ControlType.' + kind)]
    if len(matches) != 1:
        raise AssertionError(f'Expected one owned UIA element ({caption!r}, {kind!r}); found {len(matches)}')
    return matches[0]



def valid_overlay_click(ack, hwnd, pid):
    event=ack.get('click_overlay') or {}
    required=0x00080000|0x08000000|0x80|0x8|0x20
    return (event.get('hwnd')==hwnd and event.get('pid')==pid and event.get('visible') is True
            and event.get('contains_click') is True and event.get('transparent_input') is True
            and event.get('extended_style',0)&required==required
            and event.get('observed_at')=='actual fixture MouseDown event')


def text_values(nodes):
    return [n.get('value') if n.get('value') is not None else n.get('name', '') for n in nodes]


class Desktop:
    def __init__(self, job):
        self.job, self.u, self.k = job, job.u, job.k
        signatures = {
            'OpenInputDesktop': ([W.DWORD, W.BOOL, W.DWORD], W.HANDLE),
            'CloseDesktop': ([W.HANDLE], W.BOOL),
            'GetThreadDesktop': ([W.DWORD], W.HANDLE),
            'GetUserObjectInformationW': ([W.HANDLE, ctypes.c_int, ctypes.c_void_p, W.DWORD, ctypes.POINTER(W.DWORD)], W.BOOL),
            'GetForegroundWindow': ([], W.HWND), 'GetAncestor': ([W.HWND, W.UINT], W.HWND),
            'GetWindowRect': ([W.HWND, ctypes.POINTER(W.RECT)], W.BOOL),
            'GetClientRect': ([W.HWND, ctypes.POINTER(W.RECT)], W.BOOL),
            'ClientToScreen': ([W.HWND, ctypes.POINTER(W.POINT)], W.BOOL),
            'WindowFromPoint': ([W.POINT], W.HWND), 'IsIconic': ([W.HWND], W.BOOL),
            'ShowWindow': ([W.HWND, ctypes.c_int], W.BOOL), 'SetForegroundWindow': ([W.HWND], W.BOOL),
            'GetWindowDisplayAffinity': ([W.HWND, ctypes.POINTER(W.DWORD)], W.BOOL),
            'GetSystemMetrics': ([ctypes.c_int], ctypes.c_int),
            'GetDpiForWindow': ([W.HWND], W.UINT),
            'GetWindow': ([W.HWND, W.UINT], W.HWND),
            'GetThreadDpiAwarenessContext': ([], ctypes.c_void_p),
            'GetAwarenessFromDpiAwarenessContext': ([ctypes.c_void_p], ctypes.c_int),
            'AreDpiAwarenessContextsEqual': ([ctypes.c_void_p,ctypes.c_void_p], W.BOOL),
        }
        for name, (args, result) in signatures.items():
            fn = getattr(self.u, name); fn.argtypes, fn.restype = args, result
        self.k.ProcessIdToSessionId.argtypes = (W.DWORD, ctypes.POINTER(W.DWORD))
        self.k.ProcessIdToSessionId.restype = W.BOOL
        self.k.GetCurrentThreadId.restype = W.DWORD
        # Per-process DPI awareness only; no desktop/display/settings changes.
        try:
            self.u.SetProcessDpiAwarenessContext.argtypes = (ctypes.c_void_p,)
            self.u.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
        except AttributeError:
            raise AssertionError('Controller requires verifiable per-monitor-v2 DPI awareness')
        context=self.u.GetThreadDpiAwarenessContext()
        self.dpi_awareness=self.u.GetAwarenessFromDpiAwarenessContext(context)
        if self.dpi_awareness != 2 or not self.u.AreDpiAwarenessContextsEqual(context,ctypes.c_void_p(-4)):
            raise AssertionError('Controller is not verified per-monitor-v2 DPI aware')

        class Mouse(ctypes.Structure):
            _fields_ = [('dx', W.LONG), ('dy', W.LONG), ('data', W.DWORD), ('flags', W.DWORD),
                        ('time', W.DWORD), ('extra', ctypes.c_size_t)]
        class Keyboard(ctypes.Structure):
            _fields_ = [('vk', W.WORD), ('scan', W.WORD), ('flags', W.DWORD), ('time', W.DWORD), ('extra', ctypes.c_size_t)]
        class Payload(ctypes.Union):
            _fields_ = [('mouse', Mouse), ('key', Keyboard)]
        class Input(ctypes.Structure):
            _fields_ = [('type', W.DWORD), ('payload', Payload)]
        self.Mouse, self.Keyboard, self.Input = Mouse, Keyboard, Input
        self.u.SendInput.argtypes = (W.UINT, ctypes.POINTER(Input), ctypes.c_int)
        self.u.SendInput.restype = W.UINT

    def readiness(self):
        session = W.DWORD()
        if not self.k.ProcessIdToSessionId(os.getpid(), ctypes.byref(session)):
            raise ctypes.WinError(ctypes.get_last_error())
        result = {'process_pid': os.getpid(), 'process_session_id': session.value,
                  'input_desktop_opened': False, 'interactive_verified': False,
                  'platform': platform.platform(), 'windows_version': list(sys.getwindowsversion()),
                  'windows_product_type': sys.getwindowsversion().product_type,
                  'controller_dpi_awareness':self.dpi_awareness,'controller_per_monitor_v2':True,
                  'virtual_screen': [self.u.GetSystemMetrics(i) for i in (76,77,78,79)]}
        handle = self.u.OpenInputDesktop(0, False, 0x0001)  # DESKTOP_READOBJECTS only
        if not handle:
            result['win32_error'] = ctypes.get_last_error()
            return result
        try:
            result['input_desktop_opened'] = True
            result['input_desktop_handle'] = int(handle)
            def name(desktop):
                value, size = ctypes.create_unicode_buffer(256), W.DWORD()
                if not self.u.GetUserObjectInformationW(desktop, 2, value, ctypes.sizeof(value), ctypes.byref(size)):
                    raise ctypes.WinError(ctypes.get_last_error())
                return value.value
            result['input_desktop_name'] = name(handle)
            result['thread_desktop_name'] = name(self.u.GetThreadDesktop(self.k.GetCurrentThreadId()))
            result['metadata_ready'] = (session.value != 0 and result['input_desktop_name'].lower() == 'default'
                                        and result['input_desktop_name'] == result['thread_desktop_name'])
            return result
        finally:
            self.u.CloseDesktop(handle)

    def pid(self, hwnd):
        pid = W.DWORD(); self.u.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        return int(pid.value)

    def owned(self, hwnd):
        pid = self.pid(hwnd)
        if not pid or pid not in self.job.pids():
            raise AssertionError('Window PID is not in the private test process job')
        return pid

    def rect(self, hwnd, client=True):
        self.owned(hwnd)
        r = W.RECT()
        if not (self.u.GetClientRect if client else self.u.GetWindowRect)(hwnd, ctypes.byref(r)):
            raise ctypes.WinError(ctypes.get_last_error())
        x, y = r.left, r.top
        if client:
            point = W.POINT(0, 0)
            if not self.u.ClientToScreen(hwnd, ctypes.byref(point)):
                raise ctypes.WinError(ctypes.get_last_error())
            x, y = point.x, point.y
        return [x, y, r.right-r.left, r.bottom-r.top]

    def foreground(self, hwnd):
        self.owned(hwnd)
        actual = int(self.u.GetAncestor(self.u.GetForegroundWindow(), 2) or 0)
        # Qt combo/completer popups may be separate HWNDs. Accept only a same-PID
        # transient whose real Win32 owner chain reaches the intended HWND.
        for _ in range(8):
            if actual == hwnd:
                return
            if not actual or self.pid(actual) != self.pid(hwnd):
                break
            actual = int(self.u.GetWindow(actual, 4) or 0)  # GW_OWNER, read-only
        raise AssertionError('Owned target is not foreground; refusing input/capture')

    def activate(self, hwnd):
        self.owned(hwnd)
        if self.u.IsIconic(hwnd):
            self.u.ShowWindow(hwnd, 9)  # Preserve normal maximized state.
        self.u.SetForegroundWindow(hwnd)
        Deadline.wait(lambda: int(self.u.GetAncestor(self.u.GetForegroundWindow(), 2) or 0) == hwnd,
                      time.monotonic()+2, 'Windows did not permit foreground activation of the owned window')

    def capture_guard(self, hwnd):
        self.foreground(hwnd)
        if not self.u.IsWindowVisible(hwnd) or self.u.IsIconic(hwnd):
            raise AssertionError('Owned screenshot target is hidden/minimized')
        rect = self.rect(hwnd)
        vx, vy, vw, vh = [self.u.GetSystemMetrics(i) for i in (76,77,78,79)]
        if min(rect[2:]) < 64 or rect[2]*rect[3] > 8_000_000 or not (vx <= rect[0] and vy <= rect[1]
                and rect[0]+rect[2] <= vx+vw and rect[1]+rect[3] <= vy+vh):
            raise AssertionError('Owned screenshot rectangle is offscreen or exceeds its pixel budget')
        owned = self.job.pids(); blocked = []; reached = []
        def visit(other, _):
            if int(other) == hwnd:
                reached.append(True); return False
            if self.u.IsWindowVisible(other) and not self.u.IsIconic(other):
                r = W.RECT()
                if self.u.GetWindowRect(other, ctypes.byref(r)) and intersects(rect,[r.left,r.top,r.right-r.left,r.bottom-r.top]):
                    if self.pid(other) not in owned:
                        blocked.append(True)
            return True
        self.u.EnumWindows(self.job.callback_type(visit), 0)
        if blocked or not reached:
            raise AssertionError('Potential unowned occluder; refusing OS screenshot of this region')
        for fx in (.02,.5,.98):
            for fy in (.02,.5,.98):
                hit=self.u.GetAncestor(self.u.WindowFromPoint(W.POINT(round(rect[0]+rect[2]*fx),round(rect[1]+rect[3]*fy))),2)
                if not hit or self.pid(hit) not in owned:
                    raise AssertionError('Unowned screenshot point hit-test; refusing OS capture')
        return rect

    def send(self, hwnd, entries):
        self.foreground(hwnd)  # Immediately before every actual SendInput call.
        values = (self.Input * len(entries))(*entries)
        if self.u.SendInput(len(values), values, ctypes.sizeof(self.Input)) != len(values):
            raise AssertionError('SendInput did not accept all owned-window input events')

    def key(self, hwnd, vk, modifiers=()):
        self.foreground(hwnd)
        keys = []
        for key in modifiers:
            entry=self.Input();entry.type=1;entry.payload.key=self.Keyboard(key,0,0,0,0);keys.append(entry)
        for flags in (0,2):
            entry=self.Input();entry.type=1;entry.payload.key=self.Keyboard(vk,0,flags,0,0);keys.append(entry)
        for key in reversed(modifiers):
            entry=self.Input();entry.type=1;entry.payload.key=self.Keyboard(key,0,2,0,0);keys.append(entry)
        self.send(hwnd,keys)

    def type_text(self, hwnd, text):
        self.key(hwnd, 0x41, (0x11,))  # Ctrl+A, then actual Unicode keyboard events.
        for unit in range(0, len(text.encode('utf-16-le')), 2):
            self.foreground(hwnd)
            code=int.from_bytes(text.encode('utf-16-le')[unit:unit+2], 'little')
            entries=[]
            for flags in (4,6):
                entry=self.Input();entry.type=1;entry.payload.key=self.Keyboard(0,code,flags,0,0);entries.append(entry)
            self.send(hwnd,entries)

    def click(self, hwnd, x, y):
        self.foreground(hwnd)
        hit=self.u.GetAncestor(self.u.WindowFromPoint(W.POINT(round(x),round(y))),2)
        if int(hit or 0) != hwnd:
            raise AssertionError('Click hit-test is outside the exact owned target window')
        vx,vy,vw,vh=[self.u.GetSystemMetrics(i) for i in (76,77,78,79)]
        if not (vx <= x < vx+vw and vy <= y < vy+vh):
            raise AssertionError('Input point is outside the virtual desktop')
        entries=[]
        for flags in (0xC001,0x0002,0x0004):  # MOVE|ABSOLUTE|VIRTUALDESK, LEFTDOWN, LEFTUP
            entry=self.Input();entry.type=0
            entry.payload.mouse=self.Mouse(round((x-vx)*65535/(vw-1)),round((y-vy)*65535/(vh-1)),0,flags,0,0)
            entries.append(entry)
        self.send(hwnd,entries)

    def click_element(self, hwnd, node):
        if node.get('offscreen') or not node.get('enabled'):
            raise AssertionError('UIA target is offscreen/disabled; refusing guessed click')
        x,y,width,height=node['rect']
        if width <= 0 or height <= 0:
            raise AssertionError('UIA target has empty geometry')
        self.click(hwnd,x+width/2,y+height/2)

    def wheel(self, hwnd, scrollbar, down=True):
        if scrollbar['type'] != 'ControlType.ScrollBar' or scrollbar['offscreen'] or not scrollbar['enabled']:
            raise AssertionError('Scrolling requires a visible owned UIA scrollbar')
        x,y,w,h=scrollbar['rect']
        if h <= w or w <= 0:
            raise AssertionError('Scrolling requires a vertical UIA scrollbar')
        self.click(hwnd,x+w/2,y+h-min(w/2,8) if down else y+min(w/2,8))
        entry=self.Input();entry.type=0
        entry.payload.mouse=self.Mouse(0,0,ctypes.c_uint32(-480 if down else 480).value,0x0800,0,0)
        self.foreground(hwnd);self.send(hwnd,[entry]);time.sleep(.15)

    def overlay_metadata(self, hwnd):
        pid=self.owned(hwnd);affinity=W.DWORD()
        success=self.u.GetWindowDisplayAffinity(hwnd,ctypes.byref(affinity))
        return {'hwnd':hwnd,'pid':pid,'rect':self.rect(hwnd,False),
                'extended_style':int(self.u.GetWindowLongPtrW(hwnd,-20)),
                'display_affinity_query_succeeded':bool(success),
                'display_affinity':int(affinity.value) if success else None,
                'capture_exclusion_requested_by_production':True}


class Fixture:
    def __init__(self, work, job, env, budget):
        self.work,self.job,self.budget=work,job,budget
        self.request,self.response=work/'request.json',work/'response.json'
        self.title='000 VGA PUBLIC FIXTURE '+secrets.token_hex(4)
        script=work/'owned-fixture.ps1';script.write_text(POWERSHELL_HELPER,encoding='utf-8-sig')
        config=work/'fixture-config.json'
        ready=work/'fixture-ready.json'
        write_json(config,{'title':self.title,'names':NAMES,'request':str(self.request),'response':str(self.response),'ready':str(ready)})
        powershell=Path(env['SYSTEMROOT'])/'System32/WindowsPowerShell/v1.0/powershell.exe'
        self.process=job.spawn(powershell,['-NoLogo','-NoProfile','-NonInteractive','-STA','-File',script,'-Config',config],env,work)
        def started():
            if job.poll(self.process) is not None:
                diagnostic=config.with_name(config.name+'.error.json')
                detail=read_json(diagnostic).get('error','') if diagnostic.is_file() else 'No startup diagnostic was produced'
                raise AssertionError('Owned WinForms helper exited: '+str(detail)[:1800])
            return ready.is_file()
        Deadline.wait(started,budget.until(25),'Owned fixture could not initialize')
        value=read_json(ready)
        if value.get('pid') != self.process['pid']:
            raise AssertionError('Fixture readiness does not identify its own job process')
        if value.get('dpi_awareness') != 2 or value.get('per_monitor_v2') is not True:
            raise AssertionError('Fixture did not verify its capture-process DPI awareness')
        self.dpi_awareness=value['dpi_awareness']
        self.hwnd=int(value['hwnd'])

    def ask(self, op, **values):
        if self.request.exists():
            raise AssertionError('Previous fixture request is still pending')
        token=secrets.token_hex(8)
        if self.response.exists():self.response.unlink()
        write_json(self.request,dict(values,id=token,op=op))
        def completed():
            if self.response.exists():return True
            if self.job.poll(self.process) is not None:
                raise AssertionError('Owned fixture exited during external GUI automation')
            return self.response.exists()
        Deadline.wait(completed,self.budget.until(10),'Bounded fixture/UIA request timed out: '+op)
        response=read_json(self.response)
        if response.get('id') != token or response.get('ok') is not True:
            raise AssertionError('Fixture/UIA operation failed: '+str(response.get('error','invalid response')))
        return response['value']

    def snapshot(self, desktop, hwnd):
        return self.ask('snapshot',hwnd=hwnd,pid=desktop.owned(hwnd))['nodes']


class Evidence:
    def __init__(self, report_dir, fixture, desktop):
        self.directory,self.fixture,self.desktop=report_dir,fixture,desktop
        self.records=[];self.total=0

    def capture(self, name, hwnd):
        if len(self.records) >= MAX_SCREENSHOTS:
            raise AssertionError('OS screenshot count budget exhausted')
        rect=self.desktop.capture_guard(hwnd)
        path=self.directory/('windows-gui-'+name+'.png')
        if path.exists():
            raise AssertionError('Refusing to overwrite previous screenshot evidence')
        try:
            result=self.fixture.ask('capture',rect=rect,path=str(path))
            if self.desktop.capture_guard(hwnd) != rect:
                raise AssertionError('Owned capture rectangle changed during screenshot')
            size=path.stat().st_size
            with path.open('rb') as handle:
                if handle.read(8) != b'\x89PNG\r\n\x1a\n':
                    raise AssertionError('OS screenshot is not a PNG')
            if size+self.total > MAX_SCREENSHOT_BYTES:
                raise AssertionError('OS screenshot byte budget exhausted')
            self.total+=size
            result.update(file=path.name,bytes=size,sha256=sha256(path),owned_hwnd=hwnd)
            self.records.append(result)
            return result
        except BaseException:
            path.unlink(missing_ok=True)
            raise


@contextmanager
def stage(report, name):
    entry={'name':name,'status':'running'};report['stages'].append(entry)
    started=time.monotonic()
    try:
        yield entry
        entry['status']='passed'
    except BaseException as exc:
        entry.update(status='failed',error=str(exc)[:1800]);raise
    finally:
        entry['elapsed_seconds']=round(time.monotonic()-started,3)


def wait_nodes(fixture, desktop, hwnd, predicate, deadline, description):
    def check():
        nodes=fixture.snapshot(desktop,hwnd)
        return nodes if predicate(nodes) else None
    return Deadline.wait(check,deadline,description)


def visible_element(fixture, desktop, hwnd, caption, kind=None):
    for _ in range(7):
        nodes=fixture.snapshot(desktop,hwnd)
        node=element(nodes,caption,kind)
        if not node['offscreen'] and node['rect'][2]>0 and node['rect'][3]>0:
            # UIA providers occasionally fail to mark clipped scroll children.
            client=desktop.rect(hwnd);x,y,w,h=node['rect']
            if client[1] <= y and y+h <= client[1]+client[3]:
                return node
        scrollbars=[n for n in nodes if n['type']=='ControlType.ScrollBar' and not n['offscreen']
                    and n['rect'][3]>n['rect'][2] and n['rect'][2]>0]
        if len(scrollbars)!=1:raise AssertionError('Expected one visible owned vertical UIA scrollbar')
        desktop.wheel(hwnd,scrollbars[0],down=node['rect'][1]>=desktop.rect(hwnd)[1])
    raise AssertionError('Could not expose owned UIA control by ordinary scrolling: '+str(caption))


def run_walkthrough(original, reports, report, budget):
    fixture=desktop=evidence=job=None;app_hwnd=None
    with smoke_workspace() as work:
        work=work.resolve()  # Normalize Windows 8.3 TEMP aliases before PID image matching.
        try:
            with stage(report,'artifact') as result:
                result.update(validate_executable(original))
                target=work/'VGA-Aram-Helper.exe';shutil.copyfile(original,target)
                validate_executable(target)
                env=normal_environment(os.environ,work)
            with stage(report,'interactive_desktop') as result:
                job=NativeJob();desktop=Desktop(job)
                result.update(desktop.readiness())
                if not result.get('metadata_ready'):
                    raise AssertionError('No eligible interactive Default input desktop; no EXE launch or input attempted')
                fixture=Fixture(work,job,env,budget)
                desktop.activate(fixture.hwnd)
                evidence=Evidence(reports,fixture,desktop)
                result['capture']=evidence.capture('01-desktop-gate',fixture.hwnd)
                before=fixture.ask('status');r=desktop.rect(fixture.hwnd)
                desktop.click(fixture.hwnd,r[0]+r[2]/2,r[1]+r[3]-35)
                desktop.key(fixture.hwnd,0x56)
                ack=Deadline.wait(lambda: (s if (s:=fixture.ask('status'))['clicks']>before['clicks']
                                           and s['keys']>before['keys'] and s['last_key']=='V' else None),
                                  budget.until(5),'Own fixture did not acknowledge actual SendInput click and key')
                result.update(input_acknowledgment=ack,interactive_verified=True,fixture_dpi=desktop.u.GetDpiForWindow(fixture.hwnd),fixture_dpi_awareness=fixture.dpi_awareness,fixture_per_monitor_v2=True)
            with stage(report,'normal_startup') as result:
                app=job.spawn(target,[],env,work)  # Intentionally zero application arguments.
                def started():
                    if job.poll(app) is not None:
                        raise AssertionError('Normal no-argument EXE exited before its visible control window')
                    return job.windows(target)
                windows=Deadline.wait(started,budget.until(70),'Normal EXE control window startup timed out')
                if len(windows)!=1:raise AssertionError('Ambiguous owned normal EXE control windows')
                app_hwnd=windows[0]['hwnd'];desktop.activate(app_hwnd)
                desktop.u.ShowWindow(app_hwnd,3)  # Maximize our app to expose its scrollable controls.
                nodes=wait_nodes(fixture,desktop,app_hwnd,
                    lambda ns:any(n['name']=='开始窗口截图监测' and n['enabled'] for n in ns),
                    budget.until(75),'Normal public-data startup did not enable monitoring')
                source=[n['name'] for n in nodes if '来源日期' in n['name'] and '软件 ' in n['name']]
                if len(source)!=1 or '演示' in source[0] or '资料加载失败' in source[0]:
                    raise AssertionError('UIA did not expose normal non-demo public-data provenance')
                provenance=validate_public_cache(Path(env['VGA_STATE_DIR'])/'data')
                result.update(public_cache=provenance,pid=desktop.owned(app_hwnd),hwnd=app_hwnd,source_label=source[0],arguments=[],
                              screenshot=evidence.capture('02-normal-startup',app_hwnd))
            with stage(report,'target_and_hero') as result:
                desktop.click_element(app_hwnd,element(nodes,'刷新窗口','Button'))
                nodes=fixture.snapshot(desktop,app_hwnd)
                combos=sorted((n for n in nodes if n['type']=='ControlType.ComboBox'),key=lambda n:n['rect'][1])
                if len(combos)!=2:raise AssertionError('Expected the normal target and hero UIA combo boxes')
                desktop.click_element(app_hwnd,combos[0]);desktop.key(app_hwnd,0x1B);desktop.key(app_hwnd,0x24)
                selected=False
                for _ in range(32):
                    desktop.key(app_hwnd,0x28)
                    nodes=fixture.snapshot(desktop,app_hwnd)
                    combos=sorted((n for n in nodes if n['type']=='ControlType.ComboBox'),key=lambda n:n['rect'][1])
                    if fixture.title in ' '.join(str(v) for v in text_values(combos[:1])):
                        selected=True;break
                if not selected:raise AssertionError('Normal target selector did not expose/select the owned fixture')
                desktop.click_element(app_hwnd,combos[1]);desktop.type_text(app_hwnd,HERO)
                desktop.key(app_hwnd,0x0D);desktop.key(app_hwnd,0x1B)
                nodes=fixture.snapshot(desktop,app_hwnd)
                if not any(HERO in str(value) for value in text_values(nodes)):
                    raise AssertionError('Hero keyboard entry was not acknowledged by UIA')
                result.update(target_title=fixture.title,hero=HERO,input_method='UIA geometry + ordinary SendInput')
            with stage(report,'start_and_ocr') as result:
                desktop.click_element(app_hwnd,visible_element(fixture,desktop,app_hwnd,'开始窗口截图监测','Button'))
                nodes=fixture.snapshot(desktop,app_hwnd)
                if not element(nodes,'停止','Button')['enabled']:
                    raise AssertionError('Visible Start action did not enable Stop')
                desktop.activate(fixture.hwnd)
                nodes=wait_nodes(fixture,desktop,app_hwnd,
                    lambda ns:all(name in text_values(ns) for name in NAMES)
                              and any('识别稳定' in n['name'] for n in ns),
                    budget.until(50),'Normal screenshot/OCR handlers did not stably recognize the three public names')
                result.update(recognized=NAMES,normal_ocr_stable=True)
            with stage(report,'manual_confirmation') as result:
                desktop.activate(app_hwnd)
                time.sleep(.35)  # Let normal 200 ms foreground-loss invalidation settle.
                confirm=visible_element(fixture,desktop,app_hwnd,'确认英雄与三项，显示资料叠加','Button')
                desktop.click_element(app_hwnd,confirm)
                nodes=fixture.snapshot(desktop,app_hwnd)
                if not any('名称已手动确认' in n['name'] for n in nodes):
                    raise AssertionError('Normal confirmation handler did not confirm candidates')
                result.update(screenshot=evidence.capture('03-manual-confirmation',app_hwnd),names=NAMES,hero=HERO)
            with stage(report,'overlay_clickthrough') as result:
                desktop.activate(fixture.hwnd)
                overlay=Deadline.wait(lambda:job.windows(target,OVERLAY_TITLE),budget.until(8),'Confirmed overlay never became visible')
                if len(overlay)!=1:raise AssertionError('Ambiguous owned overlay windows')
                overlay_hwnd=overlay[0]['hwnd']
                labels=fixture.snapshot(desktop,overlay_hwnd)
                rendered='\n'.join(n['name'] for n in labels)
                if not all(name in rendered for name in NAMES) or HERO not in rendered or '已人工确认' not in rendered:
                    raise AssertionError('Owned overlay UIA labels do not show the confirmed public names/hero')
                if '虎牙公开源评级' not in rendered or '来源日期' not in rendered or '演示' in rendered:
                    raise AssertionError('Overlay lacks literal public source-tier/provenance labels')
                meta=desktop.overlay_metadata(overlay_hwnd)
                required=0x00080000|0x08000000|0x80|0x8|0x20
                if meta['extended_style'] & required != required:
                    raise AssertionError('Overlay lacks click-through/no-activate/topmost/layered styles')
                result.update(meta,labels=[n['name'] for n in labels if n['name']],
                    screenshot=evidence.capture('04-overlay-region',fixture.hwnd),
                    screenshot_limit='Production display affinity is observed only. WDA_EXCLUDEFROMCAPTURE or SourceCopy layered-window behavior may omit the overlay from this genuine OS screenshot; UIA labels are separate evidence, not overlay pixel proof.')
                fixture.ask('observe_overlay',hwnd=overlay_hwnd,pid=desktop.owned(overlay_hwnd))
                attempts=[]
                for _ in range(3):
                    Deadline.wait(lambda:job.u.IsWindowVisible(overlay_hwnd),budget.until(3),'Overlay hidden before click-through check')
                    before=fixture.ask('status');r=desktop.rect(overlay_hwnd,False)
                    desktop.click(fixture.hwnd,r[0]+r[2]/2,r[1]+r[3]-30)
                    ack=Deadline.wait(lambda:(s if (s:=fixture.ask('status'))['clicks']>before['clicks'] else None),
                                      budget.until(3),'Click through the overlay did not reach the owned fixture')
                    attempts.append(ack)
                    if valid_overlay_click(ack,overlay_hwnd,desktop.owned(overlay_hwnd)):
                        break
                else:
                    raise AssertionError('No actual fixture MouseDown occurred inside the visible click-through overlay')
                desktop.foreground(fixture.hwnd)
                result['clickthrough_acknowledgment']=ack
                result['clickthrough_attempts']=len(attempts)
                # Exercise the visible toggle button twice, without using a global hotkey.
                desktop.activate(app_hwnd)
                for enabled in (False,True):
                    nodes=fixture.snapshot(desktop,app_hwnd)
                    toggle=[n for n in nodes if n['type']=='ControlType.Button' and n['name'].startswith('鼠标穿透：')]
                    if len(toggle)!=1:raise AssertionError('Click-through toggle is ambiguous')
                    node=visible_element(fixture,desktop,app_hwnd,toggle[0]['name'],'Button')
                    desktop.click_element(app_hwnd,node)
                    current=job.windows(target,OVERLAY_TITLE,visible=False)
                    if len(current)!=1:raise AssertionError('Overlay identity missing after normal toggle')
                    observed=desktop.overlay_metadata(current[0]['hwnd'])
                    if bool(observed['extended_style'] & 0x20)!=enabled:
                        raise AssertionError('Normal toggle did not change the OS transparent-input style')
                result['visible_toggle_off_then_on']=True
            with stage(report,'stop') as result:
                desktop.click_element(app_hwnd,visible_element(fixture,desktop,app_hwnd,'停止','Button'))
                nodes=fixture.snapshot(desktop,app_hwnd)
                if element(nodes,'停止','Button')['enabled'] or element(nodes,'确认英雄与三项，显示资料叠加','Button')['enabled']:
                    raise AssertionError('Normal Stop action left monitoring controls enabled')
                if not any('监测已停止' in n['name'] for n in nodes) or job.windows(target,OVERLAY_TITLE):
                    raise AssertionError('Normal Stop action did not hide overlay/report stopped')
                result['overlay_hidden']=True
            with stage(report,'close') as result:
                desktop.key(app_hwnd,0x73,(0x12,))  # Alt+F4, normal owned-window close.
                Deadline.wait(lambda:not job.image_pids(target),budget.until(20),'Normal EXE did not exit after Alt+F4')
                result['normal_exe_exit_code']=job.poll(app)
                if result['normal_exe_exit_code']!=0:raise AssertionError('Normal EXE did not exit cleanly')
                fixture.ask('close')
                Deadline.wait(lambda:not job.pids(),budget.until(10),'Owned GUI descendants survived graceful close')
                result['all_owned_processes_exited']=True
        except BaseException:
            if fixture and desktop:
                if app_hwnd:
                    try:
                        report['failure_uia']=fixture.snapshot(desktop,app_hwnd)[:100]
                    except Exception as exc:report['failure_uia_error']=str(exc)[:600]
                if evidence:
                    try:
                        # Never activate/move another window for a failure screenshot.
                        hwnd=int(desktop.u.GetAncestor(desktop.u.GetForegroundWindow(),2) or 0)
                        evidence.capture('failure',hwnd)
                    except Exception as exc:report['failure_screenshot_error']=str(exc)[:600]
            raise
        finally:
            if evidence:
                report['screenshots']=evidence.records;report['screenshot_bytes']=evidence.total
            if job:
                job.cleanup()
                report['owned_job_cleanup_completed']=True


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--exe',type=Path,required=True)
    parser.add_argument('--report-dir',type=Path,default=ROOT/'reports')
    args=parser.parse_args(argv)
    reports=args.report_dir.resolve();reports.mkdir(parents=True,exist_ok=True)
    report={'status':'failed','scope':'External normal-EXE Windows UI on an owned synthetic public-text fixture only.',
            'platform':platform.platform(),'runner_environment':os.environ.get('RUNNER_ENVIRONMENT','not-reported'),
            'stages':[],'screenshots':[],'limits':{'execution_seconds':MAX_SECONDS,'cleanup_reserve_seconds':45,
            'screenshot_count':MAX_SCREENSHOTS,'screenshot_bytes':MAX_SCREENSHOT_BYTES},
            'limitations':['No real League of Legends, Vanguard, exclusive fullscreen or general game-compatibility proof.',
                           'No video. OS-region PNGs are bounded to owned visible windows and never bypass capture protection.',
                           'The supplied workflow uses a standard Windows Server hosted runner; this is not clean/non-admin Windows 10/11 or human-operated desktop qualification.',
                           'CopyFromScreen uses SourceCopy without CAPTUREBLT: layered overlays can be omitted independently of WDA_EXCLUDEFROMCAPTURE. UIA labels are not overlay pixel proof.',
                           'A noninteractive/locked desktop fails the gate; HWND existence alone is not accepted as UI proof.']}
    started=time.monotonic();code=1
    try:
        if os.name!='nt':raise RuntimeError('Requires a real Windows interactive desktop; this host is not Windows')
        run_walkthrough(args.exe.resolve(),reports,report,Deadline(MAX_SECONDS))
        if [s['name'] for s in report['stages'] if s['status']=='passed']!=list(STAGES):
            raise AssertionError('Walkthrough did not pass every required stage')
        report['status']='passed';code=0
    except Exception as exc:
        report['error']=str(exc)[:2000]
    finally:
        completed={s['name'] for s in report['stages']}
        report['stages'].extend({'name':name,'status':'not_run'} for name in STAGES if name not in completed)
        report['elapsed_seconds']=round(time.monotonic()-started,3)
        write_json(reports/'windows-gui-walkthrough.json',report)
        print(json.dumps({'status':report['status'],'report':'windows-gui-walkthrough.json',
                          'error':report.get('error'),'elapsed_seconds':report['elapsed_seconds']},ensure_ascii=False))
    return code


if __name__=='__main__':
    raise SystemExit(main())
