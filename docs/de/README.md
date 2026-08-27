<p align="right"><strong>Deutsch</strong> · <a href="../../README.md">English</a></p>

<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="../../custom_components/smart_shading/brand/dark_logo@2x.png">
    <img src="../../custom_components/smart_shading/brand/logo@2x.png" alt="Smart Shading — Adaptive Sonnen- und Hitzesteuerung" width="760">
  </picture>
</p>

<p align="center">
  <a href="https://github.com/MrCharly169/smart-shading/actions/workflows/validate.yml"><img alt="Validate-Status" src="https://img.shields.io/github/actions/workflow/status/MrCharly169/smart-shading/validate.yml?branch=develop&amp;style=flat-square&amp;label=validate"></a>
  <a href="https://github.com/MrCharly169/smart-shading/releases"><img alt="Neueste GitHub-Version einschließlich Vorabversionen" src="https://img.shields.io/github/v/release/MrCharly169/smart-shading?include_prereleases&amp;style=flat-square&amp;label=release"></a>
  <a href="https://github.com/MrCharly169/smart-shading/stargazers"><img alt="GitHub Stars" src="https://img.shields.io/github/stars/MrCharly169/smart-shading?style=flat-square"></a>
  <a href="https://github.com/MrCharly169/smart-shading/releases"><img alt="GitHub Release-Downloads" src="https://img.shields.io/github/downloads/MrCharly169/smart-shading/total?style=flat-square&amp;label=Release%20downloads"></a>
  <a href="https://hacs.xyz/docs/faq/custom_repositories/"><img alt="HACS Custom" src="https://img.shields.io/badge/HACS-Custom-41BDF5?style=flat-square"></a>
  <a href="#voraussetzungen-und-einschränkungen"><img alt="Home Assistant 2026.6 oder neuer" src="https://img.shields.io/badge/Home%20Assistant-2026.6%2B-41BDF5?style=flat-square"></a>
  <a href="../../LICENSE"><img alt="Lizenz MIT" src="https://img.shields.io/badge/License-MIT-yellow?style=flat-square"></a>
</p>

> **Beta-Kanal:** Die aktuelle Release-Linie auf `develop` verwendet GitHub-Prereleases. Aktiviere Vorabversionen in HACS nur, wenn du Beta-Builds bewusst testen möchtest. Die neueste Version ohne Prerelease-Kennzeichnung bleibt der Stable-Kanal.

**Smart Shading macht aus Home-Assistant-Cover-Entitäten eine kontextbezogene Beschattung, die auf die reale Sonne, den Raumzustand sowie ausdrückliche Sicherheits- und manuelle Signale reagiert statt nur festen Uhrzeiten zu folgen.**

## Warum Smart Shading?

Ein fester Zeitplan erkennt nicht, ob Sonne tatsächlich auf eine Fassade trifft, ob ein Raum Schutz benötigt oder ob jemand die Steuerung manuell übernommen hat. Smart Shading verbindet den Sonnenstand mit dem konfigurierten Fassadensektor und ausschließlich den von dir ausgewählten Raumeingängen.

- **Sonnenbezogen:** Entscheidungen folgen Fassadenrichtung und aktueller Sonnengeometrie, einer lokalen Lux-Quelle oder einem externen Direktsignal.
- **Raumbezogen:** Optionale Temperatur-, Anwesenheits-, Wetter-, Fenster-, Night- und Safety-Eingänge verfeinern Advanced-Entscheidungen.
- **Bewusst nachvollziehbar:** Card, Badge, Statussensoren und Diagnose zeigen aktiven Modus und Grund.
- **Manuelle Kontrolle zuerst:** Ausdrückliche Overrides und erkannte externe Bewegung können die Automation pausieren; aktive Safety hat weiterhin höchste Priorität.
- **Keine versteckten Annahmen:** Eine nicht verfügbare ausgewählte Quelle führt zu einem sichtbaren Hold, nicht zu einem heimlichen Ersatz durch Wetter, Lux, Geometrie oder den Wert null.

