"""Terminal installer, manager and uninstaller (shared by all systems)."""

import os
import shutil
import sys
from typing import List, Optional, Sequence, Tuple

from . import VERSION
from . import config as cfgmod
from . import launch, paths, security
from .config import Config, LoaderSettings, Profile


def _enable_ansi() -> bool:
    if not sys.stdout.isatty():
        return False
    if paths.IS_WINDOWS:
        try:  # turn on VT processing in the Windows console
            import ctypes
            k32 = ctypes.windll.kernel32
            h = k32.GetStdHandle(-11)
            mode = ctypes.c_uint32()
            if k32.GetConsoleMode(h, ctypes.byref(mode)):
                k32.SetConsoleMode(h, mode.value | 0x0004)
        except Exception:
            return False
    return True


_TTY = _enable_ansi()


def _c(code: str, text: str) -> str:
    return f"\033[{code}m{text}\033[0m" if _TTY else text


def bold(t): return _c("1", t)
def dim(t): return _c("2", t)
def green(t): return _c("32", t)
def yellow(t): return _c("33", t)
def red(t): return _c("31", t)
def cyan(t): return _c("36", t)


def header(title: str) -> None:
    print()
    print(bold(cyan(f"== {title} ==")))


def warn(msg: str) -> None:
    print(yellow(f"! {msg}"))


def info(msg: str) -> None:
    print(msg)


# --- prompts ------------------------------------------------------------------------

def ask(prompt: str, default: Optional[str] = None) -> str:
    suffix = f" [{default}]" if default else ""
    try:
        value = input(f"{prompt}{suffix}: ").strip()
    except EOFError:
        print()
        raise KeyboardInterrupt
    return value or (default or "")


def yes_no(prompt: str, default: bool = True) -> bool:
    hint = "Y/n" if default else "y/N"
    while True:
        value = ask(f"{prompt} ({hint})").lower()
        if not value:
            return default
        if value in ("y", "yes"):
            return True
        if value in ("n", "no"):
            return False
        print("Please answer y or n.")


def choose(prompt: str, options: Sequence[Tuple[str, str]], default: int = 0) -> str:
    """Numbered menu. Returns the key of the chosen option."""
    print(prompt)
    for i, (_, label) in enumerate(options, 1):
        marker = "*" if i - 1 == default else " "
        print(f"  {marker}{i}) {label}")
    while True:
        value = ask("Choose", str(default + 1))
        if value.isdigit() and 1 <= int(value) <= len(options):
            return options[int(value) - 1][0]
        print(f"Enter a number from 1 to {len(options)}.")


def ask_int(prompt: str, lo: int, hi: int, default: int) -> int:
    while True:
        value = ask(f"{prompt} ({lo}-{hi})", str(default))
        if value.isdigit() and lo <= int(value) <= hi:
            return int(value)
        print(f"Enter a number from {lo} to {hi}.")


def new_password(what: str) -> Optional[dict]:
    import getpass
    while True:
        try:
            first = getpass.getpass(f"New password for {what} (empty to cancel): ")
        except EOFError:
            return None
        if not first:
            return None
        second = getpass.getpass("Repeat the password: ")
        if first == second:
            return security.hash_password(first)
        print(red("The passwords do not match, try again."))


# --- pieces of the wizard -----------------------------------------------------------

def pick_color(default: str) -> str:
    options = [(k, v[0]) for k, v in cfgmod.COLORS.items()]
    keys = [k for k, _ in options]
    return choose("Icon color:", options, keys.index(default))


def _same_path(a, b) -> bool:
    return os.path.normcase(os.path.realpath(a)) == os.path.normcase(os.path.realpath(b))


