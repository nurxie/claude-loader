# Cross-platform core

This folder holds the part of Claude Loader (`claude-profiles`) that works the same on every
operating system. For the full picture - what happens when you start a profile,
where the token figures come from, what each system does differently - see
[docs/ARCHITECTURE.md](../docs/ARCHITECTURE.md). The OS-specific parts live in [`../linux`](../linux) and
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

| Module            | What it does                                                               |
| ----------------- | -------------------------------------------------------------------------- |
| `config.py`       | Profile and loader settings, validation, load/save of `config.json`        |
| `security.py`     | Password lock: salted PBKDF2-SHA256 hashes (a lock, not encryption)        |
| `icons.py`        | Pure-Python PNG/ICO reader and writer, resize, recolor to the profile color |
| `launch.py`       | Starting profiles, the CLI, password checks, `claude://` link routing      |
| `tui.py`          | Terminal setup wizard, manager and uninstaller                             |
| `cli.py`          | The `claude-profiles` command line                                         |
| `paths.py`        | Where things live on each OS                                               |
| `platform.py`     | The `Platform` interface each OS implements                                |
| `selfupdate.py`   | Looking for and installing new Claude Loader releases                      |
| `usage.py`        | What the interface shows per profile: the account's figures, and the local count behind them |
| `usage_online.py` | The real limits and reset times, asked from each profile's own account     |

### Updating Claude Loader itself

`selfupdate.check()` asks the GitHub API for the newest release (falling back
to the newest tag) and caches the answer in `<data>/update.json` for a day.
`selfupdate.install(url)` downloads the source archive and unpacks **only** the
Python files of `cross-platform/claude_profiles/core` and
`<os>/claude_profiles/<os>` into a staging folder beside the installed one,
then swaps the directories, keeping the old package until the swap has worked.
`Platform.after_self_update()` then runs `apply --quiet` in a fresh process so
the new code writes the shortcuts.

The Python environment, the `claude-profiles` command and `config.json` are
never touched, because a release does not change them. A release that does
needs the repository installer to be run again.

### Where the token figures come from

The percentages and the reset times come from the account, not from this
machine: `usage_online.py` reads the OAuth token Claude Code leaves in the
profile's own folder (`.credentials.json`) when you sign in to the CLI, and asks
the same endpoint the CLI's `/usage` uses. A profile signed in only through the
Desktop app has no such file - that session lives inside the app's own encrypted
storage - so its figures stay local until `claude-<id>` is signed in once.
`local_account()` covers the gap for identity: Claude Code records the account
in `.claude.json` either way, so every profile can still say who it is. Nothing local can know either figure - a plan's allowance is not
written down anywhere, and neither is the moment a five-hour window resets.
Answers are cached for `CACHE_SECONDS` because the usage window asks on a timer.

`usage.py` supplies what that answer does not carry. Claude Code writes one
JSON line per message into `<config dir>/projects/<project>/<session>.jsonl`,
and each assistant line carries that request's token counts and model.
`usage.py` reads them, de-duplicates on `(message id, request id)` because a
resumed session is written to more than one file, and groups them into
five-hour windows the way Claude's limits work: a window opens with the first
message, is stamped to the full hour and lasts five hours, and a five-hour gap
also ends one.

So a profile's row is the account's percentage and reset time, with the local
count naming the models behind it. When the account cannot be reached - the
profile was never started, the sign-in expired, no network - `ProfileUsage`
falls back to the local estimate against `usage_limit` / `usage_weekly_limit`,
or the busiest window seen so far, and `account_note` says in one sentence why.

The local count covers the Claude Code CLI and the Desktop app's Code tab,
which share a profile's config folder, but not Desktop chat, which Claude Code
does not record.

The same answer says **who** a profile is signed in as: `usage_online.identity`
reads the profile endpoint and returns an `Account` (e-mail, organization,
plan). The loader puts it under each profile's name, which is how you tell five
profiles apart, and `duplicates()` spots two profiles that ended up in the same
account.

`usage.Alerts` holds the rule for warning when a window is nearly full, so both
systems share it and only have to know how to raise a notification: it answers
once per window, and the reset time is what tells one window from the next. On
Linux the loader and the usage window raise it; on Windows the tray agent does,
because it is the process that outlives them.

Set `usage_online` to false to stop asking the account at all, and
`usage_alert_percent` to 0 to stop the warnings.

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
      "desktop_dir": "",          // optional explicit Desktop data folder (adopted profiles)
      "usage_limit": 0,           // tokens per 5-hour window; 0 = learn it from history
      "usage_weekly_limit": 0     // tokens per rolling 7 days; 0 = no bar
    }
  ],
  "loader": {
    "enabled": true,
    "hotkey": "<Super><Shift>c",  // GNOME format on Linux, "Win+Shift+C" on Windows
    "password": null,
    "check_updates": true,        // look for Claude Desktop updates
    "check_app_updates": true,    // look for new Claude Loader releases
    "close_after_launch": true,
    "tray": true,                 // Windows tray agent
    "open_at_login": false,       // open the loader when you sign in
    "desktop_shortcut": false,    // Windows: a Desktop shortcut for the loader itself
    "last_group": ["work", "side"] // profiles last started together ("Start group")
  },
  "autostart_profiles": ["work"], // profiles started when you sign in
  "url_handler": true,            // route claude:// links to the right profile
  "previous_url_handler": null,   // restored on uninstall
  "desktop_bin": null,            // override the detected Claude executable
  "window_class": true,           // Linux: --class so each profile gets its own dock icon
  "desktop_shortcuts": true,      // Windows: Desktop shortcuts for the profiles
  "path_added": false,            // Windows: bin folder added to the user PATH
  "usage_online": true,           // ask the account for the real limits and reset times
  "usage_url": "",                // where the limits request goes, if it ever moves
  "profile_url": "",              // where the "who is this" request goes
  "usage_alert_percent": 90,      // warn at this much of a 5-hour window; 0 = never
  "version": 2
}
```

Unknown keys are ignored, so older versions can read newer files. `version` is
what `config._migrate` reads: a file written before version 2 has its
`usage_online` turned on, because the key changed meaning (it used to switch on
an experimental extra; it is now how the figures are obtained at all).

## Tests

`tests/` covers the parts that are pure functions - the PNG and ICO codecs, the
window grouping and de-duplication, the shapes the account's answer comes in,
the config rules and migration, the password lock, the shortcut formats of both
systems and what a release archive is allowed to unpack. No network, no
windows, no Claude:

```bash
python3 -m unittest discover -s tests -t tests
```

`tests/context.py` puts `cross-platform/`, `linux/` and `windows/` on the path,
which is all a namespace package needs, so the suite runs against the working
tree on any system. GitHub Actions runs it on 3.10 and 3.12.

## Adding another OS

Write `<os>/claude_profiles/<os>/` with a `Platform` subclass, a `gui` module
and a `__main__.py` that calls `core.cli.main(YourPlatform())`, plus an
installer that copies `core` next to it. A `usage_window` module and
`has_usage_window = True` add the token window; without them `claude-profiles
usage` still prints the table.
