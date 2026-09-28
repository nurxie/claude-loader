# Claude Loader

**One hotkey, all your Claude accounts.** Claude Loader is a loader, launcher
and profile manager for Claude Desktop and the Claude Code CLI. Work with
several accounts (Team, Personal, client projects) and run their agents at the
same time, without signing out and back in.

- **Loader:** press `Win+Shift+C` / `Super+Shift+C`, click a profile and it
  starts. Hold the mouse button to pick several and start them as a group.
- **Launcher:** colored shortcuts, a tray menu, autostart at sign-in and a
  `claude-<name>` command per profile.
- **Manager:** add, recolor, lock or remove profiles, keep the Claude copy up
  to date, and uninstall cleanly.

Every profile is fully isolated: its own Desktop data (`--user-data-dir`) and
its own Claude Code config (`CLAUDE_CONFIG_DIR`). The Desktop app's Code tab
and the CLI share one login per profile and never mix with the others.

| Version | For | What you get |
| --- | --- | --- |
| [**Windows**](windows/README.md) | Windows 10/11 | Up to 5 profiles, a hotkey loader, a tray menu, colored icons, optional passwords, `claude-<name>` CLI commands |
| [**Linux**](linux/README.md) | Ubuntu 24.04+ (GNOME) | The same feature set with a native GTK loader and GNOME hotkey |
| [**Windows legacy**](windows/legacy/README.md) | Windows 10/11 | Just two Desktop shortcuts (TEAM / Personal), no installation |

> **Unofficial.** This project is not affiliated with or endorsed by Anthropic.
> Claude Desktop doesn't officially support multiple accounts. This is a
> workaround, and a future app update could break it.

Claude Loader is free, open-source software under the [MIT license](LICENSE).

---

## Quick start

**Windows:** double-click `windows\Install.cmd`, then follow the wizard.

**Linux:**

```bash
bash linux/install.sh
```

Both installers need the full repository, because they combine their OS
folder with `cross-platform/`. After setup you get:

- a **Claude (Name)** shortcut or menu entry for each profile, with its own
  icon color;
- the **Claude Loader** (default hotkey `Win+Shift+C` on Windows,
  `Super+Shift+C` on Linux). Click a profile to start it, or hold the mouse
  button to select several;
- optionally `claude-<name>` terminal commands for the Claude Code CLI;
- `claude-profiles` to manage everything later, and
  `claude-profiles uninstall` to remove it.

The command, the Python package and the data folders keep the project's
original name, `claude-profiles`.

---

## How it works

Claude Desktop is an Electron app. Electron's `--user-data-dir=<folder>`
option makes it keep all of its state in another folder: settings, session,
login, MCP config and history. Each profile gets its own folder, so it's an
independent instance that can run next to the others.

Each profile also gets its own `CLAUDE_CONFIG_DIR`, so the Desktop app's Code
tab and the profile's `claude-<name>` command share one Claude Code config
that no other profile touches.

One profile may keep using Claude's **standard folders**, which keeps the login
you already have.

## Signing in: use e-mail + code

For the first sign-in in each profile, type your e-mail address and use the
code Claude sends you. That always works and gives you the same account as
"Continue with Google".

Google sign-in returns through a `claude://` link, which by default always goes
to the standard Claude window. Details and workarounds:

- The loader's **Paste sign-in link** sends a copied `claude://` link to the
  profile you choose.
- Optional automatic **link routing** (experimental on both systems).

The OS pages explain both.

---

## Repository layout

```
README.md                  this page
LICENSE                    MIT
cross-platform/            shared core (Python): profiles, passwords, icons,
                           launching, link routing, terminal wizard/manager
linux/                     Linux part + install.sh
windows/                   Windows part + Install.cmd / install.ps1
windows/legacy/            the original two-shortcut PowerShell script
```

See [cross-platform/README.md](cross-platform/README.md) for the design and
the `config.json` format.

---

## Prior art

Community projects built on the same idea:

- [sypnose-cloud/claude-desktop-multi](https://github.com/sypnose-cloud/claude-desktop-multi): Windows, portable copy outside `WindowsApps`
- [vodongha/claude-desktop-clone](https://github.com/vodongha/claude-desktop-clone): Windows, notes on Cowork VM limits
- [jmdarre-v/claude-multiprofile](https://github.com/jmdarre-v/claude-multiprofile): macOS, Desktop + CLI
- [ftery0/claude-account-switch](https://github.com/ftery0/claude-account-switch): CLI profiles via `CLAUDE_CONFIG_DIR`

## License

[MIT](LICENSE). Claude is a trademark of Anthropic. This repository doesn't
ship any Anthropic artwork: profile icons are generated on your machine from
the installed app's own icon.
