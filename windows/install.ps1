# Installs (or updates) claude-profiles for the current Windows user, then
# starts the setup wizard (first run) or the manager (later runs).
# Any arguments are passed to claude-profiles, e.g.:  install.ps1 uninstall
# This file is intentionally ASCII-only (Windows PowerShell 5.1 reads scripts
# without a BOM in the ANSI code page).

$ErrorActionPreference = 'Stop'
$Src  = Split-Path -Parent $MyInvocation.MyCommand.Path
$Core = Join-Path $Src '..\cross-platform\claude_profiles\core'
if (-not (Test-Path $Core)) {
    throw "Cannot find $Core. Run this from a full copy of the repository."
}
$Data = Join-Path $env:LOCALAPPDATA 'claude-profiles'
$App  = Join-Path $Data 'app'
$Venv = Join-Path $Data 'venv'
$Bin  = Join-Path $Data 'bin'
$VenvPython = Join-Path $Venv 'Scripts\python.exe'

function Test-Python([string]$Exe, [string[]]$PreArgs) {
    # Python 3.10+ with Tkinter. The Microsoft Store alias stub fails this check.
    $ErrorActionPreference = 'Continue'
    try {
        & $Exe @PreArgs -c "import sys, tkinter; sys.exit(0 if sys.version_info >= (3, 10) else 1)" 2>&1 | Out-Null
        return ($LASTEXITCODE -eq 0)
    } catch { return $false }
}

function Find-Python {
    if ((Get-Command py -ErrorAction SilentlyContinue) -and (Test-Python 'py' @('-3'))) {
        $exe = & py -3 -c "import sys; print(sys.executable)"
        if ($exe) { return $exe.Trim() }
    }
    $cmd = Get-Command python -ErrorAction SilentlyContinue
    if ($cmd -and ($cmd.Source -notlike '*\WindowsApps\*') -and (Test-Python $cmd.Source @())) {
        return $cmd.Source
    }
    $known = Get-ChildItem -Path (Join-Path $env:LOCALAPPDATA 'Programs\Python') -Filter 'python.exe' `
             -Recurse -Depth 1 -ErrorAction SilentlyContinue | Sort-Object FullName -Descending
    foreach ($k in $known) {
        if (Test-Python $k.FullName @()) { return $k.FullName }
    }
    return $null
}

Write-Host ""
Write-Host "claude-profiles installer" -ForegroundColor Cyan

if (-not (Test-Path $VenvPython)) {
    $py = Find-Python
    if (-not $py) {
        Write-Host "Python 3.10 or newer (with Tkinter) is needed and was not found." -ForegroundColor Yellow
        if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
            Write-Host "Install Python from https://www.python.org/downloads/ and run this again."
            exit 1
        }
        $answer = Read-Host "Install Python 3.12 for your user with winget now? This accepts the Python license. (Y/n)"
        if ($answer -match '^(n|no)$') { exit 1 }
        winget install -e --id Python.Python.3.12 --scope user --accept-package-agreements --accept-source-agreements
        $py = Find-Python
        if (-not $py) { throw "Python was installed but cannot be found. Open a new window and run this again." }
    }
    Write-Host "Creating a private Python environment in $Venv"
    & $py -m venv $Venv
    if ($LASTEXITCODE -ne 0) { throw "Creating the Python environment failed." }
}

# Optional Windows 11 style theme for the loader. Works without it.
Write-Host "Installing the optional sv-ttk theme..."
$ErrorActionPreference = 'Continue'
& $VenvPython -m pip install --disable-pip-version-check --quiet --upgrade sv-ttk 2>&1 | Out-Null
$themeOk = ($LASTEXITCODE -eq 0)
$ErrorActionPreference = 'Stop'
if (-not $themeOk) { Write-Host "  (skipped, the standard Windows theme will be used)" -ForegroundColor DarkGray }

Write-Host "Installing claude-profiles to $App"
$Target = Join-Path $App 'claude_profiles'
if (Test-Path $Target) { Remove-Item -Recurse -Force $Target }
New-Item -ItemType Directory -Force -Path $Target | Out-Null
# claude_profiles is a namespace package: the shared core plus the Windows part.
Copy-Item -Recurse $Core (Join-Path $Target 'core')
Copy-Item -Recurse (Join-Path $Src 'claude_profiles\windows') (Join-Path $Target 'windows')
Get-ChildItem -Path $Target -Recurse -Directory -Filter '__pycache__' | Remove-Item -Recurse -Force

# Let the private Python find the program (Python writes the .pth in its own encoding).
& $VenvPython -c "import sys, sysconfig, pathlib; pathlib.Path(sysconfig.get_paths()['purelib'], 'claude_profiles_app.pth').write_text(sys.argv[1] + '\n', encoding='locale')" $App
if ($LASTEXITCODE -ne 0) { throw "Could not register the program with Python." }

New-Item -ItemType Directory -Force -Path $Bin | Out-Null
Set-Content -Encoding ascii -Path (Join-Path $Bin 'claude-profiles.cmd') -Value @(
    '@echo off',
    '"%LOCALAPPDATA%\claude-profiles\venv\Scripts\python.exe" -m claude_profiles.windows %*'
)

# After an update, refresh shortcuts and commands so they match the new version.
if (Test-Path (Join-Path $env:APPDATA 'claude-profiles\config.json')) {
    & $VenvPython -m claude_profiles.windows apply --quiet
}

& $VenvPython -m claude_profiles.windows @args
exit $LASTEXITCODE
