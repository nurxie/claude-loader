"""File system locations used by claude-profiles, per operating system."""

import os
import sys
from pathlib import Path

IS_WINDOWS = sys.platform == "win32"
NAME = "claude-profiles"
HOME = Path.home()

if IS_WINDOWS:
    APPDATA = Path(os.environ.get("APPDATA") or HOME / "AppData" / "Roaming")
    LOCALAPPDATA = Path(os.environ.get("LOCALAPPDATA") or HOME / "AppData" / "Local")
    CONFIG_DIR = APPDATA / NAME
    DATA_DIR = LOCALAPPDATA / NAME
    PROFILES_DIR = APPDATA / NAME / "profiles"   # roams like Claude's own data
    BIN_DIR = DATA_DIR / "bin"
    MAIN_CMD = BIN_DIR / f"{NAME}.cmd"
    VENV_DIR = DATA_DIR / "venv"
    DEFAULT_DESKTOP_DATA = APPDATA / "Claude"
    NATIVE_CLI = HOME / ".local" / "bin" / "claude.exe"
else:
    XDG_CONFIG = Path(os.environ.get("XDG_CONFIG_HOME") or HOME / ".config")
    XDG_DATA = Path(os.environ.get("XDG_DATA_HOME") or HOME / ".local" / "share")
    CONFIG_DIR = XDG_CONFIG / NAME
    DATA_DIR = XDG_DATA / NAME
    PROFILES_DIR = DATA_DIR / "profiles"
    BIN_DIR = HOME / ".local" / "bin"
    MAIN_CMD = BIN_DIR / NAME
    DEFAULT_DESKTOP_DATA = XDG_CONFIG / "Claude"
    NATIVE_CLI = BIN_DIR / "claude"

CONFIG_FILE = CONFIG_DIR / "config.json"
APP_DIR = DATA_DIR / "app"        # installed copy of this program
ICON_DIR = DATA_DIR / "icons"     # generated, recolored icons
LOG_DIR = DATA_DIR / "logs"       # output of launched Claude instances
DEFAULT_CLI_DIR = HOME / ".claude"


def short(path) -> str:
    """Show a path the way the user would type it (~ or %APPDATA%)."""
    p = str(path)
    if IS_WINDOWS:
        for base, label in ((LOCALAPPDATA, "%LOCALAPPDATA%"), (APPDATA, "%APPDATA%"),
                            (HOME, "%USERPROFILE%")):
            b = str(base)
            if p.lower() == b.lower():
                return label
            if p.lower().startswith(b.lower() + os.sep):
                return label + p[len(b):]
        return p
    home = str(HOME)
    if p == home:
        return "~"
    if p.startswith(home + os.sep):
        return "~" + p[len(home):]
    return p
