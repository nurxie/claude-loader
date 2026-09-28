"""Linux (Ubuntu/Debian, GNOME) implementation of the core Platform interface."""

import os
import shutil
import subprocess
from typing import List, Optional

from ..core import paths
from ..core.launch import profile_env
from ..core.platform import Platform
from . import integration, system


class LinuxPlatform(Platform):
    name = "linux"
    url_handler_default = True
    hotkey_presets = [("<Super><Shift>c", "Super+Shift+C"),
                      ("<Control><Alt>c", "Ctrl+Alt+C"),
                      ("<Super><Alt>c", "Super+Alt+C")]
    hotkey_custom_hint = "GNOME format, e.g. <Super><Alt>k"
    cli_install_hint = system.CLI_INSTALL

    # --- Claude Desktop ---------------------------------------------------------

    def installed_version(self) -> Optional[str]:
        return system.installed_version()

    def ensure_desktop_installed(self, ui) -> bool:
        version = system.installed_version()
        if version:
            print(ui.green(f"Claude Desktop {version} is installed."))
            return True
        print("Claude Desktop is not installed. It will be installed from Anthropic's official\n"
              "apt repository (https://code.claude.com/docs/en/desktop-linux). This needs sudo.")
        if not ui.yes_no("Install Claude Desktop now?", True):
            return False
        try:
            system.install_desktop(echo=lambda m: print(ui.cyan(m)))
        except (system.SystemError_, subprocess.CalledProcessError) as e:
            print(ui.red(f"Installation failed: {e}"))
            return False
        print(ui.green(f"Claude Desktop {system.installed_version()} installed."))
        return True

    def check_update(self) -> dict:
        return system.check_update()

    def run_update(self, cfg, gui: bool):
        if gui:
            r = subprocess.run(system.update_command(gui=True), text=True, capture_output=True)
            msg = (r.stderr or r.stdout).strip()[-300:]
        else:
            r = subprocess.run(system.update_command(gui=False))
            msg = ""
        system.package_files.cache_clear()
        return r.returncode == 0, msg

    def uninstall_desktop(self, ui) -> None:
        if system.installed_version() and ui.yes_no("Also uninstall Claude Desktop itself (sudo)?",
                                                    False):
            subprocess.run(["sudo", "apt-get", "remove", "-y", system.PACKAGE])

    # --- CLI ------------------------------------------------------------------------

    def cli_bin(self) -> Optional[str]:
        return system.cli_bin()

    def install_cli(self) -> None:
        system.install_cli()

    def exec_cli(self, exe: str, args: List[str], env: dict) -> None:
        os.execvpe(exe, [exe] + list(args), env)

    # --- processes ----------------------------------------------------------------------

    def desktop_command(self, cfg, profile, extra=None) -> List[str]:
        from ..core.launch import LaunchError
        exe = system.desktop_bin(cfg.desktop_bin)
        if not exe:
            raise LaunchError("Claude Desktop is not installed. Run `claude-profiles setup`.")
        cmd = [exe]
        if not profile.system_default:
            cmd.append(f"--user-data-dir={profile.desktop_data_dir}")
        if cfg.window_class:
            cmd.append(f"--class={profile.window_class}")
        return cmd + list(extra or [])

    def desktop_env(self, cfg, profile) -> dict:
        env = profile_env(profile)
        if cfg.window_class:
            env["CHROME_DESKTOP"] = f"{profile.window_class}.desktop"
        return env

    def start_profile(self, cfg, profile, extra=None) -> None:
        from ..core.launch import LaunchError
        paths.LOG_DIR.mkdir(parents=True, exist_ok=True)
        with open(paths.LOG_DIR / f"{profile.id}.log", "ab") as log:
            try:
                subprocess.Popen(self.desktop_command(cfg, profile, extra),
                                 env=self.desktop_env(cfg, profile),
                                 stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                                 start_new_session=True, cwd=str(paths.HOME))
            except OSError as e:
                raise LaunchError(f"Could not start Claude Desktop: {e}")

    def running_profile_ids(self, cfg) -> List[str]:
        return system.running_profile_ids(cfg)

    # --- integration ------------------------------------------------------------------------

    def apply(self, cfg) -> List[str]:
        return integration.apply(cfg)

    def remove_all(self, cfg) -> None:
        integration.remove_all(cfg)

    def rebuild_icons(self) -> None:
        integration.rebuild_icons()

    def icon_png(self, profile) -> str:
        return str(integration.icon_path(profile))

    def valid_hotkey(self, accel: str) -> bool:
        return integration.valid_hotkey(accel)

    def hotkey_problem(self, accel) -> Optional[str]:
        return integration.hotkey_problem(accel)

    def after_self_update(self, cfg) -> None:
        subprocess.Popen([str(paths.MAIN_CMD), "apply", "--quiet"], start_new_session=True,
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, cwd=str(paths.HOME))

    def hotkey_label(self, accel) -> str:
        return integration.hotkey_label(accel)

    def hotkey_conflicts(self, accel: str) -> List[str]:
        return integration.hotkey_conflicts(accel)

    def uninstall_extra(self, cfg, ui) -> None:
        for path in (paths.APP_DIR,):
            if path.exists():
                shutil.rmtree(path, ignore_errors=True)
        if paths.MAIN_CMD.exists():
            paths.MAIN_CMD.unlink()
        for path in (paths.PROFILES_DIR, paths.DATA_DIR):
            try:
                path.rmdir()
            except OSError:
                pass

    def path_hint(self) -> Optional[str]:
        if str(paths.BIN_DIR) not in os.environ.get("PATH", "").split(os.pathsep):
            return (f"{paths.short(paths.BIN_DIR)} is not on your PATH in this terminal. Log out "
                    "and back in (or open a new terminal) to use the claude-* commands.")
        return None

    def finish_notes(self, cfg) -> List[str]:
        notes = ["Your profiles are in the app menu as \"Claude (<name>)\"."]
        if cfg.loader.enabled:
            key = (f" or press {self.hotkey_label(cfg.loader.hotkey)}"
                   if cfg.loader.hotkey else "")
            notes.append(f"Open the loader from the menu (\"Claude Loader\"){key}.")
        return notes

    def doctor(self):
        st = system.desktop_status()
        rows = [("Claude Desktop version", st["version"] or "not installed"),
                ("Claude Desktop command", st["bin"] or "not found"),
                ("Package .desktop entry", st["entry"] or "not found"),
                ("Icon used for colors", st["icon"] or "not found (plain discs are used)"),
                ("Session", f"{os.environ.get('XDG_SESSION_TYPE', '?')} / "
                            f"{os.environ.get('XDG_CURRENT_DESKTOP', '?')}"),
                ("claude:// handler", integration.current_url_handler() or "unknown"),
                ("gsettings", shutil.which("gsettings") or "missing")]
        try:
            import gi
            gi.require_version("Gtk", "4.0")
            gi.require_version("Adw", "1")
            from gi.repository import Adw, Gtk
            rows.append(("GTK / libadwaita", f"{Gtk.get_major_version()}.{Gtk.get_minor_version()}"
                                             f" / {Adw.get_major_version()}.{Adw.get_minor_version()}"))
        except (ImportError, ValueError) as e:
            rows.append(("GTK / libadwaita", f"missing ({e})"))
        return rows

    def open_terminal(self, args: List[str]) -> bool:
        for term in (["gnome-terminal", "--"], ["kgx", "--"], ["x-terminal-emulator", "-e"]):
            if shutil.which(term[0]):
                subprocess.Popen(term + args, start_new_session=True)
                return True
        return False

    # --- UI ------------------------------------------------------------------------------------

    def gui(self):
        from . import gui
        return gui

    def open_loader(self) -> None:
        subprocess.Popen([str(paths.MAIN_CMD), "loader"], start_new_session=True,
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, cwd=str(paths.HOME))
