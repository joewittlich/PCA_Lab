<#
.SYNOPSIS
  Day-to-day commands for the SRE PCA lab on Windows (PowerShell 5.1+ or 7+).
.EXAMPLE
  .\scripts\lab.ps1 up
  .\scripts\lab.ps1 load 30m 40
  .\scripts\lab.ps1 fault latency 300
  .\scripts\lab.ps1 analyze --run latest
#>
param(
    [Parameter(Position = 0)][string]$Command = "help",
    [Parameter(Position = 1, ValueFromRemainingArguments = $true)][string[]]$Rest = @()
)
$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)

$AppPort  = if ($env:APP_PORT) { $env:APP_PORT } else { "8000" }
$PromPort = if ($env:PROMETHEUS_PORT) { $env:PROMETHEUS_PORT } else { "9090" }
$GrafPort = if ($env:GRAFANA_PORT) { $env:GRAFANA_PORT } else { "3000" }
if (-not $env:APP_URL)  { $env:APP_URL  = "http://localhost:$AppPort" }
if (-not $env:PROM_URL) { $env:PROM_URL = "http://localhost:$PromPort" }

function Invoke-Compose {
    docker compose @args
    if ($LASTEXITCODE -ne 0) { throw "docker compose $args failed (exit $LASTEXITCODE)" }
}

function Invoke-Py {
    if (Get-Command uv -ErrorAction SilentlyContinue) {
        uv run @args
    } elseif (Test-Path ".venv\Scripts\python.exe") {
        $env:PATH = "$PWD\.venv\Scripts;$env:PATH"
        $exe = $args[0]; $rest = @($args | Select-Object -Skip 1)
        & $exe @rest
    } else {
        throw "Neither uv nor .venv found. Run .\scripts\bootstrap.ps1 (or see README pip fallback)."
    }
}

function Test-DockerEngine {
    $prev = $ErrorActionPreference
    $ErrorActionPreference = "SilentlyContinue"
    try { docker info *> $null; $ok = ($LASTEXITCODE -eq 0) } catch { $ok = $false }
    finally { $ErrorActionPreference = $prev }
    return $ok
}

function Assert-Docker {
    if (-not (Test-DockerEngine)) {
        throw "Docker is not running. Start Docker Desktop (Start menu) and wait until it says 'Engine running', then retry."
    }
}

function Show-Usage {
@"
Usage: .\scripts\lab.ps1 <command> [args]

Stack:    up | down | nuke | status | logs [service]
Load:     load [dur] [rps] | load-bg [dur] [rps] | load-stop
Faults:   fault latency <ms> | fault cpu on|off | fault errors <rate> | fault reset | fault status
          scenario [--baseline-min 5 --fault-min 2 --gap-min 2]
Analysis: analyze [--run latest | --minutes 40 ...] | synthetic | notebook | exporter | test | test-short
"@
}

switch ($Command) {
    "up"     { Assert-Docker; Invoke-Compose up -d --build; & $PSCommandPath status }
    "down"   { Invoke-Compose down }
    "nuke"   { Invoke-Compose --profile load down -v }
    "status" {
        Invoke-Compose ps
        Write-Host ""
        try {
            $t = Invoke-RestMethod "$($env:PROM_URL)/api/v1/targets" -TimeoutSec 3
            Write-Host "Prometheus targets:"
            foreach ($x in $t.data.activeTargets) { "  {0,-18} {1,-7} {2}" -f $x.labels.job, $x.health, $x.lastError }
        } catch { Write-Host "  (Prometheus not reachable at $($env:PROM_URL) yet)" }
        Write-Host ""
        Write-Host "Grafana:    http://localhost:$GrafPort  (admin / admin)"
        Write-Host "Prometheus: $($env:PROM_URL)"
        Write-Host "Demo app:   $($env:APP_URL)/docs"
    }
    "logs"   { docker compose logs -f @Rest }
    "load" {
        Assert-Docker
        $env:LOAD_DURATION = if ($Rest.Count -ge 1) { $Rest[0] } else { "10m" }
        $env:LOAD_RPS      = if ($Rest.Count -ge 2) { $Rest[1] } else { "20" }
        try { Invoke-Py python -m sre_pca.runs load-start --duration $env:LOAD_DURATION --rps $env:LOAD_RPS }
        catch { Write-Host "warning: could not write the run manifest" }
        try { Invoke-Compose --profile load run --rm k6 }
        finally {
            try { Invoke-Py python -m sre_pca.runs load-end } catch { Write-Host "warning: could not record the load end time" }
        }
    }
    "load-bg" {
        Assert-Docker
        $env:LOAD_DURATION = if ($Rest.Count -ge 1) { $Rest[0] } else { "10m" }
        $env:LOAD_RPS      = if ($Rest.Count -ge 2) { $Rest[1] } else { "20" }
        try { Invoke-Py python -m sre_pca.runs load-start --duration $env:LOAD_DURATION --rps $env:LOAD_RPS }
        catch { Write-Host "warning: could not write the run manifest" }
        Invoke-Compose --profile load up -d k6
        Write-Host "k6 running in background: .\scripts\lab.ps1 logs k6"
    }
    "load-stop" {
        Invoke-Compose --profile load stop k6
        Invoke-Compose --profile load rm -f k6
        try { Invoke-Py python -m sre_pca.runs load-end } catch { Write-Host "warning: could not record the load end time" }
    }
    "fault"     { Invoke-Py sre-fault @Rest }
    "scenario"  { Invoke-Py sre-scenario @Rest }
    "analyze"   { Invoke-Py sre-pca @Rest }
    "synthetic" { Invoke-Py sre-pca --source synthetic @Rest }
    "notebook"  { Invoke-Py jupyter lab --notebook-dir=notebooks }
    "exporter"  { Invoke-Py sre-pca-exporter @Rest }
    "test"       { Invoke-Py pytest -q }
    "test-short" { Invoke-Py pytest -q -m short_run }
    default     { Show-Usage }
}