def pick_data_dir(cfg: Config, pid: str, first: bool) -> Tuple[bool, str]:
    """Returns (system_default, data_dir)."""
    own = cfgmod.default_data_dir(pid)
    options = []
    std_exists = paths.DEFAULT_DESKTOP_DATA.exists()
    if not cfg.system_default_profile():
        note = " - keeps your current login" if std_exists else ""
        options.append(("std", f"Standard Claude folders ({paths.short(paths.DEFAULT_DESKTOP_DATA)}, "
                               f"{paths.short(paths.DEFAULT_CLI_DIR)}){note}"))
    options.append(("own", f"Separate folder: {paths.short(own)}"))
    options.append(("custom", "Separate folder at a location I choose"))
    keys = [k for k, _ in options]
    default = 0 if (first and keys[0] == "std" and std_exists) else keys.index("own")
    choice = choose("Where should this profile keep its data (login, settings, history)?",
                    options, default)
    if choice == "std":
        return True, ""
    if choice == "own":
        return False, own
    taken = [p.data_dir for p in cfg.profiles if not p.system_default]
    while True:
        value = ask("Folder path", paths.short(own))
        path = os.path.abspath(os.path.expandvars(os.path.expanduser(value)))
        if any(_same_path(path, t) for t in taken):
            print(red("Another profile already uses this folder."))
            continue
        if _same_path(path, paths.DEFAULT_DESKTOP_DATA) or _same_path(path, paths.DEFAULT_CLI_DIR):
            print(red("Pick the 'Standard Claude folders' option for that instead."))
            continue
        if os.path.exists(path) and os.listdir(path):
            warn("This folder is not empty; existing data in it will be used.")
        return False, path


def ask_profile(cfg: Config, index: int, want_cli: bool, legacy: Optional[dict] = None) -> Profile:
    header(f"Profile {index + 1}" + (f" (from {paths.short(legacy['desktop_dir'])})" if legacy else ""))
    default_name = legacy["name"] if legacy else cfgmod.default_name(cfg)
    if cfgmod.check_name(cfg, default_name):
        default_name = cfgmod.default_name(cfg)
    while True:
        name = ask("Name", default_name)
        error = cfgmod.check_name(cfg, name)
        if not error:
            break
        print(red(error))
    name = name.strip()
    pid = cfgmod.make_id(name, {p.id for p in cfg.profiles})
    color = pick_color(cfgmod.next_color(cfg))
    if legacy:
        system_default, data_dir = False, cfgmod.default_data_dir(pid)
    else:
        system_default, data_dir = pick_data_dir(cfg, pid, first=index == 0)
    password = None
    if yes_no("Protect this profile with a password?", False):
        password = new_password(f'"{name}"')
    profile = Profile(id=pid, name=name, color=color, data_dir=data_dir,
                      system_default=system_default, password=password, cli=want_cli,
                      desktop_dir=legacy["desktop_dir"] if legacy else "")
    if want_cli:
        print(dim(f"  Terminal command for this profile: {profile.cli_command}"))
    return profile


def pick_hotkey(plat, current: Optional[str]) -> Optional[str]:
    options = list(plat.hotkey_presets) + [("custom", f"Custom ({plat.hotkey_custom_hint})"),
                                           ("none", "No hotkey")]
    keys = [k for k, _ in options]
    if current in keys:
        default = keys.index(current)
    else:
        default = keys.index("custom" if current else "none")
    choice = choose("Hotkey that opens the loader:", options, default)
    if choice == "none":
        return None
    if choice == "custom":
        while True:
            value = ask("Shortcut", current or "")
            if plat.valid_hotkey(value):
                choice = value
                break
            print(red(f"Not a valid shortcut. Example: {plat.hotkey_custom_hint}"))
    conflicts = plat.hotkey_conflicts(choice)
    if conflicts:
        warn(f"{plat.hotkey_label(choice)} is also used by: {', '.join(conflicts)}")
    return choice


def ask_loader(plat, loader: LoaderSettings) -> LoaderSettings:
    header("Claude Loader")
    print("The loader is a small window that shows all profiles. Click one to start it,\n"
          "or hold the mouse button on a profile to select several and start them together.\n"
          "It also checks for Claude Desktop updates and lets you edit profiles.")
    loader.enabled = yes_no("Install the loader?", True)
    if not loader.enabled:
        loader.hotkey = None
        return loader
    loader.hotkey = pick_hotkey(plat, loader.hotkey)
    if yes_no("Protect the loader with a password?", bool(loader.password)):
        loader.password = new_password("the loader") or loader.password
    else:
        loader.password = None
    loader.check_updates = yes_no("Check for Claude Desktop updates when the loader opens?",
                                  loader.check_updates)
    loader.check_app_updates = yes_no("Also look for new Claude Loader versions? "
                                      "(It only tells you; it never installs by itself.)",
                                      loader.check_app_updates)
    plat.loader_questions(loader, sys.modules[__name__])
    return loader


