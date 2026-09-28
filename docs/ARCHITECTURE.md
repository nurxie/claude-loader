# How Claude Loader is built

This is the reference for reading or changing the code. The per-OS pages
([Linux](../linux/README.md), [Windows](../windows/README.md)) tell you how to
*use* it; [`cross-platform/README.md`](../cross-platform/README.md) is the short
version of this page.

---

## 1. What the program is

One Python program, installed as `claude-profiles`, doing four jobs:

- an **installer** that puts Claude Desktop and the Claude Code CLI in place and
  walks you through creating profiles;
- a **launcher** — menu entries, shortcuts, a hotkey, `claude-<id>` commands;
- a **loader** — the window you press a hotkey for, plus a window of token
  figures;
- a **manager and uninstaller**.

It has no dependencies beyond the standard library and whatever GUI toolkit the
system already ships (GTK 4 + libadwaita on Linux, Tk on Windows; `sv-ttk` is
optional there). Nothing is downloaded at runtime except release checks and the
two account requests described in §6.

## 2. The two levers

Everything the project does rests on two settings that Claude already supports.
There is no patching, no injection, no private API:

| Lever | What it moves | Who reads it |
| --- | --- | --- |
| `--user-data-dir=<data>/desktop` | Claude Desktop's whole state: settings, session, login, MCP config, history | Electron, i.e. Claude Desktop |
| `CLAUDE_CONFIG_DIR=<data>/cli` | Claude Code's login, settings and transcripts | Claude Code — both the `claude-<id>` command and the Desktop app's Code tab |

Because the Desktop app's Code tab and the profile's terminal command get the
same `CLAUDE_CONFIG_DIR`, they share one Claude Code config per profile and
never mix with another profile's.

One profile may set `system_default: true`. It gets neither lever — it runs
Claude exactly as the normal shortcut does, and keeps a login you already have.
At most one profile can be that, and `Config.validate()` enforces it.

## 3. Shape of the code

`claude_profiles` is a **namespace package** (no `__init__.py`) deliberately
split across three folders:

```
cross-platform/claude_profiles/core/     shared
linux/claude_profiles/linux/             Ubuntu/Debian + GNOME
windows/claude_profiles/windows/         Windows 10/11
```

The installers copy `core` next to one OS folder, so the installed tree has
exactly two of the three. Tests instead put all three parent folders on
`sys.path`, which a namespace package merges by itself — that is all
`tests/context.py` does.

Two rules hold the design together:

1. **The core never imports OS code.** It talks to one object that implements
   `core.platform.Platform`.
2. **OS packages never import each other.**

So `python3 -m claude_profiles.linux` is three lines: build a `LinuxPlatform`
and hand it to `core.cli.main`.

### Core modules

| Module | What it owns |
| --- | --- |
| `config.py` | The `Profile` / `LoaderSettings` / `Config` dataclasses, validation, `config.json` load/save, migrations |
| `platform.py` | The interface every OS implements — the only thing the core knows about an OS |
| `paths.py` | Where everything lives, per OS |
| `launch.py` | Starting profiles, password checks, the CLI, `claude://` routing, sign-in autostart |
| `tui.py` | The terminal wizard, manager and uninstaller |
| `cli.py` | Argument parsing and dispatch |
| `icons.py` | A PNG/ICO reader and writer in pure Python, plus resize and recolour |
| `usage.py` | What the interface shows per profile, and the local token count behind it |
| `usage_online.py` | The account's own figures, and who a profile is signed in as |
| `security.py` | Password hashing for the launch lock |
| `selfupdate.py` | Finding and installing new releases of this program |

## 4. The Platform interface

`core.platform.Platform` is a plain class of `NotImplementedError` stubs and
harmless defaults. An OS package subclasses it. Grouped by what it covers:

- **Claude Desktop** — `installed_version`, `ensure_desktop_installed`,
  `check_update`, `run_update`, `uninstall_desktop`.
- **Claude Code CLI** — `cli_bin`, `install_cli`, `cli_install_hint`,
  `exec_cli`.
- **Processes** — `start_profile`, `running_profile_ids`.
- **Integration** — `apply` (create everything, return warnings), `remove_all`,
  `rebuild_icons`, `icon_png`.
- **Hotkeys** — `valid_hotkey`, `hotkey_problem`, `hotkey_label`,
  `hotkey_conflicts`, `hotkey_presets`.
