[CmdletBinding()]
param(
    [ValidateSet("start", "stop", "restart", "logs", "status", "watch")]
    [string]$Command = "start"
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$composeFile = Join-Path $repoRoot "compose.dev.yaml"
$configDir = Join-Path $repoRoot ".dev\ha-config"
$dockerCommand = Get-Command docker -ErrorAction SilentlyContinue
$dockerExecutable = if ($dockerCommand) { $dockerCommand.Source } else { $null }

if (-not $dockerExecutable) {
    $desktopDocker = Join-Path $env:LOCALAPPDATA "Programs\DockerDesktop\resources\bin\docker.exe"
    if (Test-Path -LiteralPath $desktopDocker) {
        $dockerExecutable = $desktopDocker
    }
}

if ($dockerExecutable) {
    $dockerBin = Split-Path -Parent $dockerExecutable
    if (($env:PATH -split ";") -notcontains $dockerBin) {
        $env:PATH = "$dockerBin;$env:PATH"
    }
}

function Invoke-Compose {
    & $dockerExecutable compose --file $composeFile @args
    if ($LASTEXITCODE -ne 0) {
        throw "docker compose failed with exit code $LASTEXITCODE"
    }
}

if (-not $dockerExecutable) {
    throw "Docker CLI was not found. Install and start Docker Desktop with the WSL 2 backend first."
}

switch ($Command) {
    "start" {
        New-Item -ItemType Directory -Force -Path $configDir | Out-Null
        Invoke-Compose up --detach
        Write-Host "Home Assistant: http://127.0.0.1:8123"
        Write-Host "Logs: powershell -ExecutionPolicy Bypass -File .\scripts\dev.ps1 logs"
        Write-Host "Backend watcher: powershell -ExecutionPolicy Bypass -File .\scripts\dev.ps1 watch"
    }
    "stop" {
        Invoke-Compose down
    }
    "restart" {
        Invoke-Compose restart home-assistant
    }
    "logs" {
        Invoke-Compose logs --follow home-assistant
    }
    "status" {
        Invoke-Compose ps
    }
    "watch" {
        New-Item -ItemType Directory -Force -Path $configDir | Out-Null
        Invoke-Compose up --detach

        $sourceDir = Join-Path $repoRoot "custom_components\smart_shading"
        $watcher = New-Object System.IO.FileSystemWatcher
        $watcher.Path = $sourceDir
        $watcher.Filter = "*"
        $watcher.IncludeSubdirectories = $true
        $watcher.EnableRaisingEvents = $true

        Write-Host "Watching Smart Shading sources. Press Ctrl+C to stop."
        Write-Host "Python, JSON and YAML changes restart Home Assistant; frontend files are bind-mounted live."

        try {
            while ($true) {
                $change = $watcher.WaitForChanged(
                    [System.IO.WatcherChangeTypes]"Changed, Created, Deleted, Renamed",
                    1000
                )
                if ($change.TimedOut) {
                    continue
                }

                $extension = [System.IO.Path]::GetExtension($change.Name).ToLowerInvariant()
                if ($extension -in ".py", ".json", ".yaml", ".yml") {
                    Write-Host "Backend change detected ($($change.Name)); restarting Home Assistant..."
                    Start-Sleep -Milliseconds 500
                    Invoke-Compose restart home-assistant
                }
            }
        }
        finally {
            $watcher.Dispose()
        }
    }
}