def ask_autostart(cfg: Config) -> None:
    """Two separate choices: open the loader at sign-in, and start profiles at sign-in."""
    header("At sign-in")
    if cfg.loader.enabled:
        cfg.loader.open_at_login = yes_no("Open the loader automatically when you sign in?",
                                          cfg.loader.open_at_login)
    if not yes_no("Start some Claude profiles automatically when you sign in?",
                  bool(cfg.autostart_profiles)):
        cfg.autostart_profiles = []
        return
    chosen = []
    for p in cfg.profiles:
        default = p.id in cfg.autostart_profiles if cfg.autostart_profiles else True
        if yes_no(f"  Start \"{p.name}\" at sign-in?", default):
            chosen.append(p.id)
    cfg.autostart_profiles = chosen
    if any(cfg.get(i).password for i in chosen):
        print(dim("  Profiles with a password will ask for it right after you sign in."))


def autostart_summary(cfg: Config) -> str:
    parts = []
    if cfg.loader.enabled and cfg.loader.open_at_login:
        parts.append("loader")
    parts += [cfg.get(i).name for i in cfg.autostart_profiles]
    return ", ".join(parts) if parts else "nothing"


def explain_url_handler(plat) -> None:
    print("\"Continue with Google\" returns to Claude through a claude:// link. Normally that\n"
          "link always goes to the standard Claude window, so the other profiles never\n"
          "receive the login. claude-profiles can take over claude:// links and send\n"
          "each one to the profile that is running (or ask which one, if several are).")
    if plat.url_handler_note:
        print(plat.url_handler_note)


def ensure_cli_installed(plat) -> None:
    if plat.cli_bin():
        return
    print("Claude Code CLI is not installed. Official installer:\n  " + plat.cli_install_hint)
    if yes_no("Install it now?", True):
        try:
            plat.install_cli()
        except Exception as e:
            print(red(f"CLI installation failed: {e}"))


def apply_and_save(plat, cfg: Config) -> None:
    cfgmod.save(cfg)
    warnings = plat.apply(cfg)
    cfgmod.save(cfg)  # apply() may record things like the previous claude:// handler
    for w in warnings:
        warn(w)


def path_hint(plat) -> None:
    hint = plat.path_hint()
    if hint:
        warn(hint)


def print_profiles(cfg: Config, running: Optional[List[str]] = None) -> None:
    running = running or []
    if not cfg.profiles:
        print(dim("  (no profiles)"))
    for i, p in enumerate(cfg.profiles, 1):
        flags = []
        if p.password:
            flags.append("password")
        if p.cli:
            flags.append(p.cli_command)
        if p.id in running:
            flags.append(green("running"))
        print(f"  {i}. {bold(p.name):<20} {cfgmod.color_label(p.color):<9} "
              f"{dim(p.data_location)}  {' '.join(flags)}")


# --- setup ---------------------------------------------------------------------------

def _is_root() -> bool:
    return hasattr(os, "geteuid") and os.geteuid() == 0


