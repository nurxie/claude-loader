"""Starting profiles: Claude Desktop windows, the CLI, and claude:// links."""

import getpass
import os
import sys
from typing import Callable, List, Optional

from . import paths, security


class LaunchError(Exception):
    pass


def clean_env(env: Optional[dict] = None) -> dict:
    """Copy of the environment without our own Python path settings."""
    env = dict(os.environ if env is None else env)
    pp = env.get("PYTHONPATH")
    if pp:
        app = os.path.normcase(str(paths.APP_DIR))
        parts = [p for p in pp.split(os.pathsep) if p and os.path.normcase(p) != app]
        if parts:
            env["PYTHONPATH"] = os.pathsep.join(parts)
        else:
            env.pop("PYTHONPATH", None)
    return env


def profile_env(profile, env: Optional[dict] = None) -> dict:
    """Environment for a profile: its own Claude Code config folder.

    The Desktop app's Code tab uses the same config folder as the CLI, so both
    get CLAUDE_CONFIG_DIR and a profile never mixes settings with another one.
    """
    env = clean_env(env)
    if profile.system_default:
        env.pop("CLAUDE_CONFIG_DIR", None)
    else:
        env["CLAUDE_CONFIG_DIR"] = str(profile.cli_config_dir)
    return env


def prepare_dirs(profile) -> None:
    if not profile.system_default:
        profile.desktop_data_dir.mkdir(parents=True, exist_ok=True)
        profile.cli_config_dir.mkdir(parents=True, exist_ok=True)


# --- passwords ----------------------------------------------------------------------

def terminal_unlock(title: str, record: dict, attempts: int = 3) -> bool:
    for _ in range(attempts):
        try:
            pw = getpass.getpass(f"Password for {title}: ")
        except (EOFError, KeyboardInterrupt):
            print()
            return False
        if security.verify_password(pw, record):
            return True
        print("Wrong password.", file=sys.stderr)
    return False


def unlock(plat, profile, gui: bool) -> bool:
    if not profile.password:
        return True
    title = f"Claude ({profile.name})"
    if gui:
        return plat.gui().ask_password_blocking(
            title, lambda pw: security.verify_password(pw, profile.password))
    return terminal_unlock(title, profile.password)


# --- commands -----------------------------------------------------------------------

def cmd_launch(plat, cfg, ids: List[str], gui: bool = True,
               unlocked: Optional[set] = None, report: Callable[[str], None] = None) -> List[str]:
    """Launch profiles by id. Returns the ids that were started.

    `unlocked` holds ids whose password was already checked (the loader passes it).
    """
    started = []
    running = set(plat.running_profile_ids(cfg))
    for pid in ids:
        profile = cfg.get(pid)
        # An already running profile was unlocked when it started; just focus it.
        if pid not in running and pid not in (unlocked or set()):
            if not unlock(plat, profile, gui):
                if report:
                    report(f"{profile.name}: wrong password, not started.")
                continue
        prepare_dirs(profile)
        plat.start_profile(cfg, profile)
        started.append(pid)
    return started


def cmd_cli(plat, cfg, profile_id: str, args: List[str]) -> None:
    profile = cfg.get(profile_id)
    if not unlock(plat, profile, gui=False):
        sys.exit(1)
    exe = plat.cli_bin()
    if not exe:
        raise LaunchError("Claude Code CLI is not installed. Install it with:\n  "
                          + plat.cli_install_hint)
    if not profile.system_default:
        profile.cli_config_dir.mkdir(parents=True, exist_ok=True)
    plat.exec_cli(exe, args, profile_env(profile))


def pick_profile_for_url(plat, cfg, running: Optional[List[str]] = None):
    """Which profile should receive a claude:// link? None if the user cancelled."""
    running = plat.running_profile_ids(cfg) if running is None else running
    if len(running) == 1:
        return cfg.get(running[0])
    candidates = [cfg.get(i) for i in running] if running else list(cfg.profiles)
    if len(candidates) == 1:
        return candidates[0]
    if not candidates:
        return None
    return plat.gui().choose_profile_blocking(
        candidates, "Which Claude profile should receive this sign-in link?")


def valid_link(url: str) -> bool:
    return url.strip().strip('"').startswith("claude://")


def send_url(plat, cfg, profile, url: str, gui: bool = True, unlocked: bool = False) -> bool:
    """Hand a claude:// link to one profile.

    A running instance with the same data folder receives it through Electron's
    single-instance handoff; otherwise the profile starts with the link.
    `unlocked=True` means the caller already checked the password.
    """
    url = url.strip().strip('"')
    if (not unlocked and profile.id not in plat.running_profile_ids(cfg)
            and not unlock(plat, profile, gui)):
        return False
    prepare_dirs(profile)
    plat.start_profile(cfg, profile, [url])
    return True


def run_autostart(plat, cfg) -> int:
    """Run at sign-in: start the chosen profiles, open the loader, then OS extras
    (on Windows this process continues as the tray agent)."""
    ids = [p.id for p in cfg.profiles if p.id in cfg.autostart_profiles]
    if ids:
        try:
            cmd_launch(plat, cfg, ids, gui=True)
        except LaunchError as e:
            print(f"Autostart: {e}", file=sys.stderr)
    if cfg.loader.enabled and cfg.loader.open_at_login:
        plat.open_loader()
    return plat.after_autostart(cfg)


def cmd_open_url(plat, cfg, url: str) -> int:
    if not valid_link(url):
        print(f"Not a claude:// link: {url}", file=sys.stderr)
        return 2
    if not cfg.profiles:
        return 1
    profile = pick_profile_for_url(plat, cfg)
    if profile is None:
        return 1
    return 0 if send_url(plat, cfg, profile, url) else 1
