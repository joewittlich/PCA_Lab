<#
.SYNOPSIS
  Bootstrap a fresh Windows 10/11 machine for the SRE PCA lab.
  Installs only what is missing: Git, WSL2, Docker Desktop, uv (which installs Python 3.12).

.USAGE
  Open PowerShell *as Administrator* (needed for WSL2 / Docker Desktop), cd into the repo, then:
    powershell -ExecutionPolicy Bypass -File .\scripts\bootstrap.ps1
  Re-run it after any reboot it asks for - it skips whatever is already installed.
#>
param([switch]$Yes)
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

function Say($m)  { Write-Host "==> $m" -ForegroundColor Cyan }
function Ok($m)   { Write-Host "  [ok] $m" -ForegroundColor Green }
function Warn($m) { Write-Host "  [!]  $m" -ForegroundColor Yellow }
function Have($c) { [bool](Get-Command $c -ErrorAction SilentlyContinue) }
function Refresh-Path {
    $m = [Environment]::GetEnvironmentVariable("Path", "Machine")
    $u = [Environment]::GetEnvironmentVariable("Path", "User")
    $env:Path = "$m;$u;$env:USERPROFILE\.local\bin"
}
function Confirm-Step($q) {
    if ($Yes) { return $true }
    $a = Read-Host "  $q [Y/n]"
    return ($a -eq "" -or $a -match "^[Yy]")
}
function Winget-Install($id, $name) {
    Say "Installing $name ($id) via winget"
    winget install --id $id -e --source winget --accept-package-agreements --accept-source-agreements
    if ($LASTEXITCODE -ne 0) { Warn "winget returned $LASTEXITCODE for $name (it may already be installed or need a reboot)" }
    Refresh-Path
}

$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator)
$needReboot = $false

Say "Windows $([Environment]::OSVersion.Version) - admin: $isAdmin"

# ---------------------------------------------------------------- winget
if (-not (Have winget)) {
    Warn "winget not found. Install 'App Installer' from the Microsoft Store (https://aka.ms/getwinget), then re-run."
    exit 1
}
Ok "winget $(winget --version)"

# ---------------------------------------------------------------- Git
if (Have git) { Ok "git $(git --version)" } else { Winget-Install "Git.Git" "Git" }

# ---------------------------------------------------------------- WSL2 (Docker Desktop backend)
$wslOk = $false
try {
    $null = wsl.exe --status 2>&1
    if ($LASTEXITCODE -eq 0) { $wslOk = $true }
} catch { $wslOk = $false }
if ($wslOk) {
    Ok "WSL is installed (Docker Desktop will use the WSL2 backend)"
} else {
    Warn "WSL2 is not installed. Docker Desktop needs it (or Hyper-V)."
    Warn "Also make sure virtualization is enabled in BIOS/UEFI (Task Manager > Performance > CPU > Virtualization: Enabled)."
    if ($isAdmin) {
        if (Confirm-Step "Run 'wsl --install --no-distribution' now? (reboot required afterwards)") {
            wsl.exe --install --no-distribution
            $needReboot = $true
        }
    } else {
        Warn "Re-run this script in an *Administrator* PowerShell to install WSL2, or run: wsl --install --no-distribution"
    }
}

# ---------------------------------------------------------------- Docker Desktop
if (Have docker) {
    Ok "docker CLI present"
} else {
    Warn "Docker Desktop is free for personal use, education and small businesses; larger companies need a paid plan."
    if (Confirm-Step "Install Docker Desktop?") {
        Winget-Install "Docker.DockerDesktop" "Docker Desktop"
        $needReboot = $true
    }
}

# ---------------------------------------------------------------- uv + Python
if (Have uv) { Ok "uv $(uv --version)" } else { Winget-Install "astral-sh.uv" "uv" }
if (-not (Have uv)) {
    Warn "uv not on PATH yet, trying the official installer"
    powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
    Refresh-Path
}
if (Have uv) {
    Say "Installing Python 3.12 + project dependencies with uv"
    uv python install 3.12
    uv sync
    if ($LASTEXITCODE -eq 0) { Ok "Python deps installed into $Root\.venv" } else { Warn "uv sync failed - see output above" }
} else {
    Warn "uv still not found - open a NEW PowerShell window and run: uv sync"
}

# ---------------------------------------------------------------- summary
Say "Checks"
if (Have git) { Ok "git" } else { Warn "git missing (open a new terminal?)" }
if (Have uv)  { Ok "uv" }  else { Warn "uv missing (open a new terminal?)" }
if (Have docker) {
    docker info *> $null
    if ($LASTEXITCODE -eq 0) { Ok "Docker engine running" }
    else { Warn "Docker installed but engine not running: start 'Docker Desktop' from the Start menu, accept the terms, wait for 'Engine running'." }
} else { Warn "docker missing" }

if ($needReboot) {
    Write-Host ""
    Warn "A REBOOT is required (WSL2 / Docker Desktop). After rebooting: start Docker Desktop, then re-run this script."
} else {
    Write-Host ""
    Write-Host "Next:  .\scripts\lab.ps1 up      (then open http://localhost:3000, admin/admin)"
}