Smart Shading richtet sich an Home-Assistant-Nutzer mit vorhandenen Cover-Entitäten, die eine adaptive, fassadenbezogene Steuerung wünschen. Easy Mode eignet sich für einen übersichtlichen Einstieg; Advanced Mode für Räume mit gezielt ausgewählten Zeitplänen, Schutzebenen, Temperaturstufen oder detaillierter Diagnose. Smart Shading ist kein Hardwaretreiber, kein Wetterdienst und kein Ersatz für Sicherheitsgrenzen im Aktor.

## So sieht es in Home Assistant aus

Die folgenden Screenshots stammen aus dem disposable Home-Assistant-E2E-Labor des Repositorys mit neutralen Testdaten. Sie zeigen das echte mitgelieferte Frontend, keine Nachbildung und keine private Installation.

| Easy Mode | Advanced Mode |
| --- | --- |
| ![Easy-Mode-Card mit geöffneter Markise, Sonnenstatus und einem Manual Override](../images/easy-mode-card.jpg) | ![Advanced-Mode-Card mit Sonnenquelle, Fassadensektor, Cover-Zielen, maximaler Öffnung und Aktionen](../images/advanced-mode-card.jpg) |
| Kompakte Raumansicht mit wesentlichem Status und einem Override. | Detaillierte Ansicht mit ausgewählten Eingängen, Zielen, Begrenzungen und Diagnosezugriff. |

<p align="center"><img src="../images/status-badges.jpg" alt="Echte Smart-Shading-Status-Badges für Haus und Räume aus dem Home-Assistant-E2E-Labor" width="300"></p>
<p align="center"><em>Hybride Custom Badges für Haus und Räume. Home Assistant verwaltet Entity, Interaktion und Sichtbarkeit; Behangsymbol, Marker und Theme-Farbe zeigen den Zustand.</em></p>

## Funktionsweise

![Sensoreingänge fließen über Sektorentscheidung und Prioritäts- und Sicherheitslogik zu Cover-Gruppen, Card und Badge](../images/architecture-overview.svg)

Jeder Sonnensektor beschreibt den Himmelsbereich, aus dem Sonne eine Fassade erreichen kann. Ein Sektor verwendet genau eine maßgebliche Sonnenquelle; Raum- und Cover-Gruppen-Kontext bestimmen anschließend das Ziel.

![Draufsicht einer Fassade mit Nord-, Ost-, Süd- und West-Sonnensektoren um ein Haus](../images/facade-sectors.svg)

## Schnellstart

1. Prüfe, dass Home Assistant `2026.6.0` oder neuer `sun.sun` und die zu steuernden Cover-Entitäten bereitstellt.
2. Installiere Smart Shading über HACS als benutzerdefiniertes **Integration Repository** oder kopiere es manuell. Starte Home Assistant neu.
3. Füge **Smart Shading** unter **Einstellungen → Geräte & Dienste → Integration hinzufügen** hinzu, wähle Easy oder Advanced und richte einen Raum, Sektor, eine Cover-Gruppe und ein Cover ein.
4. Registriere `/smart_shading/shading.js` einmal als JavaScript-Modul und füge Card oder Badge mit dem YAML unten hinzu.
5. Teste die Ziele mit neutralen Bedingungen, bevor du automatische Bewegungen im Alltag nutzt.

## Installation

### HACS Custom Repository

Smart Shading wird nicht aus dem Standardkatalog von HACS installiert. Füge es einmal als Custom Repository hinzu:

1. Öffne **HACS → Integrationen**.
2. Öffne das HACS-Menü und wähle **Benutzerdefinierte Repositorys**.
3. Trage `https://github.com/MrCharly169/smart-shading` ein.
4. Wähle die Kategorie **Integration** und füge das Repository hinzu.
5. Öffne **Smart Shading**, wähle **Download** und starte Home Assistant neu.
6. Lasse Prereleases für Stable-Nutzung deaktiviert. Aktiviere sie nur bewusst für den Beta-Kanal.

