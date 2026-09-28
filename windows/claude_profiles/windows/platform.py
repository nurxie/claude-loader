"""Windows 10/11 implementation of the core Platform interface."""

import os
import shutil
import signal
import subprocess
import sys
from pathlib import Path
from typing import List, Optional

from ..core import paths
from ..core.launch import LaunchError, profile_env
from ..core.platform import Platform
from . import claude_app, hotkeys, integration, winutil

LEGACY_PROFILE_DIR = paths.APPDATA / "Claude-Personal"
LEGACY_SHORTCUTS = ("Claude TEAM.lnk", "Claude Personal.lnk")


class WindowsPlatform(Platform):
    name = "windows"
    url_handler_default = False
    url_handler_note = ("On Windows this is experimental: Claude registers claude:// for itself "
                        "each time it starts,\nso the tray agent keeps putting the router back. "
                        "The reliable way is the loader's\n\"Paste sign-in link\".")
    hotkey_presets = hotkeys.PRESETS
    hotkey_custom_hint = "e.g. Ctrl+Alt+K or Win+Alt+K"
    cli_install_hint = "irm https://claude.ai/install.ps1 | iex   (in PowerShell)"

    # --- Claude Desktop ---------------------------------------------------------

    def installed_version(self) -> Optional[str]:
        return claude_app.installed_version()

    def ensure_desktop_installed(self, ui) -> bool:
        while not claude_app.kind():
            print("Claude Desktop is not installed. Install it from the official page:\n"
                  f"  {claude_app.DOWNLOAD_URL}")
            if not ui.yes_no("Open the download page now?", True):
                return False
            os.startfile(claude_app.DOWNLOAD_URL)
            ui.ask("Install Claude, then press Enter here to continue")
            claude_app.refresh()
        kind = claude_app.kind()
        print(ui.green(f"Claude Desktop {claude_app.installed_version()} is installed "
                       f"({'Microsoft Store / MSIX' if kind == 'msix' else 'classic installer'})."))
        if kind == "msix" and not claude_app.copy_is_current():
            print("Extra profiles run from a copy of the app, because Windows does not allow\n"
                  "starting the Store version with a separate data folder.")
            try:
                claude_app.sync_copy(echo=lambda m: print(ui.cyan(m)))
            except OSError as e:
                print(ui.red(str(e)))
                return False
        return True

    def check_update(self) -> dict:
        claude_app.refresh()
        installed = claude_app.installed_version()
        kind = claude_app.kind()
        result = {"installed": installed, "latest": None, "available": False, "action": "",
                  "message": ""}
        if kind == "msix":
            copy = claude_app.copy_version()
            result["latest"] = installed
            if not claude_app.copy_is_current():
                result["available"] = True
                result["action"] = "Refresh copy"
                result["message"] = (f"Claude was updated to {installed}. The copy used by your "
                                     f"profiles is {'version ' + copy if copy else 'missing or unknown'}.")
            else:
                result["message"] = (f"Claude Desktop {installed}; the profile copy is up to date. "
                                     "Claude itself updates through the Microsoft Store.")
        elif kind == "squirrel":
            result["message"] = f"Claude Desktop {installed} updates itself."
        else:
            result["message"] = "Claude Desktop is not installed."
        return result

    def run_update(self, cfg, gui: bool):
        busy = [p.name for p in cfg.profiles
                if not p.system_default and p.id in self.running_profile_ids(cfg)]
        if busy:
            return False, f"Close these Claude windows first: {', '.join(busy)}"
        try:
            claude_app.sync_copy(echo=(lambda m: None) if gui else print)
        except OSError as e:
            return False, str(e)
        return True, ""

    def uninstall_desktop(self, ui) -> None:
        print(ui.dim("Claude Desktop itself was not removed (Settings > Apps if you want to)."))

    # --- CLI ------------------------------------------------------------------------

    def cli_bin(self) -> Optional[str]:
        found = shutil.which("claude")
        if found and "claude_profiles" not in found:
            return found
        return str(paths.NATIVE_CLI) if paths.NATIVE_CLI.exists() else None

    def install_cli(self) -> None:
        subprocess.run(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command",
                        "irm https://claude.ai/install.ps1 | iex"])

    def exec_cli(self, exe: str, args: List[str], env: dict) -> None:
        # Ctrl+C belongs to the CLI; this process only waits for it.
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        sys.exit(subprocess.call([exe] + list(args), env=env))

    # --- processes ----------------------------------------------------------------------

    def start_profile(self, cfg, profile, extra=None) -> None:
        extra = list(extra or [])
        if profile.system_default:
            cmd = (claude_app.default_url_command(extra[0]) if extra
                   else claude_app.default_start_command())
            env = profile_env(profile)
        else:
            exe = Path(cfg.desktop_bin) if cfg.desktop_bin else claude_app.profile_exe()
            if not exe or not exe.exists():
                if claude_app.kind() == "msix":
                    raise LaunchError("The Claude copy for profiles is missing or outdated. "
                                      "Open the loader and click \"Refresh copy\", or run "
                                      "`claude-profiles update`.")
                raise LaunchError("Claude Desktop is not installed.")
            cmd = [str(exe), f"--user-data-dir={profile.desktop_data_dir}"] + extra
            env = profile_env(profile)
        if not cmd:
            raise LaunchError("Claude Desktop is not installed.")
        paths.LOG_DIR.mkdir(parents=True, exist_ok=True)
        try:
            winutil.start_detached(cmd, env=env, cwd=str(paths.HOME),
                                   log_path=paths.LOG_DIR / f"{profile.id}.log")
        except OSError as e:
            raise LaunchError(f"Could not start Claude Desktop: {e}")

    def running_profile_ids(self, cfg) -> List[str]:
        ids = []
        for p in cfg.profiles:
            dirs = claude_app.default_data_dirs() if p.system_default else [p.desktop_data_dir]
            if any(claude_app.is_running(d) for d in dirs):
                ids.append(p.id)
        return ids

    # --- integration ------------------------------------------------------------------------

    def apply(self, cfg) -> List[str]:
        warnings = integration.apply(cfg)
        if claude_app.kind() == "msix" and not claude_app.copy_is_current() and any(
                not p.system_default for p in cfg.profiles):
            warnings.append("The Claude copy for profiles is outdated. Refresh it from the "
                            "loader or with `claude-profiles update`.")
        return warnings

    def remove_all(self, cfg) -> None:
        integration.remove_all(cfg)

    def rebuild_icons(self) -> None:
        integration.rebuild_icons()

    def icon_png(self, profile) -> str:
        return str(integration.icon_png(profile))

    def valid_hotkey(self, accel: str) -> bool:
        return hotkeys.parse(accel) is not None

    def hotkey_label(self, accel) -> str:
        return hotkeys.normalize(accel) or "none"

    def hotkey_conflicts(self, accel: str) -> List[str]:
        from ..core import config as cfgmod
        cfg = cfgmod.load()
        ours = cfg and cfg.loader.hotkey and hotkeys.normalize(cfg.loader.hotkey) == hotkeys.normalize(accel)
        if ours and integration.agent_running():
            return []
        return [] if hotkeys.is_free(accel) else ["another program (or Windows itself)"]

    # --- setup hooks -------------------------------------------------------------------------

    def legacy_profiles(self) -> List[dict]:
        if LEGACY_PROFILE_DIR.is_dir() and any(LEGACY_PROFILE_DIR.iterdir()):
            return [{"name": "Personal", "desktop_dir": str(LEGACY_PROFILE_DIR),
                     "note": "It was created by the older two-account script (\"Claude Personal\")."}]
        return []

    def setup_questions(self, cfg, ui) -> None:
        ui.header("Windows options")
        cfg.desktop_shortcuts = ui.yes_no("Also put the profile shortcuts on the Desktop?", True)
        if any(p.cli for p in cfg.profiles):
            cfg.path_added = ui.yes_no(f"Add {paths.short(paths.BIN_DIR)} to your user PATH so "
                                       "the claude-<name> commands work in any terminal?", True)
        if cfg.loader.enabled:
            print("A small tray agent starts when you sign in to Windows. It owns the hotkey\n"
                  "and offers a quick menu to start profiles.")
            cfg.loader.tray = ui.yes_no("Use the tray agent?", True)

    def after_setup(self, cfg, ui) -> None:
        try:
            desk = integration.desktop_dir()
        except OSError:
            return
        old = [desk / n for n in LEGACY_SHORTCUTS if (desk / n).exists()]
        if old and ui.yes_no("Remove the old \"Claude TEAM\" / \"Claude Personal\" shortcuts from "
                             "the Desktop? The new ones replace them.", True):
            for f in old:
                try:
                    f.unlink()
                except OSError as e:
                    ui.warn(f"Could not remove {f.name}: {e}")

    def uninstall_extra(self, cfg, ui) -> None:
        if claude_app.PORTABLE_DIR.exists() and ui.yes_no(
                f"Also delete the app copy in {paths.short(claude_app.PORTABLE_DIR)}? "
                "(Only needed by claude-profiles and the older two-account script.)", True):
            shutil.rmtree(claude_app.PORTABLE_DIR, ignore_errors=True)
        for f in (integration.MANIFEST, integration.AGENT_STOP):
            if f.exists():
                f.unlink()
        # The running Python lives in the venv, so delete it after this process exits.
        targets = [paths.VENV_DIR, paths.APP_DIR, paths.BIN_DIR, paths.ICON_DIR]
        cmd = "ping 127.0.0.1 -n 8 >nul"
        for t in targets:
            cmd += f' & if exist "{t}" rmdir /s /q "{t}"'
        cmd += f' & rmdir "{paths.DATA_DIR}" 2>nul & rmdir "{paths.PROFILES_DIR}" 2>nul'
        subprocess.Popen(["cmd.exe", "/c", cmd], creationflags=winutil.CREATE_NO_WINDOW
                         | winutil.DETACHED_PROCESS, close_fds=True)

    def path_hint(self) -> Optional[str]:
        on_path = str(paths.BIN_DIR).lower() in os.environ.get("PATH", "").lower()
        if not on_path:
            return ("Open a new terminal window to use the claude-* commands "
                    "(the PATH change applies to new windows).")
        return None

    def finish_notes(self, cfg) -> List[str]:
        notes = ["Your profiles are in the Start menu under \"Claude Profiles\""
                 + (" and on the Desktop." if cfg.desktop_shortcuts else ".")]
        if cfg.loader.enabled:
            key = (f" or press {self.hotkey_label(cfg.loader.hotkey)}"
                   if cfg.loader.hotkey and cfg.loader.tray else "")
            notes.append(f"Open the loader from the Start menu (\"Claude Loader\"){key}.")
        return notes

    def doctor(self):
        m = claude_app.msix()
        rows = [("Claude Desktop", f"{claude_app.installed_version() or 'not installed'} "
                                   f"({claude_app.kind() or '-'})")]
        if m:
            rows.append(("Package family", m["family"]))
            rows.append(("Profile copy", f"{paths.short(claude_app.PORTABLE_DIR)} version "
                                         f"{claude_app.copy_version() or 'unknown'}"))
        rows += [("Exe for profiles", str(claude_app.profile_exe() or "not found")),
                 ("Icon used for colors", claude_app.find_icon() or "not found (plain discs)"),
                 ("Python", sys.executable),
                 ("Tray agent", "running" if integration.agent_running() else "not running"),
                 ("claude:// handler", integration.current_url_command() or "not registered")]
        try:
            import sv_ttk  # noqa: F401
            rows.append(("Theme", "sv-ttk (Windows 11 style)"))
        except ImportError:
            rows.append(("Theme", "standard ttk (sv-ttk not installed)"))
        return rows

    def open_terminal(self, args: List[str]) -> bool:
        subprocess.Popen(["cmd.exe", "/k"] + args, creationflags=subprocess.CREATE_NEW_CONSOLE)
        return True

    # --- UI -----------------------------------------------------------------------------------

    def gui(self):
        from . import gui
        return gui

    def run_agent(self) -> int:
        from . import agent
        return agent.run(self)

    def open_loader(self) -> None:
        winutil.start_detached([winutil.pythonw(), "-m", "claude_profiles.windows", "loader"],
                               cwd=str(paths.HOME))

    def after_autostart(self, cfg) -> int:
        # The sign-in process simply becomes the tray agent.
        if cfg.loader.enabled and cfg.loader.tray:
            return self.run_agent()
        return 0
