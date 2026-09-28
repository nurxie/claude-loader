"""Finding Claude Desktop on Windows and keeping the profile copy in sync.

Two kinds of installs exist:

* **MSIX** (Microsoft Store / current installer). Its files live in the protected
  WindowsApps folder, so extra profiles run from a copy in
  %LOCALAPPDATA%\\ClaudePortable (the same folder the older two-account script
  used). The copy does not update itself; `sync_copy()` refreshes it.
* **Squirrel** (older installer) in %LOCALAPPDATA%\\AnthropicClaude. It can be
  started with extra arguments directly, so no copy is needed.
"""

import functools
import os
import re
import struct
import subprocess
from pathlib import Path
from typing import List, Optional

from ..core import paths
from . import winutil

PORTABLE_DIR = paths.LOCALAPPDATA / "ClaudePortable"
VERSION_MARKER = PORTABLE_DIR / ".claude-profiles-version"
SQUIRREL_DIR = paths.LOCALAPPDATA / "AnthropicClaude"
DOWNLOAD_URL = "https://claude.ai/download"


@functools.lru_cache(maxsize=1)
def msix() -> Optional[dict]:
    """{'version', 'location', 'family', 'app_id', 'executable'} or None."""
    info = winutil.powershell_json(r"""
$p = Get-AppxPackage -Name '*Claude*' -ErrorAction SilentlyContinue |
     Where-Object { $_.Publisher -like '*Anthropic*' } | Select-Object -First 1
if (-not $p) { 'null'; exit 0 }
$app = @((Get-AppxPackageManifest $p).Package.Applications.Application)[0]
[pscustomobject]@{
    version = "$($p.Version)"; location = $p.InstallLocation
    family = $p.PackageFamilyName; app_id = $app.Id; executable = $app.Executable
} | ConvertTo-Json -Compress
""")
    return info or None


def squirrel_exe() -> Optional[Path]:
    exe = SQUIRREL_DIR / "claude.exe"
    return exe if exe.exists() else None


def squirrel_version() -> Optional[str]:
    versions = []
    for d in SQUIRREL_DIR.glob("app-*"):
        m = re.fullmatch(r"app-(\d+(?:\.\d+)*)", d.name)
        if m:
            versions.append(tuple(int(x) for x in m.group(1).split(".")))
    return ".".join(map(str, max(versions))) if versions else None


def kind() -> Optional[str]:
    if msix():
        return "msix"
    if squirrel_exe():
        return "squirrel"
    return None


def installed_version() -> Optional[str]:
    m = msix()
    if m:
        return m["version"]
    return squirrel_version() if squirrel_exe() else None


def refresh() -> None:
    msix.cache_clear()
    find_icon.cache_clear()


# --- the copy used by extra profiles (MSIX only) --------------------------------------

def copy_version() -> Optional[str]:
    try:
        return VERSION_MARKER.read_text(encoding="utf-8").strip() or None
    except OSError:
        return None


def copy_exe() -> Optional[Path]:
    m = msix()
    if not m:
        return None
    return PORTABLE_DIR / m["executable"]


def copy_is_current() -> bool:
    m = msix()
    exe = copy_exe()
    return bool(m and exe and exe.exists() and copy_version() == m["version"])


def sync_copy(echo=print) -> None:
    """Mirror the MSIX app into PORTABLE_DIR (about 700 MB, takes a minute)."""
    m = msix()
    if not m:
        raise OSError("Claude Desktop (MSIX) was not found.")
    echo(f"Copying Claude {m['version']} to {paths.short(PORTABLE_DIR)} (may take a minute)...")
    r = subprocess.run(["robocopy", m["location"], str(PORTABLE_DIR), "/MIR", "/R:1", "/W:1",
                        "/NFL", "/NDL", "/NJH", "/NJS", "/NP", "/XF", VERSION_MARKER.name],
                       capture_output=True, text=True, creationflags=winutil.CREATE_NO_WINDOW)
    if r.returncode >= 8:
        raise OSError(f"Copy failed (robocopy exit code {r.returncode}). Close all Claude "
                      "windows that use the copy and try again.")
    exe = copy_exe()
    if not exe or not exe.exists():
        raise OSError(f"The copied app was not found at {exe}")
    VERSION_MARKER.write_text(m["version"], encoding="utf-8")


# --- executables and commands ------------------------------------------------------------

def profile_exe() -> Optional[Path]:
    """Executable for profiles with their own data folder."""
    k = kind()
    if k == "msix":
        return copy_exe()
    if k == "squirrel":
        return squirrel_exe()
    return None


def default_start_command() -> Optional[List[str]]:
    """Start Claude normally (standard data folder)."""
    m = msix()
    if m:
        return [str(Path(os.environ.get("WINDIR", r"C:\Windows")) / "explorer.exe"),
                f"shell:AppsFolder\\{m['family']}!{m['app_id']}"]
    exe = squirrel_exe()
    return [str(exe)] if exe else None


def default_url_command(url: str) -> Optional[List[str]]:
    """Give a claude:// link to the standard instance (what Windows itself would run)."""
    m = msix()
    if m:
        return [str(Path(m["location"]) / m["executable"]), url]
    exe = squirrel_exe()
    return [str(exe), url] if exe else None


def installed_exe() -> Optional[Path]:
    m = msix()
    if m:
        return Path(m["location"]) / m["executable"]
    return squirrel_exe()


# --- running instances --------------------------------------------------------------------

def default_data_dirs() -> List[Path]:
    """Folders the standard instance may use (MSIX may redirect %APPDATA%)."""
    dirs = [paths.DEFAULT_DESKTOP_DATA]
    m = msix()
    if m:
        dirs.append(paths.LOCALAPPDATA / "Packages" / m["family"] / "LocalCache" / "Roaming" / "Claude")
    return dirs


def is_running(data_dir: Path) -> bool:
    """Chromium keeps <user-data-dir>\\lockfile open (delete-on-close) while it runs."""
    return (data_dir / "lockfile").exists()


# --- icon source ---------------------------------------------------------------------------

def _png_size(path: Path):
    try:
        with open(path, "rb") as f:
            head = f.read(24)
        if head[:8] == b"\x89PNG\r\n\x1a\n":
            return struct.unpack(">II", head[16:24])
    except OSError:
        pass
    return None


@functools.lru_cache(maxsize=1)
def find_icon() -> Optional[str]:
    """A good square Claude logo from the install (smallest PNG that is >= 256 px)."""
    roots = []
    m = msix()
    if m:
        roots.append(Path(m["location"]) / "assets")
        roots.append(Path(m["location"]) / "Assets")
    if SQUIRREL_DIR.exists():
        ico = SQUIRREL_DIR / "app.ico"
        if ico.exists():
            return str(ico)
    candidates = []
    for root in roots:
        if not root.exists():
            continue
        for f in root.glob("*.png"):
            size = _png_size(f)
            if not size or size[0] != size[1]:
                continue
            name = f.name.lower()
            if "logo" not in name or "wide" in name:
                continue
            unplated = "unplated" in name
            candidates.append((size[0] >= 256, unplated, -abs(size[0] - 256), str(f)))
    if candidates:
        return max(candidates)[3]
    return None
