# Claude Loader for Linux

Run **up to 5 Claude Desktop accounts at the same time** on Ubuntu. Each account
gets its own window, its own colored Claude icon, its own data folder and,
if you want, its own password and its own Claude Code terminal command.

Claude Loader is one program with several jobs. Its command is
`claude-profiles`:

- **Installer:** installs Claude Desktop from Anthropic's official apt
  repository, and optionally the Claude Code CLI, then walks you through
  creating your profiles.
- **Manager:** add, edit, recolor, lock or remove profiles later, from the
  terminal or from the loader.
- **Loader (optional):** a small window that opens with a hotkey. Click a
  profile to start it. Hold the mouse button to select several and start them
  together. It also checks for Claude Desktop updates and installs them in two
  clicks.
- **Uninstaller:** removes everything it created. It asks separately before it
  deletes any profile data.

> **Unofficial.** This project is not affiliated with or endorsed by Anthropic.
> Claude Desktop for Linux is in beta
> ([docs](https://code.claude.com/docs/en/desktop-linux)) and doesn't officially
> support multiple accounts. This tool uses the standard Electron
> `--user-data-dir` option, and a future app update could break it.

---

## Requirements

- **Ubuntu 24.04 or newer with the default GNOME desktop.** The loader needs
  GTK 4 and libadwaita 1.4+. Ubuntu 22.04 ships an older libadwaita, so the
  loader won't run there.
- An x86_64 or arm64 PC.
- A normal user account with `sudo` rights (needed once, to install packages).

The installer adds whatever is missing: `python3-gi`, `gir1.2-gtk-4.0`,
`gir1.2-adw-1`, `curl`, `gnupg` and `xdg-utils`.

---

## Install

```bash
git clone <this repository>
cd <repository>
bash linux/install.sh
```

`install.sh` needs the full repository: it combines `linux/` with the shared
`cross-platform/` core. It copies the program to
`~/.local/share/claude-profiles/app` and creates the `claude-profiles` command
in `~/.local/bin`. It then starts the setup wizard, which asks:

1. **Claude Desktop.** If it isn't installed yet, whether to install it from
   Anthropic's apt repository. The key fingerprint is checked before anything
   is trusted.
2. **Claude Code CLI.** Whether each profile should also get a terminal
   command, such as `claude-work`. If the CLI is missing, the wizard offers
   the official installer.
3. **Profiles (1 to 5).** For each profile you choose:
   - a **name**, for example "Work" or "Personal";
   - an **icon color**: Original, Green, Blue, Purple, Pink, Yellow, Teal or
     Graphite;
   - a **data folder**. The options are the *standard Claude folders* (only one
     profile can use them, and they keep an existing login), a separate folder
     under `~/.local/share/claude-profiles/profiles/<id>`, or a folder you pick;
   - an optional **password**.
4. **Loader.** Whether to install it, which **hotkey** opens it (default
   `Super+Shift+C`), an optional loader **password**, and whether it should
   check for updates.
5. **Sign-in link routing.** Whether `claude://` links go to the right profile.
   See [Signing in](#signing-in).

To update `claude-profiles` itself later, get the new files and run
`bash linux/install.sh` again. Your profiles and settings are kept.

---

## Using it

### Menu entries

Every profile appears in the app menu as **Claude (Name)** with its own colored
icon. You can pin those entries to the dock like any other app.

The original **Claude** entry from the package stays. It always opens the
standard data folder.

### The loader

Open it with the hotkey or the **Claude Loader** menu entry.

| Action                                           | Result                                    |
| ------------------------------------------------ | ----------------------------------------- |
| Click a profile                                  | Starts it (or focuses it if it's running) |
| **Hold** the left mouse button on a profile      | Enters selection mode and selects it      |
| Click more profiles, then **Start selected**     | Starts them and remembers them as your group |
| **Start Personal + Side** (after a group start)  | Starts the remembered group in one click  |
| **Start all**                                    | Starts every profile                      |
| Right-click or `⋮` on a profile                  | Start, Edit, Remove                       |
| Keys `1`–`5`                                     | Start profile 1–5                         |
| `Ctrl+A`                                         | Select all profiles                       |
| `Esc`                                            | Leave selection mode, or close the loader |

**Groups.** The profiles you last started together with **Start selected** are
remembered. Next time a **Start <names>** button starts them in one click, and
entering selection mode starts with them already ticked.

**At sign-in.** Settings › **When I sign in** has two independent options:
**Open the loader**, and a switch for each profile that should start by
itself. Locked profiles ask for their password first. They're stored as
`~/.config/autostart/claude-profiles.desktop`. The terminal manager has the
same choices under **What starts when you sign in**.

The main menu (`☰`) has **Add profile**, **Paste sign-in link**, **Check for
updates** and **Settings**. Settings cover the hotkey, loader password, update check,
link routing, recreating the menu entries and uninstall.

**The hotkey** is two to four keys: one to three modifiers and then a normal
key, with at least one of Super, Ctrl or Alt among them, because Shift on its
own would swallow ordinary typing. It is stored in the GNOME form,
`<Super><Shift>c`. Changing it takes effect at once; if another custom shortcut
already uses the same keys, you are told which one.

A green **● running** label shows which profiles are open. When a new Claude
Desktop version is out, a banner with an **Update** button appears. Your system
password is asked through the standard Ubuntu dialog.

### Terminal commands

```bash
claude-profiles            # manager menu (or setup on the first run)
claude-profiles loader     # open the loader
claude-profiles launch work personal
claude-profiles list
claude-profiles usage --text  # tokens per profile and when each window resets
claude-profiles update        # check for and install Claude Desktop updates
claude-profiles self-update   # update Claude Loader itself (--check only looks)
claude-profiles apply         # recreate menu entries, icons and commands
claude-profiles doctor        # show what was detected (useful for bug reports)
claude-profiles uninstall
```

`usage` counts the tokens each profile has spent from the history Claude Code
keeps in the profile's own config folder, and says when its five-hour window
resets. On Linux it prints a table; the window with the bars exists on Windows
only so far. Set a profile's allowance by putting `usage_limit` in
`config.json` (see [cross-platform/README.md](../cross-platform/README.md)).

With the CLI option on, each profile also has a command such as `claude-work`.
It runs the Claude Code CLI with that profile's own login and settings, and
takes the same arguments as `claude`:

```bash
claude-work
claude-personal -p "summarize README.md"
```

If `~/.local/bin` was just created, log out and back in once so it lands on
your `PATH`.

---

## Signing in

Sign in to each profile once. Each profile then remembers its own account.

**Recommended: e-mail + code.** In the profile's window, type your e-mail
address and use the code Claude sends you. This always works, because nothing
leaves the window. It's the same account as "Continue with Google", since
Claude accounts are identified by e-mail address.

**"Continue with Google".** After Google sign-in, the browser returns to Claude
through a `claude://` link. Normally Ubuntu hands that link to the standard
Claude entry, so the login lands in the wrong profile. That's the same problem
as on Windows; see the
[legacy README](../windows/legacy/README.md#known-problem-google-sign-in-goes-to-the-wrong-window).
Two ways around it:

- **Link routing** (on by default). `claude-profiles` takes over `claude://`
  links. If exactly one profile is running, the link goes to it. If several
  are running, a small window asks which profile should get it. This is new and
  experimental.
- **Paste sign-in link.** When the browser asks to open Claude, cancel. Copy
  the `claude://…` link, then choose **☰ › Paste sign-in link** in the loader,
  pick the profile and click **Send**. The same is available in the terminal
  manager.

If both fail, use e-mail + code.

---

## Passwords

Passwords are a **simple lock**. The loader and the menu entries ask for the
password before they start a locked profile, and the loader can have its own
password. Passwords are stored only as salted PBKDF2 hashes in a config file
that only you can read.

The lock **doesn't encrypt anything**. Profile folders are ordinary folders
readable by your Linux user, and anyone logged in as you could open them or
start Claude directly. Use it to keep a shared or unattended screen tidy, not
as data protection. For real protection, rely on your login password and disk
encryption.

---

## What goes where

| Item                                    | Location                                                    |
| --------------------------------------- | ----------------------------------------------------------- |
| Program (shared core + Linux part)      | `~/.local/share/claude-profiles/app/claude_profiles/`       |
| `claude-profiles` and `claude-<id>`     | `~/.local/bin/`                                             |
| Settings (profiles, password hashes)    | `~/.config/claude-profiles/config.json`                     |
| Menu entries                            | `~/.local/share/applications/claude-profile-*.desktop`      |
| Colored icons                           | `~/.local/share/claude-profiles/icons/`                     |
| Logs of started instances               | `~/.local/share/claude-profiles/logs/<id>.log`              |
| Profile data (default)                  | `~/.local/share/claude-profiles/profiles/<id>/`             |
|  … Claude Desktop data                  | `<data folder>/desktop`                                     |
|  … Claude Code data (CLI and Code tab)  | `<data folder>/cli`                                         |
| Hotkey                                  | GNOME Settings → Keyboard → Custom Shortcuts → Claude Loader |

The colored icons are made on your PC from the icon of the installed
`claude-desktop` package. This repository doesn't ship any Anthropic artwork.

How a profile is isolated: Claude Desktop is started with
`--user-data-dir=<data folder>/desktop`, and with
`CLAUDE_CONFIG_DIR=<data folder>/cli` so its Code tab and the `claude-<id>`
command share one Claude Code config. Profiles don't share it with each other.
A profile that uses the standard folders runs Claude exactly as the normal
menu entry does.

---

## Updating

- **Claude Desktop:** use the loader banner, `claude-profiles update`, or the
  normal `sudo apt upgrade`. All profiles use the same installed app, so one
  update covers them all. Restart open Claude windows afterwards.
- **Claude Code CLI:** the native installer updates itself in the background.
- **Claude Loader itself:** `claude-profiles self-update` looks for a new
  release on GitHub and installs it after you say yes (`--check` only looks).
  It replaces the program in `~/.local/share/claude-profiles/app`; profiles,
  settings and logins are untouched, and the old version is put back if the
  swap fails. Running `bash linux/install.sh` again from the new files still
  works and is the way to go when the installer itself changed.

---

## Uninstall

```bash
claude-profiles uninstall
```

This removes the menu entries, loader, hotkey, icons, `claude-*` commands and
the program. It then asks, separately:

- whether to delete the profiles' **own data folders**. This is off by default,
  and you have to type `DELETE` to confirm;
- whether to uninstall **Claude Desktop** as well.

The standard Claude folders (`~/.config/Claude`, `~/.claude`) are never touched.

---

## Troubleshooting

Start with `claude-profiles doctor`. It shows the detected Claude command, icon,
versions, desktop session, link handler and which profiles are running. What an
instance printed on startup is in `~/.local/share/claude-profiles/logs/<id>.log`.

| Problem                                        | What to do                                                                 |
| ---------------------------------------------- | -------------------------------------------------------------------------- |
| Hotkey does nothing                            | Registering it works only in GNOME. Add it by hand: Settings → Keyboard → Custom Shortcuts, command `~/.local/bin/claude-profiles loader`. Check that no other shortcut uses the same keys. |
| All profiles share one dock icon               | Separate dock icons depend on how the Claude build names its windows. They may not work on every version; the profiles still work. |
| A profile opens the wrong account              | Check that it doesn't use the standard folders by mistake (`claude-profiles list`). Sign out there and sign in again with e-mail + code. |
| Claude starts but ignores the profile          | Claude Desktop may not pass options through. Set `"desktop_bin"` in the config to the real executable (see `doctor`), then run `claude-profiles apply`. |
| Extra `--class` option causes trouble          | Set `"window_class": false` in the config, then run `claude-profiles apply`. |
| Google sign-in lands in the wrong window       | Turn on link routing (Settings) or use e-mail + code.                      |
| A menu entry is gone, or icons look wrong after a Claude update | Loader → Settings → Recreate, `claude-profiles manage` → Recreate, or `claude-profiles apply`. |
| `usage` says "no activity"                     | That profile has not used the Claude Code CLI or the Code tab yet. Desktop chat is not recorded. |

**Cowork** runs its tasks in a local QEMU/KVM virtual machine. Running Cowork
in several profiles at the same time hasn't been tested.

---

## Status

- Tested automatically on Ubuntu 24.04 (WSL) with a stand-in for Claude
  Desktop: config, passwords, menu entries, icons (PNG/ICO codecs, resize,
  recolor), CLI commands, launching, detecting running profiles, link routing
  and pasted links, the setup wizard, the manager and the uninstaller. The
  update check was run against Anthropic's real repository.
- **Not yet tested:** the loader window and real Claude Desktop instances on a
  GNOME desktop. Everything added in 0.3.0 — the two-to-four-key rule for the
  GNOME hotkey, `usage`, `self-update` — was written and checked on Windows and
  has not been run on Ubuntu yet.
