# Sauberer GitHub-Import

Dieses Paket ersetzt den fehlgeschlagenen Bootstrap-Import. Es enthält den vollständigen, lokal geprüften Smart-Shading-Quellstand.

## Empfohlener Weg: native Git-Übertragung

Der vorhandene GitHub-Repository-Inhalt enthält nur temporäre Bootstrap-Dateien. Deshalb wird `main` einmal gezielt durch diesen geprüften Stand ersetzt.

### Windows mit Git Bash oder PowerShell

1. Dieses ZIP entpacken.
2. Im entpackten Projektordner ein Terminal öffnen.
3. `PUSH_TO_GITHUB.ps1` in PowerShell oder `PUSH_TO_GITHUB.sh` in Git Bash ausführen.
4. GitHub authentifiziert sich über den auf dem Computer eingerichteten Credential Manager beziehungsweise SSH-Key.

### Manuelle Befehle

```bash
git init -b main
git add .
git commit -m "chore: import verified Smart Shading 4.6 baseline"
git remote add origin https://github.com/MrCharly169/smart-shading.git
git push --force -u origin main
git branch develop
git push --force -u origin develop
```

`--force` wird hier einmalig benötigt, weil der bestehende Remote-Branch ausschließlich den fehlgeschlagenen Bootstrap-Versuch enthält. Anschließend werden Änderungen normal über Branches und Pull Requests übertragen.

## Alternative mit dem Git-Bundle

Das mitgelieferte `smart-shading-verified.bundle` enthält bereits `main` und `develop`:

```bash
git clone smart-shading-verified.bundle smart-shading
cd smart-shading
git remote set-url origin https://github.com/MrCharly169/smart-shading.git
git push --force -u origin main
git push --force -u origin develop
```

## Sicherheitsregel

Keine Tokens, Passwörter, `.storage`-Dateien oder Home-Assistant-Konfigurationen mit persönlichen Entitäten in dieses Repository aufnehmen.