def run_setup(plat) -> int:
    header("Claude Loader setup")
    print("This sets up several Claude Desktop accounts that can run at the same time,\n"
          f"each with its own window, icon color and data folder (up to {cfgmod.MAX_PROFILES}).\n"
          "Unofficial tool, not affiliated with Anthropic.")
    if _is_root():
        print(red("Run this as your normal user, not with sudo."))
        return 1
    existing = cfgmod.load()
    if existing and existing.profiles:
        warn("claude-profiles is already set up.")
        if yes_no("Open the manager instead?", True):
            return run_manage(plat)
        if not yes_no("Start over? Existing profile data folders are kept on disk.", False):
            return 0
        plat.remove_all(existing)

    header("Step 1: Claude Desktop")
    if not plat.ensure_desktop_installed(sys.modules[__name__]):
        print(red("Claude Desktop is required. Nothing was changed."))
        return 1

    header("Step 2: Claude Code CLI")
    print("Each profile can also get a terminal command, like claude-work, that runs the\n"
          "Claude Code CLI signed in to that profile's account.")
    want_cli = yes_no("Create terminal commands for the profiles?", True)
    if want_cli:
        ensure_cli_installed(plat)

    header("Step 3: Profiles")
    cfg = Config()
    for legacy in plat.legacy_profiles():
        print(f"Found {paths.short(legacy['desktop_dir'])}. {legacy.get('note', '')}")
        if yes_no("Use it as one of your profiles? It keeps its login.", True):
            cfg.profiles.append(ask_profile(cfg, len(cfg.profiles), want_cli, legacy))
    remaining = cfgmod.MAX_PROFILES - len(cfg.profiles)
    default_more = max(0, 2 - len(cfg.profiles))
    if cfg.profiles:
        count = ask_int("How many more profiles do you want", 0, remaining, default_more)
    else:
        count = ask_int("How many Claude profiles do you want", 1, remaining, 2)
    for _ in range(count):
        cfg.profiles.append(ask_profile(cfg, len(cfg.profiles), want_cli))
    if not cfg.profiles:
        print(red("At least one profile is needed. Nothing was changed."))
        return 1

    cfg.loader = ask_loader(plat, LoaderSettings())
    ask_autostart(cfg)

    header("Sign-in links")
    explain_url_handler(plat)
    cfg.url_handler = yes_no("Route claude:// links to the right profile?", plat.url_handler_default)

    plat.setup_questions(cfg, sys.modules[__name__])

    header("Summary")
    print_profiles(cfg)
    if cfg.loader.enabled:
        print(f"  Loader: yes, hotkey {plat.hotkey_label(cfg.loader.hotkey)}"
              f"{', password' if cfg.loader.password else ''}")
    else:
        print("  Loader: no")
    print(f"  At sign-in: {autostart_summary(cfg)}")
    print(f"  claude:// routing: {'on' if cfg.url_handler else 'off'}")
    if not yes_no("Create everything now?", True):
        print("Cancelled, nothing was changed.")
        return 0

    apply_and_save(plat, cfg)
    plat.after_setup(cfg, sys.modules[__name__])
    header("Done")
    for note in plat.finish_notes(cfg):
        print(note)
    print(bold("First sign-in in each profile:") +
          " type your e-mail and use the code Claude sends you.\n"
          "That always works. \"Continue with Google\" returns through a claude:// link;\n"
          + ("with routing on, the link goes to the running profile (or you are asked which)."
             if cfg.url_handler else
             "you can paste that link into the loader (menu > Paste sign-in link)."))
    print(f"Manage later with: {bold('claude-profiles')}")
    path_hint(plat)
    return 0


# --- manager ---------------------------------------------------------------------------

def select_profile(cfg: Config, prompt: str) -> Optional[Profile]:
    if not cfg.profiles:
        print("There are no profiles.")
        return None
    options = [(p.id, p.name) for p in cfg.profiles] + [("", "Back")]
    pid = choose(prompt, options, 0)
    return cfg.get(pid) if pid else None


def edit_profile(plat, cfg: Config) -> None:
    profile = select_profile(cfg, "Which profile?")
    if not profile:
        return
    while True:
        header(f"Edit {profile.name}")
        print(f"  Data: {profile.data_location}")
        options = [("name", f"Name: {profile.name}"),
                   ("color", f"Color: {cfgmod.color_label(profile.color)}"),
                   ("password", f"Password: {'set' if profile.password else 'none'}"),
                   ("cli", f"Terminal command {profile.cli_command}: "
                           f"{'on' if profile.cli else 'off'}"),
                   ("done", "Save and go back")]
        choice = choose("Change:", options, len(options) - 1)
        if choice == "name":
            new = ask("New name", profile.name)
            error = cfgmod.check_name(cfg, new, profile)
            if error:
                print(red(error))
            else:
                profile.name = new.strip()
        elif choice == "color":
            profile.color = pick_color(profile.color)
        elif choice == "password":
            if profile.password and yes_no("Remove the password?", False):
                profile.password = None
            else:
                profile.password = new_password(f'"{profile.name}"') or profile.password
        elif choice == "cli":
            profile.cli = not profile.cli
            if profile.cli:
                ensure_cli_installed(plat)
        else:
            apply_and_save(plat, cfg)
            print(green("Saved."))
            return


def add_profile(plat, cfg: Config) -> None:
    if len(cfg.profiles) >= cfgmod.MAX_PROFILES:
        print(red(f"You already have {cfgmod.MAX_PROFILES} profiles, the maximum."))
        return
    want_cli = any(p.cli for p in cfg.profiles) if cfg.profiles else True
    profile = ask_profile(cfg, len(cfg.profiles), want_cli)
    cfg.profiles.append(profile)
    apply_and_save(plat, cfg)
    print(green(f"Added \"{profile.name}\"."))


def delete_folder(path) -> None:
    try:
        shutil.rmtree(path)
        print(green(f"Deleted {paths.short(path)}"))
    except OSError as e:
        print(red(f"Could not delete {paths.short(path)}: {e}"))


