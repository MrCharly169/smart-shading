# Changelog

## Unreleased


## 4.6.0-beta.2

### Heat Protection

- Heat Protection mit aktivierter Sonnenpflicht verwendet die kombinierte Sun Presence aller aktivierten Sektoren eines Raums
- ein Sektor mit bestätigter Sun Presence genügt für den gesamten Raum
- Sun Presence ist ausschließlich eine Startbedingung; nach dem Start bleibt Heat Protection unabhängig von späteren OFF-Zuständen aktiv
- auch sinkende Innenraumtemperaturen lösen eine laufende Heat Protection nicht vorzeitig auf
- Schedule, Wetterfreigabe und konfigurierte Außentemperatur-Mindestgrenze werden beim Start berücksichtigt
- nur der konfigurierte Evening Release öffnet wieder und sperrt einen weiteren Heat-Zyklus bis zum nächsten Tagesreset
- deaktivierte Sektoren sowie ungültige oder nicht verfügbare Luxwerte zählen beim Start nicht als bestätigte Sonne
- bei deaktivierter Sonnenpflicht bleibt das bisherige rein temperaturbasierte Verhalten erhalten



### Repository, Frontend und Releases

- manuellen Release-Trigger mit klarer Auswahl zwischen Beta (`develop`) und Stable (`main`) ergänzt
- Beta-Versionen werden als GitHub-Prerelease, Stable-Versionen als aktuelles Release veröffentlicht
- Branch, SemVer, Changelog, Bestätigung und doppelte Tags werden vor jeder Veröffentlichung geprüft
- HACS bietet nur veröffentlichte Versionen und keine unversionierten Branch-Snapshots an
- englische und deutsche Dokumentation um Beta-/Stable- und HACS-Testablauf erweitert
- kanonische Dashboard-Ressource auf die dauerhaft stabile URL `/smart_shading/shading.js` umgestellt
- Versionsparameter aus der Resource-URL entfernt; Home Assistant muss bei Upgrades nicht mehr angepasst werden
- bisherige `smart-shading-card.js` bleibt als Kompatibilitäts-Loader erhalten
- technische Versionsnummer ausschließlich im Integrations-Manifest gepflegt
- Pull Requests mit Produktionsänderungen müssen gleichzeitig das Changelog aktualisieren
- validierter Tag-Workflow erstellt automatisch Installations-ZIP und GitHub Release
- README, deutsche Anleitung, Entwicklungsdokumentation und CI an den neuen Release-Prozess angepasst


## 4.6.0-beta.1

### Kernstabilität

- vollständiger Review von Engine, Persistenz, Triggern, Wizard, Card und Diagnose
- Zahlenparser akzeptiert reale HA-Zustände wie `26398.72`, `26,398.72` und `26.398,72`
- keine stillschweigende Umwandlung ungültiger Sensorwerte in `0`
- Innen-/Außentemperatur und Lux verwenden dieselbe robuste Zahlenleselogik
- fehlende oder `unavailable` Zustände bleiben `None`

### Sun Presence

- `26398.72 lx` schaltet im Profil „Ausgewogen“ nach drei Minuten ON
- Presets sind gegenüber veralteten Beta-Grenzen maßgeblich
- nur „Benutzerdefiniert“ verwendet individuelle Grenzen
- eigener exakter Timer für ON-/OFF-Verzögerung
- Lux-Übergang aktualisiert Sun Presence, die vollständige Raumfahrt bleibt im normalen 20-Minuten-Takt
- Rohwert, Einheit, effektive Grenzen und Pending-Zeit in Entität, Card und Diagnosen

### Manuelle Bedienung

- externe Coverbewegung startet lokale Pause nur für dieses Cover
- konfigurierte Sperre wird ON geschaltet; Switch und Input Boolean werden unterstützt
- Sperre OFF beendet Pause sofort und löst Neuauswertung aus
- Pauseablauf schaltet Sperre OFF und evaluiert exakt einmal
- wiederholte Fahrtelegramme verlängern eine bereits aktive Pause nicht
- eigenes Coverfeedback wird über Ziel, Richtung, Toleranz und Zeitfenster erkannt
- Initialzustand `unavailable → open` gilt nicht als manuelle Bedienung
- unmittelbares Benutzer-Unlock wird nicht mehr mit internem Lock-Feedback verwechselt
- Safety überschreibt lokale Pause und reagiert bei manueller Bewegung sofort

### Raum-Pause und Master

- eigener Ablauf-Timer für Raum-Pausen
- Master EIN deaktiviert ohne Gegenfahrt und ohne automatischen Reset
- Master AUS löst sofortige Neuauswertung aus
- Safety bleibt höher priorisiert

### Trigger und Last

- normale Vollauswertung standardmäßig alle 20 Minuten
- Temperatur, normaler Sonnenstand und Lux-Messwertänderungen werden gebündelt
- sofortige Auswertung nur für kritische Freigaben/Safety/Fenster/Override-Ende

### Card

- lokaler Pausezustand ohne JavaScript-ReferenceError
- kleinere Icons mit `--mdc-icon-size`
- eigene Sections-Grid-Regeln gegen zu schmale Darstellung
- aktive Sun Presence pulsiert; Heat, Safety und Master werden animiert
- effektive Temperaturgrenzen steuern die Farben
- Sektorkürzel öffnet den richtigen Sun-Presence-Sensor
- Hand-Button ruft den Switch korrekt über `switch.toggle` auf

### Diagnose und Migration

- irreführende alte Blockierungszähler werden einmalig zurückgesetzt
- echte Blockierungen werden weiterhin gezählt; `already_correct` und Cooldowns nicht
- erweiterter offizieller HA-Diagnoseexport und zusätzlicher JSON-Export
- Config-Entry-Schema 9, Runtime-Schema 2
