# Preflight-Bericht – Smart Shading 4.6.0-beta.1

## Erfolgreich geprüft

- Python-Kompilierung aller Integrationsmodule
- Modulweite Prüfung auf nicht definierte globale Namen
- JSON- und Übersetzungsdateien
- JavaScript-Syntax
- echter Node-Lauf von Card, Editor und Advanced Dialog
- 79 automatisierte Regressionstests
- realer Luxwert `26398.72`
- veraltete Presetwerte werden nicht verwendet
- External Cover → Pause → Lock ON
- Lock OFF → Pause Ende → sofortige Auswertung
- Input Boolean und Switch als Lock
- eigener Befehl versus Fremdbewegung
- Initialzustand versus echte Bewegung
- Raum- und Cover-Pausentimer
- Safety-Override
- Fensterblockierung
- 20-Minuten-Triggerstrategie
- Sections-Grid und Icongrößen

## Nicht in der Build-Umgebung möglich

- echter Start unter Home Assistant Core 2026.7.2
- reale KNX-Telegrammfolge und Aktor-Laufzeiten
- visuelle Prüfung auf dem konkreten Browser-/Dashboard-Theme

Deshalb zuerst einen Pilotraum verwenden und das offizielle Diagnosepaket nach den ersten Fahrten sichern.
