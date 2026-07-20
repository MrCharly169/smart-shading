# Smart Shading

Smart Shading ist eine Home-Assistant-Custom-Integration für sektorbasierte Beschattung mit Sonnenstand, Lux, Temperatur, Safety, Fensterkontakten sowie manuellen Overrides.

## Verzeichnis und Domain

```text
/config/custom_components/smart_shading
```

Domain:

```text
smart_shading
```

Dashboard-Ressource:

```text
/smart_shading/shading.js
```

Card:

```yaml
type: custom:smart-shading-card
entity: sensor.DEIN_RAUMSTATUS
```

Die Card übernimmt den in der Integration gewählten Modus automatisch. Sie hat
keinen eigenen Easy-/Advanced-Schalter.

## Easy und Advanced Mode

- **Easy Mode** verwendet ausschließlich `sun.sun`, den konfigurierten
  Fassadensektor, die Behangziele und einen raumweiten **Manual Override**. Der
  Override bleibt aktiv, bis ein Benutzer oder eine explizite Automation ihn
  ausschaltet.
- **Advanced Mode** ergänzt Sun Presence/Lux, Temperaturen, Wetter, Zeitpläne,
  Safety, Pause, Heat Protection, Nachtfunktion, Diagnose, Manual-Entitäten pro
  Behang und die optionale Erkennung externer Fahrten.

Advanced-Einstellungen bleiben beim Wechsel zu Easy gespeichert, werden dort
aber nicht ausgeführt. Bei neuen Räumen ist die Pausenerkennung durch externe
Fahrten aus, bis sie im Advanced Mode ausdrücklich aktiviert wird.

## Voraussetzungen

- Home Assistant 2026.6 oder neuer
- funktionsfähige Sonnenintegration mit `sun.sun`
- mindestens eine Cover-Entität
- optional Raumtemperatur, Außentemperatur, Lux, Fensterkontakte, Safety-Sensoren und Automatiksperren

## Sun Presence

Voreinstellungen:

| Profil | ON ab | OFF unter | ON-Verzögerung | OFF-Verzögerung |
|---|---:|---:|---:|---:|
| Weniger empfindlich | 35.000 lx | 18.000 lx | 6 min | 20 min |
| Ausgewogen | 18.000 lx | 9.000 lx | 3 min | 12 min |
| Empfindlich | 8.000 lx | 4.000 lx | 2 min | 8 min |

**Empfindlicher bedeutet einen niedrigeren Schwellwert.**

Beispiel mit dem realen Home-Assistant-Zustand `26398.72 lx`:

- Profil **Ausgewogen**
- Wert liegt über 18.000 lx
- Sun Presence startet die ON-Verzögerung
- nach drei durchgehend hellen Minuten wird der sektorspezifische Binary Sensor ON

Sun Presence und Sektorgeometrie sind getrennt:

- Sun Presence kann ON sein, weil es hell ist.
- Der Sektor kann trotzdem außerhalb liegen, wenn der Sonnenazimut den konfigurierten Bereich verlassen hat.
- Beispiel: Süd 120°–240°, Sonne 244° → Sun Presence kann ON sein, Beschattung dieses Sektors bleibt aber inaktiv.

## Manuelle Bedienung

### Lokaler Override pro Cover

Eine unerwartete Coverbewegung über Home Assistant, KNX, einen Taster oder eine andere Automation bewirkt:

1. nur dieses Cover wird bis zum nächsten Sonnenaufgang plus Offset pausiert;
2. die konfigurierte Automatiksperre wird eingeschaltet;
3. Smart Shading sendet keine Gegenfahrt;
4. die Card zeigt am Cover **Pausiert**;
5. am Ende wird die Automatiksperre ausgeschaltet und der Raum sofort neu ausgewertet.

Wird die Automatiksperre vorher manuell ausgeschaltet, endet die lokale Pause sofort.

### Raum-Pause

Der Pause-Button pausiert die gesamte normale Raumautomatik nach der im Wizard gewählten Regel. Die Pause besitzt einen eigenen Ablauf-Timer und endet nicht erst bei der nächsten 20-Minuten-Prüfung.

### Manueller Master-Override

Der Hand-Button schaltet den manuellen Master:

```text
EIN  = normale Raumautomatik dauerhaft deaktiviert
AUS  = Automation wieder freigegeben und sofort neu ausgewertet
```

Es gibt keinen automatischen Reset. Safety bleibt höher priorisiert.

## Auswertungsstrategie

Standardintervall:

```text
20 Minuten
```

Normale Änderungen von Temperatur, Sonnenstand und Lux lösen keine vollständige Raumneuberechnung bei jedem Messwert aus. Lux aktualisiert nur die Sun-Presence-Hysterese und deren Timer.

Sofort neu ausgewertet wird unter anderem bei:

- Safety-Änderungen
- Fensterkontakt-Änderungen
- Freigabe einer Automatiksperre
- Ende einer lokalen Cover-Pause
- Ende einer Raum-Pause
- Ausschalten des Master-Overrides
- manueller Coverbewegung während aktiver Safety
- manueller Betätigung von „Jetzt auswerten“

## Cover-Semantik

Smart Shading verwendet für die Behanghöhe die Home-Assistant-Semantik und
für Lamellen standardmäßig die KNX-Semantik:

