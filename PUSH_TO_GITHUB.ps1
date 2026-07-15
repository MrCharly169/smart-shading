param(
    [string]$Remote = "https://github.com/MrCharly169/smart-shading.git"
)

$ErrorActionPreference = "Stop"

if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    throw "Git ist nicht installiert oder nicht im PATH. Installiere Git for Windows oder verwende GitHub Desktop."
}

$answer = Read-Host "Der bestehende Remote-Verlauf wird einmalig ersetzt. Fortfahren? Tippe JA"
if ($answer -ne "JA") {
    Write-Host "Abgebrochen."
    exit 1
}

if (-not (Test-Path ".git")) {
    git init -b main
}

git checkout -B main

git add -A
$pending = git status --porcelain
if ($pending) {
    git commit -m "chore: import verified Smart Shading 4.6 baseline"
} elseif (-not (git rev-parse --verify HEAD 2>$null)) {
    git commit --allow-empty -m "chore: import verified Smart Shading 4.6 baseline"
}

$origin = git remote get-url origin 2>$null
if ($LASTEXITCODE -eq 0) {
    git remote set-url origin $Remote
} else {
    git remote add origin $Remote
}

git push --force -u origin main
git branch -f develop main
git push --force -u origin develop

Write-Host "Fertig. main und develop wurden vollständig übertragen."