def profile_folders(profile) -> List[str]:
    """Folders that belong only to this profile (never the standard ones)."""
    if profile.system_default:
        return []
    folders = [profile.data_dir]
    if profile.desktop_dir:
        folders.append(profile.desktop_dir)
    return [f for f in folders if os.path.exists(f)]


def remove_profile(plat, cfg: Config) -> None:
    profile = select_profile(cfg, "Remove which profile?")
    if not profile:
        return
    if profile.id in plat.running_profile_ids(cfg):
        warn(f"\"{profile.name}\" is running. Close its window first to be safe.")
    if not yes_no(f"Remove the profile \"{profile.name}\" (menu entry, icon, command)?", False):
        return
    folders = profile_folders(profile)
    delete_data = False
    if folders:
        delete_data = yes_no(f"Also delete its data ({', '.join(paths.short(f) for f in folders)})? "
                             "This permanently deletes that account's login, settings and "
                             "history on this PC.", False)
    cfg.profiles.remove(profile)
    apply_and_save(plat, cfg)
    if delete_data:
        for f in folders:
            delete_folder(f)
    print(green(f"Removed \"{profile.name}\"."))


def loader_menu(plat, cfg: Config) -> None:
    ask_loader(plat, cfg.loader)
    if cfg.loader.enabled:
        cfg.loader.close_after_launch = yes_no("Close the loader after starting a profile?",
                                               cfg.loader.close_after_launch)
    apply_and_save(plat, cfg)
    print(green("Loader settings saved."))


def check_updates_menu(plat, cfg) -> None:
    print("Checking for updates...")
    try:
        result = plat.check_update()
    except Exception as e:  # network errors, missing tools...
        print(red(f"Could not check for updates: {e}"))
        return
    print(f"  Installed: {result['installed'] or 'not installed'}")
    if result.get("latest"):
        print(f"  Latest:    {result['latest']}")
    if not result["available"]:
        print(green(result.get("message") or "Claude Desktop is up to date."))
        return
    print(result["message"])
    warn("Close all Claude windows first.")
    if yes_no(f"{result.get('action', 'Update')} now?", True):
        ok, msg = plat.run_update(cfg, gui=False)
        print(green("Done.") if ok else red(f"Failed: {msg}"))


def usage_menu(cfg) -> None:
    from . import usage as usagemod
    header("Token usage")
    for line in usagemod.text_report(cfg):
        print(line)


def self_update_menu(plat, check_only: bool = False) -> int:
    """Look for a newer Claude Loader on GitHub and, if asked, install it."""
    from . import selfupdate
    print("Looking for a newer Claude Loader...")
    try:
        info = selfupdate.check(force=True)
    except selfupdate.UpdateError as e:
        print(red(f"Could not check for updates: {e}"))
        return 1
    print(f"  Installed: {info['current']}")
    print(f"  Latest:    {info['latest'] or 'unknown'}")
    if not info["available"]:
        print(green(info["message"]))
        return 0
    print(yellow(info["message"]))
    if info["notes"]:
        print()
        print(dim(info["notes"][:800]))
        print()
    if check_only:
        print(f"Install it with: {bold('claude-profiles self-update')}   ({info['page']})")
        return 0
    print(f"It replaces the program in {paths.short(paths.APP_DIR)}. Your profiles, settings\n"
          "and logins are not touched.")
    if not yes_no(f"Download and install {info['latest']} now?", True):
        return 0
    try:
        selfupdate.install(info["url"])
    except selfupdate.UpdateError as e:
        print(red(f"Update failed: {e}"))
        return 1
    print(green(f"Claude Loader {info['latest']} is installed."))
    cfg = cfgmod.load()
    if cfg is not None:
        plat.after_self_update(cfg)
    warn("Close and reopen the loader to use the new version.")
    return 0


