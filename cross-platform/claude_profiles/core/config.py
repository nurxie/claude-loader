"""Configuration model: profiles, loader settings, load/save."""

import json
import os
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import List, Optional

from . import paths

MAX_PROFILES = 5
CONFIG_VERSION = 1

# key -> (label, target hue in degrees or None, saturation factor, swatch)
# "original" keeps the icon as shipped.
COLORS = {
    "original": ("Original", None, 1.0, "#D97757"),
    "green":    ("Green",    140,  1.0, "#3FB871"),
    "blue":     ("Blue",     205,  1.0, "#3A9FE0"),
    "purple":   ("Purple",   270,  1.0, "#9B6BDF"),
    "pink":     ("Pink",     325,  1.0, "#E062A8"),
    "yellow":   ("Yellow",   48,   1.0, "#E0B53A"),
    "teal":     ("Teal",     172,  1.0, "#2FB5A5"),
    "graphite": ("Graphite", 0,    0.0, "#7A7A7A"),
}
DEFAULT_COLOR_ORDER = ["green", "blue", "purple", "pink", "yellow", "teal", "original", "graphite"]

# Hotkeys are stored in the native format of each OS.
DEFAULT_HOTKEY = "Win+Shift+C" if paths.IS_WINDOWS else "<Super><Shift>c"
RESERVED_IDS = {"profiles", "desktop"}


class ConfigError(Exception):
    pass


@dataclass
class Profile:
    id: str
    name: str
    color: str = "green"
    # Root folder for this profile's data. Empty when system_default is True.
    data_dir: str = ""
    # Use Claude's standard folders. Keeps an existing login. At most one profile.
    system_default: bool = False
    password: Optional[dict] = None
    cli: bool = True
    # Optional explicit Claude Desktop data folder, e.g. one adopted from the
    # older Windows script (%APPDATA%\Claude-Personal). Default: <data_dir>/desktop.
    desktop_dir: str = ""

    @property
    def desktop_data_dir(self) -> Optional[Path]:
        if self.system_default:
            return None
        return Path(self.desktop_dir) if self.desktop_dir else Path(self.data_dir) / "desktop"

    @property
    def cli_config_dir(self) -> Optional[Path]:
        return None if self.system_default else Path(self.data_dir) / "cli"

    @property
    def cli_command(self) -> str:
        return f"claude-{self.id}"

    @property
    def window_class(self) -> str:
        return f"claude-profile-{self.id}"

    @property
    def data_location(self) -> str:
        if self.system_default:
            return "standard Claude folders"
        if self.desktop_dir:
            return f"{paths.short(self.data_dir)} (app data: {paths.short(self.desktop_dir)})"
        return paths.short(self.data_dir)


@dataclass
class LoaderSettings:
    enabled: bool = True
    hotkey: Optional[str] = DEFAULT_HOTKEY
    password: Optional[dict] = None
    check_updates: bool = True
    close_after_launch: bool = True
    # Windows: background tray agent that owns the hotkey.
    tray: bool = True
    # Open the loader when you sign in to the computer.
    open_at_login: bool = False
    # Profiles last started together; preselected next time ("Start group").
    last_group: List[str] = field(default_factory=list)


