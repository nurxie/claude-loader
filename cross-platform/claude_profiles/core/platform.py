"""The interface between the cross-platform core and each operating system.

`claude_profiles.linux.platform.LinuxPlatform` and
`claude_profiles.windows.platform.WindowsPlatform` implement it. The core
(wizard, manager, launching, link routing) only talks to this interface.
"""

from typing import List, Optional, Sequence, Tuple


class Platform:
    name = "generic"
    # Shown in the wizard when asking about claude:// routing.
    url_handler_default = True
    url_handler_note = ""
    # (value, label) pairs offered by the wizard, and a hint for custom input.
    hotkey_presets: Sequence[Tuple[str, str]] = ()
    hotkey_custom_hint = ""

    # --- Claude Desktop --------------------------------------------------------

    def installed_version(self) -> Optional[str]:
        raise NotImplementedError

    def ensure_desktop_installed(self, ui) -> bool:
        """Make sure Claude Desktop is installed; may ask the user. True if usable."""
        raise NotImplementedError

    def check_update(self) -> dict:
        """{'installed', 'latest', 'available': bool, 'message', 'action'}"""
        raise NotImplementedError

    def run_update(self, cfg, gui: bool) -> Tuple[bool, str]:
        raise NotImplementedError

    def uninstall_desktop(self, ui) -> None:
        """Optionally remove Claude Desktop itself (asks first)."""

    # --- Claude Code CLI ---------------------------------------------------------

    def cli_bin(self) -> Optional[str]:
        raise NotImplementedError

    def install_cli(self) -> None:
        raise NotImplementedError

    cli_install_hint = ""

    # --- processes -----------------------------------------------------------------

    def start_profile(self, cfg, profile, extra: Optional[List[str]] = None) -> None:
        raise NotImplementedError

    def running_profile_ids(self, cfg) -> List[str]:
        raise NotImplementedError

    def exec_cli(self, exe: str, args: List[str], env: dict) -> None:
        """Run the CLI in the foreground and exit with its status."""
        raise NotImplementedError

    # --- desktop integration ----------------------------------------------------------

    def apply(self, cfg) -> List[str]:
        """Create/refresh menu entries, icons, commands, hotkey. Returns warnings."""
        raise NotImplementedError

    def remove_all(self, cfg) -> None:
        raise NotImplementedError

    def rebuild_icons(self) -> None:
        raise NotImplementedError

    def icon_png(self, profile) -> str:
        """Path of the profile's colored PNG icon (for the loader)."""
        raise NotImplementedError

    # --- hotkeys ---------------------------------------------------------------------

    def valid_hotkey(self, accel: str) -> bool:
        raise NotImplementedError

    def hotkey_label(self, accel: Optional[str]) -> str:
        return accel or "none"

    def hotkey_conflicts(self, accel: str) -> List[str]:
        return []

    # --- setup / uninstall hooks -----------------------------------------------------------

    def setup_questions(self, cfg, ui) -> None:
        """OS-specific questions asked by the setup wizard before saving."""

    def legacy_profiles(self) -> List[dict]:
        """Existing profile folders worth adopting: [{'name', 'desktop_dir', 'note'}]."""
        return []

    def after_setup(self, cfg, ui) -> None:
        """Clean-up offered after a successful setup (e.g. old shortcuts)."""

    def uninstall_extra(self, cfg, ui) -> None:
        """OS-specific removal steps (runs after remove_all)."""

    def path_hint(self) -> Optional[str]:
        return None

    def finish_notes(self, cfg) -> List[str]:
        return []

    def doctor(self) -> List[Tuple[str, str]]:
        return []

    def open_terminal(self, args: List[str]) -> bool:
        """Open a terminal window running `args`. False if not possible."""
        return False

    # --- user interface ----------------------------------------------------------------------

    def gui(self):
        """Module with ask_password_blocking, choose_profile_blocking, run_loader."""
        raise NotImplementedError

    def open_loader(self) -> None:
        """Start the loader as a separate process (used at sign-in)."""
        raise NotImplementedError

    def after_autostart(self, cfg) -> int:
        """Last step of `claude-profiles autostart`. Returns the exit code."""
        return 0

    def run_agent(self) -> int:
        raise NotImplementedError("There is no background agent on this system.")
