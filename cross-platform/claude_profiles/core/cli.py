"""Command line entry point shared by all systems: `claude-profiles <command>`."""

import argparse
import sys

from . import VERSION
from . import config as cfgmod
from . import launch, paths, tui


def _need_config():
    cfg = cfgmod.load()
    if cfg is None:
        print("claude-profiles is not set up yet. Run: claude-profiles setup", file=sys.stderr)
        sys.exit(1)
    return cfg


def cmd_doctor(plat) -> int:
    """Print what was detected; handy when something does not work."""
    print(f"claude-profiles {VERSION} ({plat.name})")
    for label, value in plat.doctor():
        print(f"{label:<23}: {value}")
    print(f"{'Claude Code CLI':<23}: {plat.cli_bin() or 'not installed'}")
    cfg = cfgmod.load()
    print(f"{'Config':<23}: {paths.CONFIG_FILE if cfg else 'not set up'}")
    if cfg:
        running = plat.running_profile_ids(cfg)
        for p in cfg.profiles:
            state = "running" if p.id in running else "stopped"
            print(f"  - {p.id:<12} {p.name:<16} {state:<8} {p.data_location}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="claude-profiles",
        description="Run several Claude Desktop / Claude Code accounts side by side. "
                    "Without a command, opens the setup (first run) or the manager.")
    parser.add_argument("--version", action="version", version=f"claude-profiles {VERSION}")
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("setup", help="first-time setup wizard")
    sub.add_parser("manage", help="terminal manager (add, edit, remove profiles...)")
    sub.add_parser("uninstall", help="remove claude-profiles")
    sub.add_parser("loader", help="open the graphical loader")
    p = sub.add_parser("launch", help="start one or more profiles")
    p.add_argument("ids", nargs="+", metavar="PROFILE_ID")
    p.add_argument("--no-gui", action="store_true", help="ask passwords in the terminal")
    p = sub.add_parser("cli", help="run Claude Code CLI with a profile")
    p.add_argument("id", metavar="PROFILE_ID")
    p.add_argument("args", nargs=argparse.REMAINDER)
    p = sub.add_parser("open-url", help="route a claude:// link to the right profile")
    p.add_argument("url")
    sub.add_parser("list", help="list profiles")
    p = sub.add_parser("apply", help="recreate shortcuts, icons, commands and hotkey")
    p.add_argument("--quiet", action="store_true")
    p = sub.add_parser("update", help="check for (and install) Claude Desktop updates")
    p.add_argument("--check", action="store_true", help="only check, do not install")
    sub.add_parser("doctor", help="show what was detected on this system")
    sub.add_parser("agent", help="background tray agent that owns the hotkey (Windows)")
    sub.add_parser("autostart", help="run at sign-in: start chosen profiles, open the loader")
    return parser


def main(plat, argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return run(plat, args) or 0
    except KeyboardInterrupt:
        print("\nCancelled.")
        return 130
    except (cfgmod.ConfigError, launch.LaunchError) as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


def run(plat, args) -> int:
    if args.command is None:
        return tui.run_manage(plat) if cfgmod.load() else tui.run_setup(plat)
    if args.command == "setup":
        return tui.run_setup(plat)
    if args.command == "manage":
        return tui.run_manage(plat)
    if args.command == "uninstall":
        return tui.run_uninstall(plat)
    if args.command == "doctor":
        return cmd_doctor(plat)

    cfg = _need_config()
    if args.command == "loader":
        if not cfg.loader.enabled:
            print("The loader is turned off. Turn it on with: claude-profiles manage",
                  file=sys.stderr)
            return 1
        return plat.gui().run_loader(plat)
    if args.command == "agent":
        return plat.run_agent()
    if args.command == "autostart":
        return launch.run_autostart(plat, cfg)
    if args.command == "launch":
        started = launch.cmd_launch(plat, cfg, args.ids, gui=not args.no_gui,
                                    report=lambda m: print(m, file=sys.stderr))
        return 0 if len(started) == len(args.ids) else 1
    if args.command == "cli":
        extra = args.args[1:] if args.args[:1] == ["--"] else args.args
        launch.cmd_cli(plat, cfg, args.id, extra)
        return 0
    if args.command == "open-url":
        return launch.cmd_open_url(plat, cfg, args.url)
    if args.command == "list":
        tui.print_profiles(cfg, plat.running_profile_ids(cfg))
        return 0
    if args.command == "apply":
        warnings = plat.apply(cfg)
        cfgmod.save(cfg)
        if not args.quiet:
            for w in warnings:
                print(f"! {w}")
            print("Shortcuts, icons and commands are up to date.")
        return 0
    if args.command == "update":
        result = plat.check_update()
        print(f"Installed: {result['installed'] or 'not installed'}   "
              f"Latest: {result.get('latest') or 'unknown'}")
        if result["available"]:
            print(result["message"])
            if not args.check:
                ok, msg = plat.run_update(cfg, gui=False)
                if not ok:
                    print(f"Failed: {msg}", file=sys.stderr)
                return 0 if ok else 1
        return 0
    return 1
