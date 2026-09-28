# Cross-platform core

This folder holds the part of Claude Loader (`claude-profiles`) that works the same on every
operating system. The OS-specific parts live in [`../linux`](../linux) and
[`../windows`](../windows). You don't run anything from here directly: each
OS installer copies this core next to its own part.

## Layout

`claude_profiles` is a Python **namespace package** without an `__init__.py`,
split across folders:

```
cross-platform/claude_profiles/core/     shared (this folder)
linux/claude_profiles/linux/             Ubuntu/Debian + GNOME, GTK 4 loader
windows/claude_profiles/windows/         Windows 10/11, Tk loader, tray agent
```

The installers merge them into one tree:

- Linux: `~/.local/share/claude-profiles/app/`
- Windows: `%LOCALAPPDATA%\claude-profiles\app\`

The program runs as `python -m claude_profiles.linux` or
`python -m claude_profiles.windows`.

| Module        | What it does                                                               |
| ------------- | -------------------------------------------------------------------------- |
| `config.py`   | Profile and loader settings, validation, load/save of `config.json`        |
| `security.py` | Password lock: salted PBKDF2-SHA256 hashes (a lock, not encryption)        |
| `icons.py`    | Pure-Python PNG/ICO reader and writer, resize, recolor to the profile color |
| `launch.py`   | Starting profiles, the CLI, password checks, `claude://` link routing      |
| `tui.py`      | Terminal setup wizard, manager and uninstaller                             |
| `cli.py`      | The `claude-profiles` command line                                         |
| `paths.py`    | Where things live on each OS                                               |
| `platform.py` | The `Platform` interface each OS implements                                |

## How a profile is isolated

Every profile that doesn't use the standard folders gets:

- `--user-data-dir=<data folder>/desktop`. Claude Desktop, an Electron app,
  keeps its settings, session and login there, so each profile is its own
  instance and they can run side by side.
- `CLAUDE_CONFIG_DIR=<data folder>/cli`. Claude Code keeps its login and
  settings there. The Desktop app's Code tab and the `claude-<id>` terminal
  command use the same folder, so they share one config per profile.

At most one profile may use the **standard folders**. It runs Claude exactly
as the normal shortcut does and keeps an existing login.

## Platform interface

`core.platform.Platform` is the only thing the core knows about an OS. An OS
package implements it:

- detecting and installing Claude Desktop, and checking for or applying
  updates;
- starting a profile, and telling which profiles are running;
- creating shortcuts or menu entries, icons, CLI commands, the hotkey and the
  `claude://` handler, and removing them again;
- hotkey format and validation;
- OS-specific wizard questions and uninstall steps;
- the GUI module (password prompt, profile chooser, loader).

## `config.json`

It's stored in `~/.config/claude-profiles/` on Linux and in
`%APPDATA%\claude-profiles\` on Windows. It's readable only by you on Linux.

```jsonc
{
  "profiles": [
    {
      "id": "work",               // used in file and command names (claude-work)
      "name": "Work",
      "color": "green",           // original, green, blue, purple, pink, yellow, teal, graphite
      "data_dir": "/home/me/.local/share/claude-profiles/profiles/work",
      "system_default": false,    // true = standard Claude folders
      "password": null,           // or {"algo": "pbkdf2-sha256", "iterations", "salt", "hash"}
      "cli": true,
      "desktop_dir": ""           // optional explicit Desktop data folder (adopted profiles)
    }
  ],
  "loader": {
    "enabled": true,
    "hotkey": "<Super><Shift>c",  // GNOME format on Linux, "Win+Shift+C" on Windows
    "password": null,
    "check_updates": true,
    "close_after_launch": true,
    "tray": true,                 // Windows tray agent
    "open_at_login": false,       // open the loader when you sign in
    "last_group": ["work", "side"] // profiles last started together ("Start group")
  },
  "autostart_profiles": ["work"], // profiles started when you sign in
  "url_handler": true,            // route claude:// links to the right profile
  "previous_url_handler": null,   // restored on uninstall
  "desktop_bin": null,            // override the detected Claude executable
  "window_class": true,           // Linux: --class so each profile gets its own dock icon
  "desktop_shortcuts": true,      // Windows: Desktop shortcuts
  "path_added": false,            // Windows: bin folder added to the user PATH
  "version": 1
}
```

Unknown keys are ignored, so older versions can read newer files.

## Adding another OS

Write `<os>/claude_profiles/<os>/` with a `Platform` subclass, a `gui` module
and a `__main__.py` that calls `core.cli.main(YourPlatform())`, plus an
installer that copies `core` next to it.
