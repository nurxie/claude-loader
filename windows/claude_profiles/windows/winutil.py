"""Small Windows helpers: known folders, shortcuts, registry, PATH, processes."""

import ctypes
import json
import os
import subprocess
import sys
import tempfile
import uuid
from ctypes import wintypes
from pathlib import Path
from typing import List, Optional

import winreg

CREATE_NO_WINDOW = 0x08000000
DETACHED_PROCESS = 0x00000008
CREATE_NEW_PROCESS_GROUP = 0x00000200

# --- known folders ----------------------------------------------------------------

_FOLDERS = {
    "Desktop": "B4BFCC3A-DB2C-424C-B029-7FE99A87C641",
    "Programs": "A77F5D77-2E2B-44C3-A6A2-ABA601054A51",   # Start Menu\Programs
    "Startup": "B97D20BB-F46A-4C97-BA10-5E3608430854",
}


class _GUID(ctypes.Structure):
    _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD),
                ("Data3", wintypes.WORD), ("Data4", ctypes.c_ubyte * 8)]


def known_folder(name: str) -> Path:
    guid = _GUID()
    ctypes.windll.ole32.CLSIDFromString(f"{{{_FOLDERS[name]}}}", ctypes.byref(guid))
    out = ctypes.c_wchar_p()
    if ctypes.windll.shell32.SHGetKnownFolderPath(ctypes.byref(guid), 0, None,
                                                  ctypes.byref(out)) != 0:
        raise OSError(f"Cannot find the {name} folder")
    try:
        return Path(out.value)
    finally:
        ctypes.windll.ole32.CoTaskMemFree(out)


# --- PowerShell -------------------------------------------------------------------

def powershell(script: str, timeout: int = 120) -> subprocess.CompletedProcess:
    """Run a PowerShell script (from a temp file, so no quoting issues)."""
    fd, path = tempfile.mkstemp(suffix=".ps1")
    try:
        with os.fdopen(fd, "w", encoding="utf-8-sig") as f:
            f.write(script)
        return subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
             "-File", path], capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=timeout, creationflags=CREATE_NO_WINDOW)
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


def powershell_json(script: str, timeout: int = 120):
    r = powershell("$ProgressPreference = 'SilentlyContinue'\n"
                   "[Console]::OutputEncoding = [Text.Encoding]::UTF8\n" + script, timeout)
    text = r.stdout.strip()
    if r.returncode != 0 or not text:
        return None
    try:
        return json.loads(text)
    except ValueError:
        return None


# --- shortcuts ------------------------------------------------------------------------