- **Setup and uninstall hooks** — `setup_questions`, `loader_questions`,
  `legacy_profiles`, `after_setup`, `uninstall_extra`, `path_hint`,
  `finish_notes`, `doctor`, `open_terminal`.
- **Interface** — `gui()` (a module with `ask_password_blocking`,
  `choose_profile_blocking`, `run_loader`), `open_loader`,
  `has_usage_window` / `run_usage_window`, `run_agent`, `after_autostart`,
  `after_self_update`.

`apply(cfg)` is the important one: it must be **idempotent**. Every command that
changes anything calls it, and it brings the generated files and system settings
into line with the config, returning a list of warnings rather than raising.

## 5. What happens when

### Starting a profile

1. The loader card, menu entry, tray item or `claude-profiles launch <id>` calls
   `launch.cmd_launch`.
2. Already-running profiles are collected first: a profile that is running was
   unlocked when it started, so it is only focused, never asked again.
3. For the rest, `launch.unlock` asks for the password when the profile has one
   (a GUI prompt, or `getpass` with `--no-gui`).
4. `launch.prepare_dirs` creates `<data>/desktop` and `<data>/cli`.
5. `Platform.start_profile` builds the command line and environment and starts
   the process detached, with output appended to `<data dir>/logs/<id>.log`.

`launch.profile_env` also strips our own `PYTHONPATH` entry, so the launched app
never inherits the loader's import path.

### Routing a `claude://` link

Google sign-in returns through a `claude://` link, which by default always goes
to whichever Claude the system registered. With routing on, the system hands the
link to `claude-profiles open-url` instead:

1. `launch.valid_link` checks the scheme.
2. `launch.pick_profile_for_url` picks the target: the only running profile if
   there is exactly one; otherwise the GUI asks.
3. `launch.send_url` starts that profile *with the link as an argument*. If the
   profile is already running, Electron's single-instance handoff delivers it to
   the existing window.

The **Paste sign-in link** dialog is the manual version of the same call, and is
the reliable one on Windows (see §8).

### Reading token usage

`usage.collect_profile(profile, cfg)` puts together two sources.

**The account** (`usage_online`) is authoritative. It reads the OAuth token
Claude Code leaves in `<cli dir>/.credentials.json` when you sign in from the
terminal, and asks the endpoint the CLI's own `/usage` uses. That answer is the
only place two figures exist: how much of the five-hour window is gone, and the
exact moment it resets. Nothing on the machine knows either — a plan's allowance
is not written down anywhere.

**The transcripts on this PC** fill in what the answer does not carry. Claude
Code writes one JSON line per message into
`<cli dir>/projects/<project>/<session>.jsonl`, and each assistant line carries
that request's token counts and model. `usage.read_entries` reads them and
de-duplicates on `(message id, request id)`, because a resumed session is written
into more than one file. `usage.build_blocks` groups them into windows the way
Claude's limits work: a window opens with the first message, is stamped down to
the full hour, lasts five hours, and a five-hour silence also ends one.

`ProfileUsage` then decides what to show. The account wins wherever it answered;
the local count supplies the per-model breakdown and the message count, and
stands in entirely when the account cannot be reached. One rule is worth
knowing: a token budget you set by hand is **not** a figure on its own — with
nothing recorded locally, `share` stays `None` rather than reading "0 %" of a
window that may be half gone.

Failure is a sentence, never an exception reaching the interface.
`account_note` carries it, and the interesting case is a profile signed in only
through the Desktop app: that session lives in the app's own encrypted storage,
so there is no token to read. `usage_online.local_account` covers the gap for
identity — Claude Code records the account in `.claude.json` either way, so the
loader can still name every profile.

`usage.Alerts` holds the rule for warning near a limit, so both systems share it
and only have to raise a notification: it answers once per window, and the reset
time is what tells one window from the next.

Answers are cached — 45 s for limits, 15 min for identity — because the usage
window asks on a timer.

### Making icons

No Anthropic artwork ships with this project. `icons.py` reads the icon of the
**installed** Claude, recolours it and writes the result next to the config:

1. The OS layer finds a source (`system.find_icon` on Linux, `claude_app.find_icon`
   on Windows).
2. `icons.load_image` decodes it — PNG and ICO are handled by hand, SVG through
   GdkPixbuf where it exists.
3. `icons.resize` scales it, area-averaging when shrinking.
4. `icons.recolor` moves every coloured pixel to the profile's hue in HSV and
   leaves anything near-grey alone, so outlines and white stay put.
