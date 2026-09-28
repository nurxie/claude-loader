# Legacy: two Claude Desktop accounts, no installation

The original, minimal Windows script. It creates **two Desktop shortcuts**,
**Claude TEAM** and **Claude Personal**, that can run at the same time, each
signed in to a different account. There's no installer, no Python and no
loader: one PowerShell script and a double-click launcher.

> For up to 5 profiles, a hotkey loader, colored icons, passwords and CLI
> commands, use the [full Windows version](../README.md) instead. It can take
> over the Personal profile created here, and you keep its login.

> **Unofficial.** Not affiliated with or endorsed by Anthropic. It relies on
> Claude Desktop honoring Electron's `--user-data-dir` option, and a future app
> update could break it.

| Shortcut            | What it opens                                            |
| ------------------- | -------------------------------------------------------- |
| **Claude TEAM**     | Your normal Claude Desktop with its existing login       |
| **Claude Personal** | A second, separate Claude profile for your other account |

## How it works

- **Claude TEAM** starts the installed app normally, with its default data
  folder.
- **Claude Personal** starts the app with
  `--user-data-dir="%APPDATA%\Claude-Personal"`, so it keeps its own settings,
  session and login.

Two install types are handled:

- **Microsoft Store / MSIX.** Windows doesn't allow starting the app inside
  the protected `WindowsApps` folder with a different data folder, so the script
  copies it to `%LOCALAPPDATA%\ClaudePortable`. The Personal shortcut points to
  that copy. The TEAM shortcut starts the normal packaged app.
- **Classic installer** (`%LOCALAPPDATA%\AnthropicClaude\claude.exe`). No copy
  is needed. *This path hasn't been tested on a real machine yet.*

## Requirements

Windows 10 or 11, Claude Desktop installed
([claude.ai/download](https://claude.ai/download)), and Windows PowerShell 5.1
(included with Windows).

## Setup

1. Keep `Run-Setup.cmd` and `Setup-ClaudeTwoAccounts.ps1` in the same folder.
2. Double-click **`Run-Setup.cmd`**. If SmartScreen shows a blue warning, click
   **More info**, then **Run anyway**. With an MSIX install, copying the app
   takes about a minute.
3. The **Claude TEAM** and **Claude Personal** shortcuts appear on the Desktop.

### First sign-in to the personal account (once)

1. Close **all** Claude windows, including the tray icon (right-click it and
   choose Quit).
2. Open **Claude Personal**.
3. **Don't click "Continue with Google".** Type your e-mail address (for
   example your Gmail address) and sign in with the code Claude sends you. It's
   the same account as with Google, since Claude identifies accounts by e-mail.
4. Open **Claude TEAM**. It should still be signed in to your Team account.

After that, both shortcuts can run side by side, in any order.

> The script's final message still says "sign in with Google". Skip that and
> use the e-mail code.

## Known problem: Google sign-in goes to the wrong window

**Symptom:** In Claude Personal you click "Continue with Google" and finish in
the browser. The login then lands in the **TEAM** window, and Personal stays
signed out.

**Cause:** Google sign-in returns to the app through a `claude://` link.
Claude registers that link for itself in `HKCU\Software\Classes\claude`,
pointing at the installed app, and it does this again each time it starts.
The link therefore always reaches the standard (TEAM) instance, never the copy
with the Personal data folder.

**Fix:** sign in to Personal with **e-mail + code**. If a Google login reached
TEAM and switched it to your personal account, sign out there and sign back in
to the Team account.

The full Windows version adds a **Paste sign-in link** button that sends a
copied `claude://` link to the profile you choose.

## Updating Claude

- **MSIX:** the copy in `%LOCALAPPDATA%\ClaudePortable` doesn't update itself.
  After Claude updates, run `Run-Setup.cmd` again. The Personal login is kept.
- **Classic installer:** both shortcuts use the installed app, so updates apply
  to both.

## Uninstalling

Delete the two shortcuts, then `%LOCALAPPDATA%\ClaudePortable` (MSIX only),
and, if you want, `%APPDATA%\Claude-Personal`. That last folder holds the
personal login, settings and history.

## Troubleshooting

- **`Unexpected token '}'` / `'{'` in PowerShell:** Windows PowerShell 5.1 reads
  scripts without a BOM in the ANSI code page, and non-ASCII text breaks
  parsing. The scripts here are ASCII-only on purpose; keep them that way.
- **The launcher runs an old script:** a re-download may be saved as
  `Setup-ClaudeTwoAccounts (1).ps1`. Delete the old file and make sure the new
  one has exactly the name `Setup-ClaudeTwoAccounts.ps1`.
- **"Claude Desktop not found":** install it from
  [claude.ai/download](https://claude.ai/download) and run the script again.

## Limitations

- **Cowork** uses one Hyper-V VM per machine, so only one profile can run it at
  a time. Chat and the Code tab aren't affected.
- Each window is a full Electron app, so memory use roughly doubles.

## Bonus: Claude Code CLI with two accounts

The Claude Code CLI keeps its login and settings in the folder named by
`CLAUDE_CONFIG_DIR` (default `~/.claude`). Add this to your PowerShell profile
(`notepad $PROFILE`):

```powershell
function claude-team {
    claude @args
}

function claude-personal {
    $old = $env:CLAUDE_CONFIG_DIR
    $env:CLAUDE_CONFIG_DIR = "$HOME\.claude-personal"
    try { claude @args } finally { $env:CLAUDE_CONFIG_DIR = $old }
}
```

Run `claude-personal` once and use `/login` inside it. `/status` shows the
active account. If the profile doesn't load because scripts are disabled,
`Set-ExecutionPolicy RemoteSigned -Scope CurrentUser` allows local scripts.
That changes a security setting, so decide for yourself.