def run_manage(plat) -> int:
    while True:
        cfg = cfgmod.load()
        if cfg is None:
            print("claude-profiles is not set up yet.")
            return run_setup(plat)
        header(f"Claude Loader {VERSION}")
        version = plat.installed_version()
        print(f"Claude Desktop: {version or red('not installed')}")
        print_profiles(cfg, plat.running_profile_ids(cfg))
        loader = (f"on, hotkey {plat.hotkey_label(cfg.loader.hotkey)}"
                  if cfg.loader.enabled else "off")
        print(dim(f"  Loader: {loader}.  At sign-in: {autostart_summary(cfg)}.  "
                  f"claude:// routing: {'on' if cfg.url_handler else 'off'}."))
        group = cfg.group()
        if group:
            print(dim(f"  Last group: {cfg.group_label(60)}"))
        options = []
        if len(cfg.profiles) < cfgmod.MAX_PROFILES:
            options.append(("add", "Add a profile"))
        options += [("edit", "Edit a profile"),
                    ("remove", "Remove a profile"),
                    ("launch", "Start a profile"),
                    ("link", "Send a sign-in link (claude://...) to a profile"),
                    ("loader", "Loader and hotkey settings"),
                    ("autostart", "What starts when you sign in"),
                    ("url", f"Turn claude:// routing {'off' if cfg.url_handler else 'on'}"),
                    ("usage", "Token usage per profile"),
                    ("update", "Check for Claude Desktop updates"),
                    ("selfupdate", "Check for Claude Loader updates"),
                    ("repair", "Recreate shortcuts, icons and commands"),
                    ("uninstall", "Uninstall claude-profiles"),
                    ("quit", "Quit")]
        choice = choose("What do you want to do?", options, len(options) - 1)
        if choice == "quit":
            return 0
        if choice == "add":
            add_profile(plat, cfg)
        elif choice == "edit":
            edit_profile(plat, cfg)
        elif choice == "remove":
            remove_profile(plat, cfg)
        elif choice == "launch":
            profile = select_profile(cfg, "Start which profile?")
            if profile:
                launch.cmd_launch(plat, cfg, [profile.id], gui=False, report=warn)
        elif choice == "link":
            url = ask("Paste the claude:// link")
            if not launch.valid_link(url):
                print(red("That is not a claude:// link."))
            else:
                profile = select_profile(cfg, "Send it to which profile?")
                if profile and launch.send_url(plat, cfg, profile, url, gui=False):
                    print(green(f"Link sent to \"{profile.name}\"."))
        elif choice == "loader":
            loader_menu(plat, cfg)
        elif choice == "autostart":
            ask_autostart(cfg)
            apply_and_save(plat, cfg)
            print(green(f"At sign-in: {autostart_summary(cfg)}."))
        elif choice == "url":
            if not cfg.url_handler:
                explain_url_handler(plat)
            cfg.url_handler = not cfg.url_handler
            apply_and_save(plat, cfg)
        elif choice == "usage":
            usage_menu(cfg)
        elif choice == "update":
            check_updates_menu(plat, cfg)
        elif choice == "selfupdate":
            self_update_menu(plat)
        elif choice == "repair":
            plat.rebuild_icons()
            apply_and_save(plat, cfg)
            print(green("Shortcuts, icons and commands recreated."))
        elif choice == "uninstall":
            if run_uninstall(plat) == 0:
                return 0


# --- uninstall ---------------------------------------------------------------------------

def run_uninstall(plat) -> int:
    header("Uninstall claude-profiles")
    cfg = None
    try:
        cfg = cfgmod.load()
    except cfgmod.ConfigError as e:
        warn(str(e))
    print("This removes the shortcuts, the loader, the hotkey, the icons, the claude-*\n"
          "terminal commands and the claude-profiles program itself.")
    if not yes_no("Continue?", False):
        return 1

    owned = [(p, profile_folders(p)) for p in (cfg.profiles if cfg else [])]
    owned = [(p, f) for p, f in owned if f]
    delete_data = False
    if owned:
        print("Profile data folders (logins, settings, history):")
        for p, folders in owned:
            print(f"  {p.name}: {', '.join(paths.short(f) for f in folders)}")
        delete_data = yes_no("Delete these folders too? This cannot be undone.", False)
        if delete_data:
            delete_data = ask("Type DELETE to confirm") == "DELETE"
            if not delete_data:
                print("Keeping the data folders.")

    plat.remove_all(cfg)
    plat.uninstall_extra(cfg, sys.modules[__name__])
    if delete_data:
        for _, folders in owned:
            for f in folders:
                delete_folder(f)
    for path in (paths.CONFIG_DIR / "config.json", paths.LOG_DIR):
        if path.is_dir():
            shutil.rmtree(path, ignore_errors=True)
        elif path.exists():
            path.unlink()
    for path in (paths.PROFILES_DIR, paths.CONFIG_DIR):
        try:
            path.rmdir()  # only if empty
        except OSError:
            pass
    print(green("claude-profiles has been removed."))
    if not delete_data and owned:
        print(dim("Profile data folders were kept."))
    print(dim("Standard Claude folders were not touched."))
    plat.uninstall_desktop(sys.modules[__name__])
    return 0
