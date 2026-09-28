# Claude Loader for Windows 10/11

Run **up to 5 Claude Desktop accounts at the same time** on one Windows PC.
Each account gets its own window, its own colored Claude icon, its own data
folder and, if you want, its own password and its own Claude Code terminal
command.

Claude Loader is one program with several jobs. Its command is
`claude-profiles`:

- **Installer:** finds Claude Desktop, prepares the copy that extra profiles
  run from, and walks you through creating profiles.
- **Manager:** add, edit, recolor, lock or remove profiles, from the terminal
  or from the loader.
- **Loader:** a window that opens with a hotkey (default `Win+Shift+C`). Click
  a profile to start it. Hold the mouse button to select several and start them
  together. It also keeps the profile copy of Claude up to date.
- **Tray agent:** a small background helper that owns the hotkey and offers a
  quick "Start …" menu in the notification area.
- **Uninstaller:** removes everything it created. It asks before it deletes any
  profile data.

> **Unofficial.** Not affiliated with or endorsed by Anthropic. Claude Desktop
> doesn't officially support several accounts. This uses Electron's standard
> `--user-data-dir` option, and a future app update could break it.

Only need two accounts and no installation? See the
[legacy two-shortcut script](legacy/README.md).

---

## Requirements

- Windows 10 or 11.
- Claude Desktop, from the Microsoft Store / MSIX or the classic installer:
  [claude.ai/download](https://claude.ai/download).
- Python 3.10+ with Tkinter. If it's missing, the installer offers to install
  Python 3.12 for your user with `winget`.

The installer creates a private Python environment in
`%LOCALAPPDATA%\claude-profiles\venv`. It installs one optional package there,
[`sv-ttk`](https://pypi.org/project/sv-ttk/), which gives the Windows 11 look.
Without it, the standard Windows theme is used.

---

## Install

1. Get the whole repository. The installer needs both `windows\` and
   `cross-platform\`.
2. Double-click **`windows\Install.cmd`**. If SmartScreen shows a blue warning,
   click **More info**, then **Run anyway**.
3. The setup wizard asks:
   1. **Claude Desktop.** If it's missing, the wizard opens the official
      download page. With the Store version it copies the app to
      `%LOCALAPPDATA%\ClaudePortable`, which is about 700 MB and takes a minute.
      See [why](#why-a-copy-of-claude).
   2. **Terminal commands.** Whether each profile gets a `claude-<name>`
      command for the Claude Code CLI. If the CLI is missing, the wizard offers
      the official installer.
   3. **An existing profile.** If you used the legacy script, it offers to
      take over `%APPDATA%\Claude-Personal` as a profile, and its login is kept.
   4. **Profiles (1 to 5).** For each: a **name**, an **icon color**, a **data
      folder** and an optional **password**. The data folder can be the
      standard Claude folder (only one profile can use it, and it keeps your
      current login), a separate folder under
      `%APPDATA%\claude-profiles\profiles\<id>`, or a folder you choose.
   5. **Loader.** Whether to install it, which **hotkey** opens it, and an
      optional loader **password**.
   6. **Sign-in link routing.** Experimental on Windows. See
      [Signing in](#signing-in).
   7. **Windows options.** Desktop shortcuts, whether to put `claude-<name>` on
      your PATH, and the tray agent.
   8. **Clean-up.** It offers to remove the old "Claude TEAM" / "Claude
      Personal" Desktop shortcuts.

To update `claude-profiles` later, get the new files and run `Install.cmd`
again. Profiles and settings are kept.

---

## Using it

### Shortcuts

Each profile appears in the Start menu under **Claude Profiles** as
**Claude (Name)** with its own colored icon. If you chose it, the shortcut is
on the Desktop too. Pin them to the taskbar or Start like any other shortcut.

### The loader

Open it with the hotkey, the tray icon or **Claude Profiles › Claude Loader**.

| Action                                          | Result                                   |
| ----------------------------------------------- | ---------------------------------------- |
| Click a profile                                 | Starts it (or brings it forward if open) |
| **Hold** the left mouse button on a profile     | Enters selection mode and selects it     |
| Click more profiles, then **Start selected**    | Starts them and remembers them as your group |
| **Start Personal + Side** (after a group start) | Starts the remembered group in one click |
| **Start all**                                   | Starts every profile                     |
| Right-click or `⋯` on a profile                 | Start, Edit, Remove                      |
| Keys `1`–`5`                                    | Start profile 1–5                        |
| `Ctrl+A`                                        | Select all                               |
| `Esc`                                           | Leave selection mode, or close           |

**Groups.** The profiles you last started together with **Start selected** are
remembered. Next time a **Start <names>** button starts them in one click, and
entering selection mode (**Select** or holding the mouse button) starts with
them already ticked. The tray menu has the same **Start group** item.

The `☰` menu has **Add profile**, **Paste sign-in link**, **Check for
updates**, **Settings** and **About**. Settings cover the hotkey, tray agent,
what starts at sign-in, Desktop shortcuts, PATH, loader password, link
routing, repair and uninstall.

### Starting at sign-in

**Settings › When I sign in to Windows** has two independent options:

- **Open the loader**, so the window is waiting for you after sign-in;
- **Start:** tick the profiles that should open by themselves. Locked ones ask
  for their password first.

Both use one shortcut in your Startup folder (**Claude Profiles**), which also
starts the tray agent. The terminal manager has the same choices under **What
starts when you sign in**.

A green **● running** label shows which profiles are open. When Claude has
updated and the profile copy is out of date, a banner with a **Refresh copy**
button appears.

The loader follows the Windows light/dark setting and your accent color.

### Tray agent

The agent starts when you sign in to Windows (the **Claude Profiles** shortcut
in your Startup folder). It owns the hotkey. Left-click the tray icon to open
the loader, or right-click it for **Start <profile>**, **Start group**,
**Start all** and **Open Claude Loader**. It uses about 20–30 MB of memory. If the hotkey is already taken by
another program, the tray icon shows a notice. Pick another hotkey in
Settings.

### Terminal

```bat
claude-profiles            :: manager menu (or setup on the first run)
claude-profiles loader
claude-profiles launch work personal
claude-profiles list
claude-profiles update     :: refresh the Claude copy after Claude updated
claude-profiles doctor     :: what was detected (useful for bug reports)
claude-profiles uninstall
```

With terminal commands on, each profile also has `claude-<id>` (for example
`claude-work`). It runs the Claude Code CLI with that profile's own login and
settings, with the same arguments as `claude`. Open a new terminal window after
setup so the PATH change applies.

---

## Signing in

Sign in to each profile once. Each profile then remembers its account.

**Recommended: e-mail + code.** In the profile's window, type your e-mail
address and use the code Claude sends you. It's the same account as "Continue
with Google", because Claude identifies accounts by e-mail.

**"Continue with Google".** The browser returns to Claude through a
`claude://` link. Claude registers that link for itself, pointing at the
standard app, every time it starts. So by default the login lands in the
standard window, not in the profile that asked for it. Two ways around it:

- **Paste sign-in link (reliable).** When the browser asks to open Claude,
  cancel. Copy the `claude://…` link, for example by right-clicking the page's
  open-app button › Copy link. In the loader choose **☰ › Paste sign-in link**,
  pick the profile and click **Send**. The loader fills the link in for you if
  it's already on the clipboard.
- **Link routing (experimental).** `claude-profiles` registers itself for
  `claude://`, and the tray agent puts that registration back whenever Claude
  overwrites it. A link then goes to the running profile, or you're asked
  which profile should get it. It's off by default. Turn it on in Settings.

If a Google login switched the standard profile to the wrong account, sign out
there and sign back in with the right one.

---

## Passwords

Passwords are a **simple lock**. The loader, the shortcuts and the `claude-<id>`
commands ask for it before they start a locked profile, and the loader can have
its own password. Only salted PBKDF2 hashes are stored, in
`%APPDATA%\claude-profiles\config.json`.

The lock **doesn't encrypt anything**. Profile folders are ordinary folders of
your Windows account, and anyone signed in as you can open them or start
Claude directly. For real protection, use your Windows password and
BitLocker.

---

## Why a copy of Claude?

The Store (MSIX) version of Claude lives in `C:\Program Files\WindowsApps`,
and Windows won't start it with a different data folder. Extra profiles
therefore run from a copy in `%LOCALAPPDATA%\ClaudePortable`. That's the same
folder the legacy script used, so an existing copy is reused.

- The **standard** profile, if you keep one, always runs the real Store app, so
  Store updates reach it immediately.
- The **copy** doesn't update itself. After Claude updates, the loader shows
  **Refresh copy**. You can also run `claude-profiles update`. Close the
  profile windows first.

With the classic installer (`%LOCALAPPDATA%\AnthropicClaude`) no copy is
needed, and all profiles use the installed app. *This path is implemented but
hasn't been tested on a real machine yet.*

---

## What goes where

| Item                                       | Location                                               |
| ------------------------------------------ | ------------------------------------------------------ |
| Program, Python environment, icons, logs   | `%LOCALAPPDATA%\claude-profiles\`                      |
| `claude-profiles.cmd`, `claude-<id>.cmd`   | `%LOCALAPPDATA%\claude-profiles\bin\`                  |
| Settings (profiles, password hashes)       | `%APPDATA%\claude-profiles\config.json`                |
| Profile data (default)                     | `%APPDATA%\claude-profiles\profiles\<id>\`             |
|  … Claude Desktop data                     | `<data folder>\desktop` (or the adopted folder)        |
|  … Claude Code data (CLI and Code tab)     | `<data folder>\cli`                                    |
| Copy of Claude for profiles (MSIX)         | `%LOCALAPPDATA%\ClaudePortable\`                       |
| Shortcuts                                  | Start menu › Claude Profiles, Desktop (optional)       |
| Sign-in autostart and tray agent           | Startup folder › Claude Profiles                       |
| `claude://` routing (only if turned on)    | `HKCU\Software\Classes\claude`                         |

The colored icons are made on your PC from the logo of the installed Claude
Desktop. The repository doesn't ship Anthropic artwork.

Each profile runs with `--user-data-dir=<data folder>\desktop` and with
`CLAUDE_CONFIG_DIR=<data folder>\cli`. That way the Code tab and the
`claude-<id>` command share one Claude Code config, and different profiles
never mix. Running profiles are detected by the `lockfile` that Claude keeps in
its data folder while it runs.

---

## Uninstall

Run `claude-profiles uninstall` or use **Settings › Uninstall…** in the
loader. It removes the shortcuts, loader, tray agent, hotkey, `claude-*`
commands, PATH entry, `claude://` routing (the previous handler is restored),
the program and its Python environment. It asks separately:

- whether to delete the profiles' **own data folders**. This is off by default,
  and you have to type `DELETE` to confirm;
- whether to delete the **Claude copy** in `%LOCALAPPDATA%\ClaudePortable`.

The standard Claude folders and Claude Desktop itself are never touched.

---

## Troubleshooting

Start with `claude-profiles doctor`. What each instance printed on startup is
in `%LOCALAPPDATA%\claude-profiles\logs\<id>.log`.

| Problem                                          | What to do |
| ------------------------------------------------ | ---------- |
| "The Claude copy for profiles is missing or outdated" | Loader › Refresh copy, or `claude-profiles update` (close profile windows first). |
| The hotkey does nothing                          | Is the tray icon there? If not, run **Claude Profiles** from the Startup folder or turn the agent on in Settings. The icon's tooltip says if the hotkey is taken. |
| All profiles share one taskbar button            | Expected: Claude sets its own taskbar identity. The shortcuts still have their colors. |
| A profile opens the wrong account                | Check `claude-profiles list` for its data folder. Sign out there and sign in with e-mail + code. |
| Google sign-in lands in the wrong window         | Use **Paste sign-in link** (see [Signing in](#signing-in)). |
| Icons look wrong after a Claude update           | Settings › Repair shortcuts and icons. |
| `claude-work` is not recognized                  | Open a new terminal window, or turn on "commands on PATH" in Settings. |

**Cowork** uses one Hyper-V virtual machine per PC, so only one profile can use
Cowork at a time. Chat and the Code tab aren't affected.

---

## Status

- Tested automatically on Windows 11 in an isolated sandbox (temporary
  AppData, mocked registry and known folders). The tests cover: config, icons
  made from the real Claude logo, Start-menu, Desktop and Startup shortcuts,
  CLI commands, PATH handling, `claude://` registration and restore, launching
  with the right folders and environment, running detection via `lockfile`,
  link routing, the copy/update logic, and the setup wizard, manager and
  uninstaller (including taking over `Claude-Personal`). The loader and all
  its dialogs were rendered and checked in light, dark and standard themes.
- **Not yet tested for real:** the tray agent (hotkey, tray menu), starting
  real Claude instances from the loader, `claude://` routing with a real
  Google sign-in, and the classic (Squirrel) installer.