```text
Position 0 %   = geschlossen
Position 100 % = offen
Tilt 0 %       = Lamellen vollständig geöffnet, Lichtdurchlass
Tilt 100 %     = Lamellen vollständig geschlossen, Sonnenblockierung
```

### Außenjalousie mit Lamellen

```text
Open  → Position 100 %, Tilt 0 %
Solar → Position 0 %, Tilt adaptiv zur Sonnenhöhe
Heat  → Position 0 %, Tilt 100 %
Safety → Position 100 %, Tilt 0 %
```

Keine 50-%-Zwischenstufe.

## Card-Bedienung

Footer:

- **Pause/Play:** Raum pausieren oder fortsetzen
- **Pfeilkreis:** sofort neu auswerten
- **Hand:** manuellen Master umschalten
- **Regler:** Advanced View öffnen

Interaktionen:

- Sonnenbalken → `sun.sun`
- Sektorkürzel wie `S` oder `E` → Sun-Presence-Sensor dieses Sektors
- Fensterkürzel → zugehöriger Fensterkontakt
- Coverzeile → Cover-More-Info

Die Card definiert eigene Grid-Regeln für die Sections View und begrenzt alle `ha-icon`-Größen zusätzlich über `--mdc-icon-size`.

## Diagnose

Offizieller Home-Assistant-Download:

```text
Einstellungen → Geräte & Dienste → Smart Shading → ⋮ → Diagnosen herunterladen
```

Enthalten sind unter anderem:

- effektive Konfiguration
- echte Eingangszustände und Einheiten
- Lux-Rohwert und geparster Wert
- effektive Sun-Presence-Grenzen
- lokale Cover-Pausen
- Raum-/Sektorstatus
- Sollwerte und Unterdrückungsgründe
- bis zu 500 Diagnoseereignisse

Zusätzlich erzeugt der Export-Button eine JSON-Datei unter:

```text
/config/www/smart_shading_logs/
```

## Updates

Die Dashboard-Ressource wird einmalig als JavaScript-Modul registriert:

```text
/smart_shading/shading.js
```

Diese URL bleibt bei allen zukünftigen Versionen gleich. Beim nächsten Upgrade:

1. Smart Shading über HACS aktualisieren oder den Integrationsordner ersetzen.
2. Home Assistant vollständig neu starten.
3. Browser beziehungsweise Companion App neu laden, falls noch die alte Card im Speicher liegt.

Die Resource muss nicht mehr pro Version angepasst werden. Keine Versionsnummer und keinen `?v=...`-Parameter ergänzen.

Bestehende Installationen mit `/smart_shading/smart-shading-card.js?v=...` funktionieren über einen Kompatibilitäts-Loader weiter. Empfohlen wird, die Resource einmal auf `/smart_shading/shading.js` umzustellen.

## Versions- und Änderungsverwaltung

- `custom_components/smart_shading/manifest.json` ist die einzige technische Versionsquelle.
- Noch nicht veröffentlichte Änderungen stehen unter `CHANGELOG.md → Unreleased`.
- Jede Änderung an Logik, Card, Advanced Mode oder Release-Verhalten muss im Changelog dokumentiert werden.
- Die Pull-Request-Vorlage fragt Dokumentation, Tests und Migrationsauswirkungen verpflichtend ab.
- CI verhindert Produktionsänderungen ohne Changelog-Anpassung.
- Ein Release-Tag muss exakt zur Version im Manifest passen.
- Ein gültiger Tag erzeugt nach erfolgreichen Tests automatisch das Installations-ZIP und den GitHub Release.

## Beta- und Stable-Kanal

- **Beta** wird ausschließlich aus `develop` veröffentlicht und verwendet Versionen wie `4.6.0-beta.2`.
- **Stable** wird ausschließlich aus `main` veröffentlicht und verwendet Versionen wie `4.6.0` beziehungsweise später `1.0.0`.
- Beta-Releases werden auf GitHub als Prerelease markiert; Stable-Releases werden als aktuelles Release markiert.
- HACS bietet keinen unversionierten Entwicklungsbranch an. Installiert werden ausschließlich veröffentlichte Versionen.

Release vorbereiten:

1. Änderungen aus `Unreleased` in einen Abschnitt `## <Version>` verschieben.
2. Dieselbe Version in `custom_components/smart_shading/manifest.json` eintragen.
3. Änderungen nach `develop` für Beta oder nach `main` für Stable mergen.
4. Unter **GitHub → Actions → Release → Run workflow** den richtigen Branch und Kanal auswählen.
5. Die Manifest-Version ohne führendes `v` zur Bestätigung eingeben.

Der Workflow validiert Branch, Versionsformat, Changelog, Paket, Python, Frontend und bereits vorhandene Tags. Erst danach werden Tag, GitHub Release und Installations-ZIP erstellt.

Für HACS wird das Repository einmalig als benutzerdefiniertes Repository vom Typ **Integration** hinzugefügt. Das Repository darf nicht wirklich privat geschaltet werden: HACS kann private GitHub-Repositories nicht herunterladen. „Privater Beta-Test“ bedeutet, dass das öffentliche Repository nicht im offiziellen HACS-Katalog gelistet ist und nur auf dem eigenen Testsystem als Custom Repository verwendet wird.

GitHub kann nicht selbst erkennen, welche fachliche Bedeutung eine Codeänderung besitzt. Die Repository-Regeln sorgen deshalb dafür, dass die Beschreibung im selben Pull Request bewusst mitgeändert und durch CI kontrolliert wird.
