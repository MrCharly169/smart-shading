#!/usr/bin/env bash
set -euo pipefail

REMOTE="${1:-https://github.com/MrCharly169/smart-shading.git}"

command -v git >/dev/null 2>&1 || {
  echo "Git ist nicht installiert oder nicht im PATH." >&2
  exit 1
}

read -r -p "Der bestehende Remote-Verlauf wird einmalig ersetzt. Zum Fortfahren JA eingeben: " ANSWER
[[ "$ANSWER" == "JA" ]] || { echo "Abgebrochen."; exit 1; }

if [[ ! -d .git ]]; then
  git init -b main
fi

git checkout -B main
git add -A
if ! git diff --cached --quiet || ! git rev-parse --verify HEAD >/dev/null 2>&1; then
  git commit -m "chore: import verified Smart Shading 4.6 baseline"
fi

if git remote get-url origin >/dev/null 2>&1; then
  git remote set-url origin "$REMOTE"
else
  git remote add origin "$REMOTE"
fi

git push --force -u origin main
git branch -f develop main
git push --force -u origin develop

echo "Fertig. main und develop wurden vollständig übertragen."