_SHORTCUT_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
$items = Get-Content -Raw -Encoding UTF8 -LiteralPath $args[0] | ConvertFrom-Json
$wsh = New-Object -ComObject WScript.Shell
foreach ($i in $items) {
    $dir = Split-Path $i.path -Parent
    if (-not (Test-Path -LiteralPath $dir)) { New-Item -ItemType Directory -Force -Path $dir | Out-Null }
    $l = $wsh.CreateShortcut($i.path)
    $l.TargetPath = $i.target
    $l.Arguments = $i.args
    if ($i.icon) { $l.IconLocation = $i.icon + ',0' }
    if ($i.workdir) { $l.WorkingDirectory = $i.workdir }
    if ($i.description) { $l.Description = $i.description }
    $l.WindowStyle = 1
    $l.Save()
}
"""


def create_shortcuts(items: List[dict]) -> None:
    """items: [{path, target, args, icon, workdir, description}] - created in one go."""
    if not items:
        return
    fd, data = tempfile.mkstemp(suffix=".json")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump([{k: str(v) if v is not None else "" for k, v in i.items()} for i in items], f)
    try:
        script = _SHORTCUT_SCRIPT.replace("$args[0]", "'" + data.replace("'", "''") + "'")
        r = powershell(script)
        if r.returncode != 0:
            raise OSError(f"Creating shortcuts failed: {r.stderr.strip()[-400:]}")
    finally:
        os.unlink(data)


def read_shortcut_target(path: Path) -> str:
    """Target + arguments of a .lnk (for recognising old shortcuts)."""
    r = powershell("$l = (New-Object -ComObject WScript.Shell).CreateShortcut('"
                   + str(path).replace("'", "''") + "'); $l.TargetPath + ' ' + $l.Arguments")
    return r.stdout.strip()


# --- registry ---------------------------------------------------------------------------

def reg_get(root, key: str, name: str = "") -> Optional[str]:
    try:
        with winreg.OpenKey(root, key) as k:
            return winreg.QueryValueEx(k, name)[0]
    except OSError:
        return None


def reg_set(root, key: str, name: str, value: str, kind=winreg.REG_SZ) -> None:
    with winreg.CreateKeyEx(root, key, 0, winreg.KEY_SET_VALUE) as k:
        winreg.SetValueEx(k, name, 0, kind, value)


def reg_delete_tree(root, key: str) -> None:
    try:
        with winreg.OpenKey(root, key, 0, winreg.KEY_ALL_ACCESS) as k:
            while True:
                try:
                    sub = winreg.EnumKey(k, 0)
                except OSError:
                    break
                reg_delete_tree(root, f"{key}\\{sub}")
        winreg.DeleteKey(root, key)
    except FileNotFoundError:
        pass


def broadcast_environment_change() -> None:
    HWND_BROADCAST, WM_SETTINGCHANGE, SMTO_ABORTIFHUNG = 0xFFFF, 0x001A, 0x0002
    result = wintypes.DWORD()
    ctypes.windll.user32.SendMessageTimeoutW(HWND_BROADCAST, WM_SETTINGCHANGE, 0, "Environment",
                                             SMTO_ABORTIFHUNG, 3000, ctypes.byref(result))


def _user_path() -> List[str]:
    value = reg_get(winreg.HKEY_CURRENT_USER, "Environment", "Path") or ""
    return [p for p in value.split(";") if p]


def path_contains(folder: Path) -> bool:
    norm = os.path.normcase(os.path.normpath(str(folder)))
    return any(os.path.normcase(os.path.normpath(os.path.expandvars(p))) == norm
               for p in _user_path())


def add_to_user_path(folder: Path) -> bool:
    if path_contains(folder):
        return False
    parts = _user_path() + [str(folder)]
    reg_set(winreg.HKEY_CURRENT_USER, "Environment", "Path", ";".join(parts), winreg.REG_EXPAND_SZ)
    broadcast_environment_change()
    return True


def remove_from_user_path(folder: Path) -> None:
    norm = os.path.normcase(os.path.normpath(str(folder)))
    parts = [p for p in _user_path()
             if os.path.normcase(os.path.normpath(os.path.expandvars(p))) != norm]
    reg_set(winreg.HKEY_CURRENT_USER, "Environment", "Path", ";".join(parts), winreg.REG_EXPAND_SZ)
    broadcast_environment_change()


# --- processes, windows, mutexes ------------------------------------------------------------

def start_detached(cmd: List[str], env: Optional[dict] = None, cwd: Optional[str] = None,
                   log_path: Optional[Path] = None) -> None:
    log = open(log_path, "ab") if log_path else subprocess.DEVNULL
    try:
        subprocess.Popen(cmd, env=env, cwd=cwd, stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                         creationflags=DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP,
                         close_fds=True)
    finally:
        if log_path:
            log.close()


class NamedMutex:
    """Per-session named mutex used as a single-instance lock."""

    ERROR_ALREADY_EXISTS = 183

    def __init__(self, name: str):
        k32 = ctypes.windll.kernel32
        k32.CreateMutexW.restype = wintypes.HANDLE
        self.handle = k32.CreateMutexW(None, False, f"Local\\{name}")
        self.already_exists = ctypes.GetLastError() == self.ERROR_ALREADY_EXISTS

    def close(self) -> None:
        if self.handle:
            ctypes.windll.kernel32.CloseHandle(self.handle)
            self.handle = None


def mutex_exists(name: str) -> bool:
    SYNCHRONIZE = 0x00100000
    k32 = ctypes.windll.kernel32
    k32.OpenMutexW.restype = wintypes.HANDLE
    h = k32.OpenMutexW(SYNCHRONIZE, False, f"Local\\{name}")
    if h:
        k32.CloseHandle(h)
        return True
    return False


def focus_window(title: str) -> bool:
    user32 = ctypes.windll.user32
    user32.FindWindowW.restype = wintypes.HWND
    hwnd = user32.FindWindowW(None, title)
    if not hwnd:
        return False
    SW_RESTORE = 9
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, SW_RESTORE)
    user32.SetForegroundWindow(hwnd)
    return True


def allow_foreground_for_children() -> None:
    ASFW_ANY = 0xFFFFFFFF
    ctypes.windll.user32.AllowSetForegroundWindow(wintypes.DWORD(ASFW_ANY))


def set_dpi_aware() -> None:
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def apps_use_light_theme() -> bool:
    value = reg_get(winreg.HKEY_CURRENT_USER,
                    r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
                    "AppsUseLightTheme")
    return value != 0


def pythonw() -> str:
    """pythonw.exe next to the running interpreter (no console window)."""
    exe = Path(sys.executable)
    candidate = exe.with_name("pythonw.exe")
    return str(candidate if candidate.exists() else exe)


def python_console() -> str:
    exe = Path(sys.executable)
    candidate = exe.with_name("python.exe")
    return str(candidate if candidate.exists() else exe)


def new_id() -> str:
    return uuid.uuid4().hex
