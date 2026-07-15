# Smart Shading 4.6.0-beta.1

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
/smart_shading/smart-shading-card.js?v=4.6.0-beta.1
```

Card:

```yaml
type: custom:smart-shading-card
entity: sensor.DEIN_RAUMSTATUS
advanced_mode: true
```

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

Smart Shading verwendet die Home-Assistant-Semantik:

```text
Position 0 %   = geschlossen
Position 100 % = offen
Tilt 0 %       = Lamellen geschlossen
Tilt 100 %     = Lamellen geöffnet
```

### Außenjalousie mit Lamellen

```text
Open  → Position 100 %, Tilt 100 %
Solar → Position 0 %, Tilt adaptiv zur Sonnenhöhe
Heat  → Position 0 %, Tilt 0 %
Safety → Position 100 %, Tilt 100 %
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

## Update von 4.5

1. Ordner sichern:

```bash
cd /config/custom_components
mv smart_shading smart_shading_backup_4.5
```

2. Drop-in-ZIP nach `/config` kopieren und entpacken:

```bash
cd /config
unzip -q smart_shading_v4_4.6.0-beta.1_dropin.zip -d /config
```

3. Version prüfen:

```bash
grep '"version"' /config/custom_components/smart_shading/manifest.json
```

4. Home Assistant vollständig neu starten.

5. Ressource aktualisieren:

```text
/smart_shading/smart-shading-card.js?v=4.6.0-beta.1
```

6. Browser mit `Strg + F5` neu laden.

Der bestehende `smart_shading`-Config-Entry bleibt erhalten.