HACS installiert den Quellstand eines veröffentlichten GitHub-Releases. `hacs.json` blendet den unversionierten Standardbranch aus, damit Entwicklungs-Snapshots nicht als Releases angeboten werden.

### Manuelle Installation

1. Lade das ZIP-Asset des gewünschten [GitHub-Releases](https://github.com/MrCharly169/smart-shading/releases) herunter.
2. Kopiere den enthaltenen Ordner `custom_components/smart_shading` in die Home-Assistant-Konfiguration. Der vollständige Pfad lautet danach:

   ```text
   <config>/custom_components/smart_shading
   ```

3. Starte Home Assistant neu.

Kopiere nicht nur die Frontend-Datei; Integration, Übersetzungen, Services und Card werden gemeinsam ausgeliefert.

## Erste Einrichtung

### Integration hinzufügen

1. Öffne **Einstellungen → Geräte & Dienste → Integration hinzufügen**.
2. Suche nach **Smart Shading**.
3. Wähle **Easy** oder **Advanced**. Die Auswahl ist für diesen Konfigurationseintrag fest; für die andere Variante ist ein neuer Eintrag nötig.
4. Benenne Haus oder Bereich und lege einen Raum an.
5. Lege einen Fassadensektor an, wähle seine einzelne Sonnenquelle, erstelle eine Cover-Gruppe, wähle ihr physisches Profil und ordne Cover zu.
6. Wähle in Advanced Mode nur die optionalen Fähigkeiten aus, die der Raum tatsächlich benötigt.
7. Prüfe und speichere die Konfiguration. Unvollständige Sektoren, Gruppen, Cover oder abhängige Optionen weist der Assistent zurück.

Home Assistants `sun.sun` wird automatisch verwendet. Fehlt die Sun-Integration oder ist sie nicht verfügbar, stoppt Smart Shading die Sektoreinrichtung und erklärt, was wiederhergestellt werden muss.

### Dashboard-Ressource registrieren

Registriere das mitgelieferte Frontend einmal unter **Einstellungen → Dashboards → Ressourcen**:

```text
URL:  /smart_shading/shading.js
Typ:  JavaScript-Modul
```

Die URL ist absichtlich versionslos. Updates ersetzen das JavaScript hinter demselben Pfad. Ältere Einträge mit `/smart_shading/smart-shading-card.js?v=...` funktionieren über einen Kompatibilitäts-Loader weiter, sollten aber einmalig auf die kanonische URL oben umgestellt werden.

### Card hinzufügen

```yaml
type: custom:smart-shading-card
entity: sensor.DEIN_RAUM_STATUS
```

Die Card leitet Easy- oder Advanced-Darstellung aus dem Konfigurationseintrag ab und besitzt keinen eigenen Modusschalter.

### Badge hinzufügen

```yaml
type: custom:smart-shading-badge
entity: sensor.DEIN_RAUM_ODER_HAUS_STATUS
tap_action:
  action: more-info
```

Wähle **Smart Shading status** und den Haus- oder Raumstatus über Home Assistants nativen Entity-Selector. Das Custom Badge kombiniert Behanglogo, Zustandsmarker und semantische Farbe. Navigation wird im nativen Tab Interaktionen und die bedingte Anzeige ausschließlich unter Sichtbarkeit konfiguriert; das Badge besitzt keine eigenen Navigate-, Hidden- oder Zustandsfelder. Die optionale Dashboard-Badge-Funktion im Setup erzeugt eine Onboarding-Hilfe, verändert aber nie automatisch ein bestehendes Dashboard.

## Easy oder Advanced?

| | Easy Mode | Advanced Mode |
| --- | --- | --- |
| Geeignet für | Übersichtliche Fassadensteuerung mit sicheren Standardwerten | Räume mit ausdrücklich ausgewähltem Zusatzverhalten |
| Sonnenquelle | Eine Quelle pro Sektor: Geometrie, Lux oder externes Ein/Aus | Dieselben Quellen plus editierbare Schwellen, Verzögerungen und eigene Geometrie |
| Temperatur | Optionaler Außensensor aktiviert automatisch seine Mindestbedingung | Optionale Innen-/Außentemperaturstufen und zugehörige Regler |
| Manuelle Kontrolle | Ein unbefristetes Manual Override pro Raum | Raum- und Cover-Pausen/Overrides, mit optionaler Erkennung externer Bewegung |
| Optionale Funktionen | Anleitung für Dashboard-Badges | Zeitpläne, Night, Safety, Bedingungen, Blendschutz, maximale Öffnung, Testwerkzeuge und Expertenausführung |
| Diagnose | Kompakter Status und Grund | Entscheidungs-Trace, abgelehnte Regeln, Eingangsqualität, Ziele, Schutzzonen und Befehlslebenszyklus |

Easy ist bewusst klein: wenige Entscheidungen, Profilstandardwerte, eine Quelle pro Sektor und ein verständliches Override. Advanced beginnt mit derselben Grundbeschattung und aktiviert nur die für den Raum ausgewählten Fähigkeiten. Nicht ausgewählte Advanced-Funktionen laufen nicht im Hintergrund und ergänzen keine Card-Steuerungen.

### Entscheidungs- und Sicherheitsphilosophie

Für Advanced-Entscheidungen ist die durch Code und Tests verifizierte, unveränderliche Reihenfolge:

1. aktive **Safety**;
2. manueller Master-Override, Raumpause oder lokale Cover-Pause;
3. Hold bei nicht verfügbarer konfigurierter Safety- oder Night-Quelle;
4. **Night**;
5. **Heat Protection**;
6. Zeitplan- oder Eingangsqualitäts-Hold;
7. **Glare Protection**;
8. **Solar**;
9. **Comfort**;
10. **Open** oder Idle-Hold.

Jeder passende und abgelehnte Kandidat bleibt im Advanced-Trace mit stabilem Grund und normalisierter Eingangsqualität erhalten. Die Befehlsplanung folgt erst danach. Ein neueres Ziel mit höherer Priorität verwirft veraltete verzögerte Arbeit. Die vollständigen technischen Verträge stehen unter [Advanced behavior](../ADVANCED_MODE.md) und [Mode architecture](../MODE_ARCHITECTURE.md).

### Berechneter Blendschutz

Eine Advanced-Schutzzone gehört zu genau einem physischen Behang und beschreibt das lichte Fenster sowie den Tisch, Sitzplatz, Bildschirm oder anderen Bereich, der nicht direkt von der Sonne getroffen werden soll. Seitlich laufende Vorhänge können mittig, von links nach rechts oder von rechts nach links schließen. Bei einem einseitigen Vorhang begrenzt Smart Shading den berechneten Sonnenkorridor auf die echte Fensteröffnung und folgt dessen wandernder Kante. Die aktuelle 3D-Sonnengeometrie bestimmt direkt das aktuelle Prozentziel. Wird eine Anwesenheitsbedingung erst erfüllt, nachdem die Sonne weiter in den Schutzbereich gewandert ist, erhält der Behang deshalb sofort das geometrisch erforderliche Ziel, zum Beispiel 45% oder 30%, statt einer künstlichen Zwischenstufe. Ein strengeres normales Solar- oder Safety-Ziel behält seinen Vorrang.

Dieselbe Zone kann eine oder mehrere native Home-Assistant-Bedingungen enthalten. So kann zum Beispiel ein binärer Präsenzbereich verlangen, dass jemand am Tisch sitzt, eine Wetterbedingung `sunny` verlangen und ein numerischer Grenzwert in UND-, ODER- oder NICHT-Gruppen eingebunden werden. Zonenbezogene Ein- und Ausschaltverzögerungen entprellen diese Bedingungen: Neue Zonen verlangen standardmäßig 60 Sekunden ununterbrochen erfüllte Bedingungen und halten nach einer falschen oder nicht verfügbaren Bedingung noch 300 Sekunden nach. Die Verriegelung übersteht Neustarts, verzögert aber niemals das geometrische Verlassen der Fassade, des Höhenbereichs oder der Schutzzone. Jede Zone erhält außerdem eine eigene minimale Sonnenhöhe und kann die Lux- oder externe Sonnenbestätigung ausdrücklich nur für den Blendschutz ignorieren; Fassadenrichtung, Geometrie, Zeitplan und Zonenbedingungen gelten weiterhin. Die Advanced Card beschriftet das Ziel jedes einzelnen Behangs mit seinem aktiven Modus, etwa **Blendschutz** oder **Sonnenschutz**.

## Unterstützte Cover-Profile

| Profil | Steuerungsmodell |
| --- | --- |
| Außenjalousie | Position plus Lamellenführung einschließlich adaptiver Lamellenkurve |
| Rollladen | Positionsziele |
| Außen- oder Zip-Screen | Positionsziele |
| Innenvorhang | Positionsziele |
| Vertikaljalousie | Position plus Lamellenführung |
| Markise | Positionsziele mit eingefahrener Neutral- und Safety-Position |
| Einfaches Open/Close-Cover | Nur Open/Close-Services, keine numerischen Zielfelder |

Das gewählte physische Profil ändert Assistentenfelder, Standardwerte, Befehle, Entitäten und Card-Darstellung. Wind- und Frost-Safety-Quellen werden nur für passende Außenprofile angeboten. Ein Profilwechsel setzt inkompatible Profilwerte zurück, behält aber zugeordnete Cover.

Für die Cover-Position gilt die Home-Assistant-Semantik: `0%` geschlossen und `100%` offen. Smart Shadings Lamellenkonvention verwendet die KNX-orientierte Skala seiner Profile: `0%` offen/lichtdurchlässig und `100%` geschlossen/sonnenblockend. Nutze **Invert slats** nur, wenn ein unterstütztes Cover die Gegenrichtung meldet.

## Voraussetzungen und Einschränkungen

- Home Assistant `2026.6.0` oder neuer.
- Die native Sun-Integration und eine verfügbare Entität `sun.sun`.
- Vorhandene Home-Assistant-Cover-Entitäten; Smart Shading kommuniziert nicht direkt mit Motoren.
- Genau eine Sonnenquelle pro Sektor. Quellen werden nicht kombiniert und es gibt keinen versteckten Fallback.
- Ohne Außentemperatursensor wird die Außentemperatur ignoriert. Ist ein ausgewählter Sensor nicht verfügbar, gilt seine Bedingung nicht als erfüllt.
- Easy/Advanced ist pro Konfigurationseintrag fest.
- Der allgemeine Advanced-Beschattungszeitplan erlaubt alle Tagesmodi; Night besitzt eine unabhängige Quelle oder einen sonnenbezogenen Zeitraum.
- Berechnete Objekt-Blendschutzgeometrie gibt es nur für kompatible Advanced-Profile; Außenjalousien und Markisen werden vom Rechner nicht angeboten, Ergebnisse für Vertikallamellen sind Näherungen.
- Softwareautomation ersetzt keine physischen Endlagen, Aktorschutzfunktionen oder geeignete Wind-/Frostsicherung. Prüfe Ziele und Fail-safe-Verhalten für deine Anlage.

### Lokale Verarbeitung und Datenschutz

Smart Shading liest Entitätszustände, berechnet Entscheidungen, speichert seine Laufzeitdaten und ruft Cover-Services innerhalb von Home Assistant auf. Das Manifest deklariert die IoT-Klasse `calculated`, enthält keine Python-Abhängigkeiten zu Drittanbietern und die Integration besitzt keinen Cloud-Client oder Telemetrie-Endpunkt. Diese Aussage gilt für Smart Shading selbst; Home Assistant, HACS und die Integrationen deiner Entitäten können eigenes Netzwerk- und Datenschutzverhalten haben.

## Aktualisieren

1. Aktualisiere Smart Shading in HACS oder ersetze den vollständigen Ordner `custom_components/smart_shading` durch die Dateien eines neueren Releases.
2. Starte Home Assistant neu.
3. Lade Browser oder Companion App neu, falls noch alter Card-Code im Speicher liegt.

Behalte `/smart_shading/shading.js` unverändert und ergänze keinen Versionsparameter.

## Deinstallieren

1. Entferne den Smart-Shading-Konfigurationseintrag unter **Einstellungen → Geräte & Dienste**.
2. Entferne Smart Shading in HACS oder lösche bei manueller Installation `<config>/custom_components/smart_shading`.
3. Starte Home Assistant neu.
4. Wenn kein Smart-Shading-Eintrag mehr besteht, entferne `/smart_shading/shading.js` aus den Dashboard-Ressourcen sowie Cards und Badges aus deinen Dashboards.

Die Deinstallation entfernt oder verändert keine Cover-Entitäten anderer Integrationen.

## FAQ und Fehlerbehebung

**Die Card meldet „Custom element doesn't exist“.**

Prüfe, dass `/smart_shading/shading.js` als JavaScript-Modul registriert ist, starte Home Assistant nach der Installation neu und lade Browser oder Companion App neu.

**Warum wartet die normale Beschattung?**

Prüfe den Grund in Card und Raumstatussensor. Die Sonne kann außerhalb des Sektors liegen, Zeitplan oder Temperaturbedingung können inaktiv oder ein ausgewählter Lux-/Externer-/Temperatur-Eingang nicht verfügbar sein. Smart Shading ersetzt die Quelle nicht.

**Brauche ich einen Lux- oder Außentemperatursensor?**

Nein. Ein Sektor kann nur Sonnengeometrie nutzen; ohne gewählten Sensor wird die Außentemperatur ignoriert. Lux und externe Direktsignal-Entitäten sind alternative maßgebliche Quellen, keine zusätzlichen Fallbacks.

**Kann ich einen bestehenden Eintrag von Easy auf Advanced umstellen?**

Nein. Der Setup-Vertrag bleibt fest, damit keine versteckten Moduseinstellungen entstehen. Erstelle einen separaten Konfigurationseintrag und richte ihn bewusst ein.

**Home Assistant zeigt eine falsche KNX-Cover-Bewegung. Was soll ich prüfen?**

Lies den [KNX-Leitfaden zur Fehlerbehebung](../FAQ.md#why-does-home-assistant-show-a-knx-cover-moving-although-the-motor-is-idle), bevor du Aktor- oder State-Updater-Einstellungen änderst.

Weitere Antworten stehen in den [FAQ](../FAQ.md). Für Einrichtungshilfe siehe [Support](../../SUPPORT.md). Suche bei einem reproduzierbaren Fehler zuerst in den vorhandenen [Issues](https://github.com/MrCharly169/smart-shading/issues) und nutze anschließend das Bug-Report-Template mit anonymisierter Diagnose. Sicherheitsprobleme folgen [SECURITY.md](../../SECURITY.md).

## Lizenz und freiwillige Unterstützung

Smart Shading ist Open-Source-Software unter der [MIT-Lizenz](../../LICENSE). Private und kommerzielle Nutzung sind nach Maßgabe dieser Lizenz erlaubt; es gibt keine separate kommerzielle Lizenz oder Gebühr. Die Software wird ohne Gewährleistung bereitgestellt, wie in der Lizenz beschrieben.

Freiwilliges Sponsoring kann Entwicklung, Tests, Dokumentation und Wartung unterstützen, ist aber niemals eine Lizenzgebühr. **Platzhalter für Finanzierungslink:** Im Repository ist derzeit keine verifizierte Buy-Me-a-Coffee- oder GitHub-Sponsors-URL vorhanden; deshalb wurde kein Funding-Badge ergänzt.

## Technische Dokumentation und Entwicklung

- [Advanced behavior](../ADVANCED_MODE.md)
- [Mode and decision architecture](../MODE_ARCHITECTURE.md)
- [Setup-wizard behavior contract](../SETUP_WIZARD_REVIEW.md)
- [Home Assistant E2E laboratory](../HA_E2E_LAB.md)
- [Regression matrix](../REGRESSION_MATRIX.md)
- [Development guide](../DEVELOPMENT.md)
- [Contributing](../../CONTRIBUTING.md)
- [Changelog](../../CHANGELOG.md)
