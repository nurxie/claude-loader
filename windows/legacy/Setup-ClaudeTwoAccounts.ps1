# Creates two Claude Desktop shortcuts on the Desktop:
#   "Claude TEAM"     - regular Claude (your current Team account)
#   "Claude Personal" - separate profile for your personal account
# Both can run at the same time. Unofficial method: Electron flag --user-data-dir.
# This file is intentionally ASCII-only to avoid encoding problems.

$ErrorActionPreference = 'Stop'

$Desktop     = [Environment]::GetFolderPath('Desktop')
$ProfileDir  = Join-Path $env:APPDATA      'Claude-Personal'
$PortableDir = Join-Path $env:LOCALAPPDATA 'ClaudePortable'
$Squirrel    = Join-Path $env:LOCALAPPDATA 'AnthropicClaude\claude.exe'
$wsh         = New-Object -ComObject WScript.Shell

function New-Shortcut([string]$Name, [string]$Target, [string]$Arguments, [string]$Icon) {
    $lnk = $wsh.CreateShortcut((Join-Path $Desktop "$Name.lnk"))
    $lnk.TargetPath = $Target
    if ($Arguments) { $lnk.Arguments = $Arguments }
    if ($Icon)      { $lnk.IconLocation = $Icon }
    $lnk.WorkingDirectory = Split-Path $Target -Parent
    $lnk.Save()
    Write-Host "  + $Name" -ForegroundColor Green
}

Write-Host ""
Write-Host "Looking for Claude Desktop..." -ForegroundColor Cyan

$pkg = Get-AppxPackage -Name '*Claude*' -ErrorAction SilentlyContinue |
       Where-Object { $_.Publisher -like '*Anthropic*' } |
       Select-Object -First 1

if ($pkg) {
    # Microsoft Store / MSIX version: an exe inside WindowsApps cannot be
    # started with custom arguments, so we make a local copy of the app.
    Write-Host "  Found MSIX version $($pkg.Version)"
    $app = @((Get-AppxPackageManifest $pkg).Package.Applications.Application)[0]
    $exe = Join-Path $PortableDir $app.Executable

    Write-Host "Copying app to $PortableDir (may take a minute)..." -ForegroundColor Cyan
    robocopy $pkg.InstallLocation $PortableDir /MIR /R:1 /W:1 /NFL /NDL /NJH /NJS /NP | Out-Null
    if ($LASTEXITCODE -ge 8) { throw "Copy failed (robocopy exit code $LASTEXITCODE)" }
    if (-not (Test-Path $exe)) { throw "Copied app not found at $exe" }

    $teamTarget = Join-Path $env:WINDIR 'explorer.exe'
    $teamArgs   = "shell:AppsFolder\$($pkg.PackageFamilyName)!$($app.Id)"
}
elseif (Test-Path $Squirrel) {
    Write-Host "  Found regular install: $Squirrel"
    $exe        = $Squirrel
    $teamTarget = $Squirrel
    $teamArgs   = $null
}
else {
    throw "Claude Desktop not found. Install it from claude.ai/download and run this again."
}

New-Item -ItemType Directory -Force -Path $ProfileDir | Out-Null

Write-Host "Creating Desktop shortcuts..." -ForegroundColor Cyan
New-Shortcut 'Claude TEAM'     $teamTarget $teamArgs "$exe,0"
New-Shortcut 'Claude Personal' $exe ('--user-data-dir="' + $ProfileDir + '"') "$exe,0"

Write-Host ""
Write-Host "Done! First login to your personal account (only once):" -ForegroundColor Yellow
Write-Host "  1. Close ALL Claude windows, including the tray icon near the clock." -ForegroundColor Yellow
Write-Host "  2. Open 'Claude Personal' and sign in with Google." -ForegroundColor Yellow
Write-Host "  3. Then open 'Claude TEAM' - it stays on your Team account." -ForegroundColor Yellow
Write-Host "After that, both shortcuts can run at the same time, in any order." -ForegroundColor Yellow
Write-Host ""
