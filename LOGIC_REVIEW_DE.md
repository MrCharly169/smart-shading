# Logikprüfung – Smart Shading 4.6.0-beta.1

## Prioritäten

```text
Safety > Manual Master > Heat > Raum-Pause > lokale Cover-Pause/Lock > Zeitplan > Solar/Comfort > Open
```

Safety darf normale Sperren und Pausen übersteuern.

## Auswertung

- Startup: einmalige Vollauswertung
- regulär: alle 20 Minuten
- Lux: nur Sun-Presence-Hysterese und exakter Delay-Timer
- sofort: Safety/Fenster, Lock-Freigabe, Pauseablauf, Master-Freigabe, manuelle Safety-Gegenfahrt

## Fremd- versus Eigenbedienung

Eigenes Feedback benötigt:

- einen frischen Smart-Shading-Befehl
- Bewegung in Richtung des gespeicherten Ziels oder Ziel erreicht
- Positions-/Tiltänderung außerhalb bloßen Messrauschens

Bewegung ohne frischen Befehl oder weg vom Ziel gilt als extern. Initiale Verfügbarkeit ohne echte Bewegung gilt nicht als extern.

## Sun Presence

Sun Presence bewertet ausschließlich Lux mit Hysterese und Verzögerung. Die effektive Beschattung verlangt zusätzlich:

- Sonne über Horizont
- Azimut im Sektor
- Mindestsonnenhöhe
- Zeitplan
- Temperatur-/Weather-Bedingungen
- keine höher priorisierte Sperre

## Außenjalousien

- normale Sonnenbeschattung: 0 % Position, Tilt adaptiv
- Heat: 0 % Position, Tilt 0 %
- Open/Safety: 100 % Position, Tilt 100 %

## Persistenz

Persistiert werden:

- Raum-Pause und Masterzustand
- Heat-/Shading-Hysterese
- Sun Presence und Pending-Timer
- lokale Cover-Pausen
- Benutzer-Overrides

Ablauftimer werden nach Reload neu geplant.