@dataclass
class Config:
    profiles: List[Profile] = field(default_factory=list)
    loader: LoaderSettings = field(default_factory=LoaderSettings)
    # Send claude:// sign-in links to the profile that asked for them.
    url_handler: bool = True
    # Whatever handled claude:// before we took over (restored on uninstall).
    previous_url_handler: Optional[str] = None
    # Override for the Claude Desktop executable (normally auto-detected).
    desktop_bin: Optional[str] = None
    # Linux: pass --class so each profile gets its own dock icon.
    window_class: bool = True
    # Windows: also put profile shortcuts on the Desktop.
    desktop_shortcuts: bool = True
    # Windows: we added our bin folder to the user PATH (remove it on uninstall).
    path_added: bool = False
    # Profiles started automatically when you sign in to the computer.
    autostart_profiles: List[str] = field(default_factory=list)
    version: int = CONFIG_VERSION

    # --- lookup helpers -------------------------------------------------

    def get(self, profile_id: str) -> Profile:
        for p in self.profiles:
            if p.id == profile_id:
                return p
        raise ConfigError(f"No profile with id '{profile_id}'.")

    def system_default_profile(self) -> Optional[Profile]:
        for p in self.profiles:
            if p.system_default:
                return p
        return None

    def prune(self) -> None:
        """Forget ids of profiles that no longer exist (keeps profile order)."""
        ids = [p.id for p in self.profiles]
        self.autostart_profiles = [i for i in ids if i in self.autostart_profiles]
        self.loader.last_group = [i for i in ids if i in self.loader.last_group]

    def group(self) -> List[Profile]:
        """The remembered group, if it still has at least two profiles."""
        members = [p for p in self.profiles if p.id in self.loader.last_group]
        return members if len(members) >= 2 else []

    def group_label(self, max_len: int = 32) -> str:
        names = " + ".join(p.name for p in self.group())
        return names if len(names) <= max_len else names[:max_len - 1] + "…"

    def remember_group(self, ids: List[str]) -> bool:
        """Remember ids started together. Returns True if the saved group changed."""
        ordered = [p.id for p in self.profiles if p.id in ids]
        if len(ordered) < 2 or ordered == self.loader.last_group:
            return False
        self.loader.last_group = ordered
        return True

    def validate(self) -> None:
        if len(self.profiles) > MAX_PROFILES:
            raise ConfigError(f"At most {MAX_PROFILES} profiles are supported.")
        ids = [p.id for p in self.profiles]
        if len(ids) != len(set(ids)):
            raise ConfigError("Profile ids must be unique.")
        if sum(1 for p in self.profiles if p.system_default) > 1:
            raise ConfigError("Only one profile can use the standard Claude folders.")
        dirs = []
        for p in self.profiles:
            if not p.system_default:
                dirs.append(os.path.normcase(os.path.realpath(p.data_dir)))
                if p.desktop_dir:
                    dirs.append(os.path.normcase(os.path.realpath(p.desktop_dir)))
        if len(dirs) != len(set(dirs)):
            raise ConfigError("Two profiles cannot share a data folder.")
        for p in self.profiles:
            if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,19}", p.id) or p.id in RESERVED_IDS:
                raise ConfigError(f"Invalid profile id '{p.id}'.")
            if not p.name.strip():
                raise ConfigError("Profile names cannot be empty.")
            if p.color not in COLORS:
                raise ConfigError(f"Unknown color '{p.color}'.")
            if not p.system_default and not os.path.isabs(p.data_dir):
                raise ConfigError(f"Data folder of '{p.name}' must be an absolute path.")


# --- load / save ------------------------------------------------------------

def load() -> Optional[Config]:
    """Return the saved config, or None if claude-profiles is not set up."""
    try:
        raw = json.loads(paths.CONFIG_FILE.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as e:
        raise ConfigError(f"Cannot read {paths.CONFIG_FILE}: {e}")

    known_profile = set(Profile.__dataclass_fields__)
    known_loader = set(LoaderSettings.__dataclass_fields__)
    known_config = set(Config.__dataclass_fields__) - {"profiles", "loader"}

    cfg = Config(
        profiles=[Profile(**{k: v for k, v in p.items() if k in known_profile})
                  for p in raw.get("profiles", [])],
        loader=LoaderSettings(**{k: v for k, v in raw.get("loader", {}).items()
                                 if k in known_loader}),
        **{k: v for k, v in raw.items() if k in known_config},
    )
    cfg.validate()
    cfg.prune()
    return cfg


def save(cfg: Config) -> None:
    cfg.validate()
    cfg.prune()
    paths.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    tmp = paths.CONFIG_FILE.with_suffix(".tmp")
    # The file holds password hashes, so keep it private (no-op on Windows,
    # where the per-user AppData folder is already private).
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(asdict(cfg), f, indent=2)
        f.write("\n")
    os.replace(tmp, paths.CONFIG_FILE)


def mtime() -> float:
    try:
        return paths.CONFIG_FILE.stat().st_mtime
    except OSError:
        return 0.0


# --- helpers for creating profiles ------------------------------------------

DEFAULT_NAMES = ["Work", "Personal", "Profile 3", "Profile 4", "Profile 5"]


def make_id(name: str, taken) -> str:
    """Turn a display name into a short, unique id usable in file and command names."""
    base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:16].strip("-") or "profile"
    if base in RESERVED_IDS:
        base = f"{base}-1"
    candidate, n = base, 2
    while candidate in taken or candidate in RESERVED_IDS:
        candidate = f"{base}-{n}"
        n += 1
    return candidate


def default_name(cfg: Config) -> str:
    taken = {p.name.lower() for p in cfg.profiles}
    for n in DEFAULT_NAMES + [f"Profile {i}" for i in range(6, 10)]:
        if n.lower() not in taken:
            return n
    return "Profile"


def default_data_dir(profile_id: str) -> str:
    return str(paths.PROFILES_DIR / profile_id)


def next_color(cfg: Config) -> str:
    used = {p.color for p in cfg.profiles}
    for c in DEFAULT_COLOR_ORDER:
        if c not in used:
            return c
    return DEFAULT_COLOR_ORDER[0]


def color_label(key: str) -> str:
    return COLORS.get(key, (key,))[0]


def check_name(cfg: Config, name: str, profile: Optional[Profile] = None) -> Optional[str]:
    """Return an error message for an unusable profile name, else None."""
    name = name.strip()
    if not name:
        return "Enter a name."
    if len(name) > 40:
        return "Keep the name under 40 characters."
    if name.lower() in {p.name.lower() for p in cfg.profiles if p is not profile}:
        return "A profile with this name already exists."
    return None
