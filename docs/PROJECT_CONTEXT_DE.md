# Projektkontext: Smart Shading

Stand: 21. Juli 2026  
Quellen: eingecheckter Repository-Stand und der vom Projektinhaber bereitgestellte [ursprüngliche ChatGPT-Chat](https://chatgpt.com/share/6a585d62-a660-83eb-94a2-b737ce02543e).

## Ziel

Smart Shading ist eine Home-Assistant-Custom-Integration für sektorbasierte, KNX-taugliche Beschattung. Sie entscheidet aus Sonnenstand, Helligkeit, Temperaturen, Fensterkontakten und Safety-Signalen über die gewünschte Stellung von Covers und Jalousien. Die Integration soll dabei nachvollziehbar, fehlertolerant und manuell übersteuerbar sein.

## Fachliche Leitplanken

- Sicherheit hat immer Vorrang vor normaler Beschattung, Raum-Pause und lokalen Pausen.
- Eine unerwartete manuelle Bewegung pausiert nur das betroffene Cover, statt eine Gegenfahrt auszulösen.
- Der manuelle Master schaltet die normale Raumautomatik dauerhaft aus; Safety bleibt aktiv.
- Raum-Pause, lokale Cover-Pause und Master-Override sind unterschiedliche Zustände und dürfen nicht ineinander überführt werden.
- Easy Mode und Advanced Mode sind ausschließlich unterschiedliche Konfigurationsansichten. Beide verwenden dasselbe kanonische Konfigurationsmodell und dieselbe Runtime-Engine.
- Positions- und Lamellenwerte folgen der Home-Assistant-Semantik: `0 %` geschlossen, `100 %` offen.
- Regelmäßige Auswertung erfolgt standardmäßig alle 20 Minuten; sicherheits- und bedienungsrelevante Änderungen werten sofort neu aus.

## Architektur und Bedienung

- Integrationsdomain: `smart_shading`
- Python-Integration: `custom_components/smart_shading/`
- kanonische Lovelace-Ressource: `/smart_shading/shading.js`
- Hauptbestandteile: Config Flow, Entscheidungsengine, Controller, Entitäten, Diagnoseexport und Custom Card.
- Die Card zeigt Raum-/Sektorstatus, Coverstatus und Pausenzustände; sie bietet Raum-Pause, Sofortauswertung, manuellen Master und die Advanced View.

## Aktueller Arbeitsstand

- `main` basiert auf Version `4.6.0-beta.2`.
- `develop` ist der ausschließliche Beta-Kanal; `main` ist der Stable-Kanal.
- Versionen werden ausschließlich in `custom_components/smart_shading/manifest.json` geführt.
- Alle noch nicht veröffentlichten, sichtbaren Änderungen gehören nach `CHANGELOG.md → Unreleased`.
- Die CI validiert Tests, Frontend, Paketstruktur, Versions-/Changelog-Konsistenz und Releases.

## Bekannte Themen aus der bisherigen Entwicklung

- zuverlässige Erkennung manueller KNX-/Home-Assistant-Fahrten und der Statusrückmeldung;
- gemeinsames Freigeben mehrerer Covers beziehungsweise Gruppen;
- Pausenlogik und deren Darstellung in der Card;
- Jalousie-/Lamellenrichtung einschließlich globaler Invertierung und cover-spezifischer Ausnahme;
- HACS-Veröffentlichung, Beta-/Stable-Workflow und Updates der Lovelace-Ressource;
- klare, schrittweise Einrichtung im Wizard, ohne die bestehende Entscheidungslogik zu verändern.

## Arbeitsregeln für weitere Änderungen

1. Bestehende Logik nicht beiläufig verändern; fachliche Änderungen zuerst als klaren Entscheid oder Issue festhalten.
2. Für jede produktrelevante Änderung Regressionstest, Changelog und bei Bedarf Dokumentation anpassen.
3. Keine zweite Engine oder parallele Konfiguration für Easy/Advanced einführen.
4. Die versionlose Ressource `/smart_shading/shading.js` beibehalten.
5. Releases nur über den vorgesehenen GitHub-Workflow erstellen.

Weiterführende Referenzen: [README_DE.md](../README_DE.md), [MODE_ARCHITECTURE.md](MODE_ARCHITECTURE.md), [DEVELOPMENT.md](DEVELOPMENT.md), [REGRESSION_MATRIX.md](REGRESSION_MATRIX.md).
