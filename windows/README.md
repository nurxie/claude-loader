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
- **Token usage window:** a bar per profile showing how much of the 5-hour
  window is spent, when it resets, and the week by model.
- **Uninstaller:** removes everything it created. It asks before it deletes any
  profile data.

It also keeps itself current: it tells you when a new Claude Loader release is
out and installs it when you click **Update**.

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

The `☰` menu has **Add profile**, **Token usage**, **Paste sign-in link**,
**Check for Claude updates**, **Check for Claude Loader updates**, **Settings**
and **About**. Settings cover the hotkey, tray agent, what starts at sign-in,
Desktop shortcuts (for the profiles and for the loader itself), PATH, loader
password, link routing, Claude Loader's own updates, the token usage source,
recreating shortcuts and uninstalling.

**Which account is which.** Each profile's card names the account it is signed
in as - the e-mail and the organization - once it has been asked. That is the
thing you cannot see from the outside: five profiles look alike until one of
them turns out to be the wrong login. If two profiles end up in the same
account, the loader says so.

**At a glance.** Under the name, a thin bar shows how much of that profile's
five-hour window is gone, amber from 75 % and red from 90 %, so you can see the
state of every account without opening anything.

**A warning before you run out.** At 90 % of a window you get one desktop
notification per profile per window, with the time it resets. Turn it off in
Settings, or set `usage_alert_percent` to 0 in `config.json`.

### Changing the hotkey

**Settings › Hotkey › Change…**, then press the combination you want. It takes
effect as soon as you save — no restart. A shortcut is **two to four keys**:
one to three modifiers (Ctrl, Alt, Shift, Win) and then a normal key, with at
least one of Ctrl, Alt or Win among them, because Shift on its own would
swallow ordinary typing. If the combination cannot be used, the dialog says why
in one line; if another program already owns it, Settings says so before you
save. Ready-made ones are one click away, and **None** turns the hotkey off.

### Shortcuts you deleted by accident

**Settings › Recreate shortcuts and icons** builds the whole set again: the
Start-menu entries, the Desktop shortcuts, the colored icons and the
`claude-<name>` commands. Nothing else changes. The terminal manager has the
same entry, and so does `claude-profiles apply`.

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
**Start all**, **Token usage** and **Open Claude Loader**. It uses about
20–30 MB of memory. If the hotkey is already taken by another program, the tray
icon shows a notice. Pick another hotkey in Settings.

### Terminal

```bat
claude-profiles              :: manager menu (or setup on the first run)
claude-profiles loader
claude-profiles launch work personal
claude-profiles list
claude-profiles usage        :: the token window (--text prints a table)
claude-profiles update       :: refresh the Claude copy after Claude updated
claude-profiles self-update  :: update Claude Loader itself (--check only looks)
claude-profiles apply        :: recreate shortcuts, icons and commands
claude-profiles doctor       :: what was detected (useful for bug reports)
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

## Token usage

Open it from the loader's `☰ › Token usage…`, the tray menu, the Start menu
(**Claude Profiles › Claude Token Usage**) or `claude-profiles usage`. It is a
window of its own, meant to be left open next to your work.

Each profile gets two bars:

- **5-hour window** — what this window has cost so far and **when it resets**.
  Claude's allowance runs in five-hour windows that open with your first
  message, so the window shows both the countdown and the wall-clock time.
- **Last 7 days** — a rolling total, with the busiest models named.

The bar turns amber at 75 % and red at 90 %. It refreshes itself every minute.

> **A profile signed in only in the Claude app has no figures yet.** The app's
> Code tab keeps its session inside the app's own encrypted storage, so there is
> no token for Claude Loader to read. The profile still shows *which* account it
> is — Claude Code records that either way — but the percentages stay empty
> until you sign that profile's terminal command in once:
>
> ```
> claude-work          # then /login, once per profile
> ```
>
> After that the account answers and the bars fill in. Signing in through the
> terminal does not sign you out of the app; they share the profile's folder.

**Where the numbers come from.** The percentages and the reset times are asked
from each profile's own account, over HTTPS, with the sign-in that profile
already keeps in its folder. That is the only place they exist: a plan's
allowance is not written down anywhere on your PC, and neither is the moment a
window resets.

Alongside that, Claude Loader reads the Claude Code transcripts in the
profile's config folder for the detail the account does not return - which
models the tokens went to, and how many messages. That covers the **Claude Code
CLI and the Desktop app's Code tab**, which share the folder; chat in the
Desktop app is not recorded by Claude Code, so it is not counted there.

If an account cannot be reached - the profile has never been started, the
sign-in has expired, Windows keeps that profile's sign-in somewhere other than
its own folder, there is no network - the window says so in one sentence and
falls back to the local count. The bar then fills against whatever you set
under **Limits...**, or against the busiest window seen so far.

Nothing is sent anywhere but Anthropic, and nothing read is stored, logged or
shown. To turn the requests off, use the switch in Settings, or pass
`claude-profiles usage --local`.

---

## Keeping Claude Loader up to date

The loader checks github.com once a day for a newer release and shows a banner
when there is one. Nothing is installed until you click **Update**. You can
also use `☰ › Check for Claude Loader updates`, **Settings › Check now**, or
`claude-profiles self-update` (`--check` only looks).

An update downloads the release and replaces the program in
`%LOCALAPPDATA%\claude-profiles\app`. Your profiles, settings, passwords and
logins are not touched, and neither is the Python environment. If the swap
cannot be done, the old version is put back and nothing changes. Close and
reopen the loader afterwards.

Turn the check off in **Settings › Claude Loader itself** if you would rather
update by re-running `Install.cmd` from the repository.

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
| Last update check                          | `%LOCALAPPDATA%\claude-profiles\update.json`           |
| Shortcuts                                  | Start menu › Claude Profiles, Desktop (optional)       |
| … Start menu                               | Claude (Name), Claude Loader, Claude Token Usage       |
| … Desktop                                  | Claude (Name), and Claude Loader if you asked for it   |
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
| A shortcut is gone, or the icons look wrong after a Claude update | Settings › Recreate shortcuts and icons (or `claude-profiles apply`). |
| The usage window says "no activity"              | That profile has not used the Claude Code CLI or the Code tab yet. Desktop chat is not counted. |
| A usage bar has no limit                         | Set your plan's allowance under Limits…, or give it a few windows of history to learn from. |
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
- Also checked on a real machine: the two-to-four-key rule over a table of
  valid and invalid combinations, the token window and its limits dialog (built
  and painted, with and without limits), `claude-profiles usage` against real
  transcripts, the update check against the live GitHub API, and a full
  self-update of a real release into a sandbox folder.
- The account figures, the per-profile identity and the near-the-limit warning
  were written against a live Anthropic endpoint and verified end to end **on
  Linux**; the shared half of that code is covered by the test suite on every
  system.
- **Not yet tested for real on Windows:** the tray agent (hotkey, tray menu and
  its warning balloon), the usage bar on the loader cards, starting real Claude
  instances from the loader, `claude://` routing with a real Google sign-in, and
  the classic (Squirrel) installer.

How it all fits together, for reading or changing the code: [docs/ARCHITECTURE.md](../docs/ARCHITECTURE.md).