5. `icons.make_icon` writes a PNG, or an ICO with 256/48/32/16 px entries.

If no source can be read, `icons.fallback_disc` draws a plain coloured circle,
so a profile always has an icon. The colour is part of the file name, so the
system's icon caches notice a change.

### Updating itself

`selfupdate.check()` asks the GitHub API for the newest release, falls back to
the newest tag, and caches the answer for a day in `<data>/update.json`.

`selfupdate.install(url)` downloads the source archive and unpacks **only** the
`.py` files of `cross-platform/claude_profiles/core` and
`<os>/claude_profiles/<os>` into a staging folder, refusing anything that is too
large or whose path climbs out of the destination. It then swaps the directories,
keeping the old package until the swap has succeeded. `after_self_update` runs
`apply --quiet` in a fresh process, so the *new* code writes the shortcuts.

The Python environment, the `claude-profiles` command and `config.json` are
never touched, because a release does not change them. A release that does needs
the repository installer run again.

## 6. What leaves the machine

In normal use, four things — all plain HTTPS, all skippable. (Installing Claude
Desktop or the Claude Code CLI downloads from Anthropic too, but that only
happens when you ask the wizard for it.)

| Request | When | Why |
| --- | --- | --- |
| `api.github.com/repos/<repo>` | Once a day, if `check_app_updates` | Is there a newer Claude Loader |
| Anthropic's apt index (Linux) | When checking for Claude Desktop updates | The newest published version |
| `api.anthropic.com/api/oauth/usage` | Per profile, cached 45 s, if `usage_online` | The real limits and reset times |
| `api.anthropic.com/api/oauth/profile` | Per profile, cached 15 min, if `usage_online` | Which account the profile is |

The last two carry the profile's own OAuth token, the same one Claude Code
itself sends. It is read from the profile's folder for one request and never
written anywhere, logged, or shown. Both endpoints are settings
(`usage_url` / `profile_url`, or `CLAUDE_PROFILES_USAGE_URL` /
`CLAUDE_PROFILES_PROFILE_URL`) because they are not a documented public API and
may move. Set `usage_online` to false to stop asking at all.

## 7. `config.json`

Lives in `~/.config/claude-profiles/` (Linux) or `%APPDATA%\claude-profiles\`
(Windows), written through a temp file and `os.replace`, with mode `0600`
because it holds password hashes.

Reading is forgiving by design: unknown keys are dropped, so an older build can
read a newer file. `config._migrate` handles the other direction, keyed on
`version`:

- **1 → 2**: `usage_online` is turned on. The key changed meaning — it used to
  switch on an experimental extra, and is now how the figures are obtained at
  all, with its own fallback.

`Config.validate()` is the gate every save goes through: at most five profiles,
unique ids matching `[a-z0-9][a-z0-9-]{0,19}`, no two profiles sharing a data
folder, at most one `system_default`, absolute data paths, known colours, and
sane numbers.

`config.make_id` turns a display name into that id: lower-cased, every run of
anything but `a-z0-9` collapsed to `-`, trimmed, cut to 16 characters, made
unique with `-2`, `-3`, and stepped around the reserved `profiles` and
`desktop`. The display name itself is never touched.

## 8. Per-OS notes

### Linux (`claude_profiles.linux`)

- **Claude Desktop** comes from Anthropic's apt repository. The signing key is
  downloaded and its fingerprint checked against a constant before anything
  trusts it. Update checks parse the repository's `Packages` index directly, so
  they need no root; the update itself runs `apt-get install --only-upgrade`
  through `pkexec` or `sudo`.
- **Menu entries** are `.desktop` files in `~/.local/share/applications`, each
  carrying an `X-Claude-Profiles=true` marker. Nothing without that marker is
  ever modified or deleted; the same goes for the `claude-*` wrappers in
  `~/.local/bin`, which carry a comment marker.
- **The hotkey** is a GNOME custom keybinding written with `gsettings`.
  `hotkey_conflicts` reads the other custom bindings to warn about clashes. Two
  to four keys, at least one of Super/Ctrl/Alt.
- **`claude://`** is registered with `xdg-mime`, remembering whatever handled it
  before so uninstall can put it back.
- **Running profiles** are found by walking `/proc/*/cmdline`, matching
  `--user-data-dir` and skipping Electron helpers (`--type=`). A profile on the
  standard folders is matched by its executable instead.
- **The interface** is GTK 4 + libadwaita. Because Ubuntu 22.04 ships
  libadwaita 1.1, `compat.py` supplies stand-ins built from GTK 4.6 primitives
  for the widgets that arrived later — `ToolbarView`, `Banner`, the rows,
  `AlertDialog`, `AboutWindow`, `Gtk.FileDialog`. Each name is the real widget
  where it exists, so `gui.py` is written once against the newer API;
  `claude-profiles doctor` prints what is being stood in for.

### Windows (`claude_profiles.windows`)

- **Two kinds of install.** The MSIX (Store) build lives in the protected
  `WindowsApps` folder and cannot be started with a different data folder, so
  extra profiles run from a mirror in `%LOCALAPPDATA%\ClaudePortable`, refreshed
  with `robocopy` and stamped with a version marker. The older Squirrel install
  takes arguments directly and needs no copy.
- **Running profiles** are found by the `lockfile` Chromium keeps open in each
  data folder.
- **The tray agent** (`agent.py`) is pure `ctypes`: its own window class, a
  notification icon, `RegisterHotKey`, and a message loop. It owns the hotkey,
  offers a quick menu, re-reads the config when its mtime changes, and raises the
  near-the-limit warning, because it is the one process that outlives the
  windows.
- **`claude://`** is a `HKCU\Software\Classes\claude` registry key. Claude
  re-registers itself for that scheme every time it starts, so the agent puts the
  router back on each tick — which is why routing is off by default here and
  **Paste sign-in link** is the recommended path.
- **Shortcuts** are created through one PowerShell call driving `WScript.Shell`.
  Everything in the Start-menu folder is ours; on the Desktop only the paths
  recorded in `shortcuts.json` are ever removed.

## 9. Security

The password is a **lock, not encryption**. `security.py` stores a salted
PBKDF2-SHA256 hash (300 000 iterations) and the loader, menu entries and
`claude-<id>` commands check it before starting a profile. The profile's files
stay ordinary files owned by your user: anyone logged in as you can open them or
start Claude directly. It is for a shared or unattended screen, not for data
protection — that is what your login password and disk encryption are for.

`config.json` is written `0600` because the hashes live there.

## 10. Tests

`tests/` covers the parts that are pure functions — no network, no windows, no
Claude:

```bash
python3 -m unittest discover -s tests -t tests
```

| File | What it pins down |
| --- | --- |
| `test_icons.py` | PNG and ICO round-trips, greyscale/palette/filters the decoder must accept, resize, recolour leaving greys alone, the fallback disc |
| `test_usage.py` | Window grouping, the five-hour-gap rule, de-duplication of resumed sessions, which source wins, the alert rule, formatting |
| `test_usage_online.py` | The shapes the account's answer comes in, the identity fallback, telling "signed in elsewhere" from "never signed in", expired tokens |
| `test_config.py` | Id generation, every validation rule, groups, save/load, the 1 → 2 migration, file permissions |
| `test_hotkeys.py` | Both shortcut formats, and `.desktop` quoting |
| `test_security_and_updates.py` | The password lock, version comparison, and what a release archive is allowed to unpack |

GitHub Actions runs the suite on 3.10 and 3.12 and compiles every module.

## 11. Adding another OS

Write `<os>/claude_profiles/<os>/` with:

- `platform.py` — a `Platform` subclass;
- `gui.py` — a module with `ask_password_blocking`, `choose_profile_blocking`
  and `run_loader`;
- `__main__.py` — `sys.exit(core.cli.main(YourPlatform()))`;
- an installer that copies `cross-platform/claude_profiles/core` next to it.

Optionally a `usage_window` module plus `has_usage_window = True`; without it
`claude-profiles usage` still prints the table.

## 12. Known limits

- **Unofficial.** Claude Desktop does not support several accounts. This uses
  documented Electron and Claude Code settings, but a future app update could
  still break it.
- **A profile signed in only in the Claude app has no readable token**, so its
  percentages stay empty until `claude-<id>` is signed in once. Its identity
  still shows.
- **Desktop chat is not counted.** Claude Code records the CLI and the Code tab;
  chat in the app is not written anywhere we can read.
- **Windows `claude://` routing is a tug of war** with the app, which re-claims
  the scheme on every start.
- **Self-update replaces only the Python packages.** A release that changes the
  installer, the Python environment or the launcher command needs the repository
  installer run again.
