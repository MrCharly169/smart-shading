# Installations- und Pilotcheckliste – Smart Shading 4.6.0-beta.1

## Installation

- [ ] Sicherung des alten Ordners erstellt
- [ ] `/config/custom_components/smart_shading/manifest.json` vorhanden
- [ ] Version `4.6.0-beta.1` geprüft
- [ ] Home Assistant vollständig neu gestartet
- [ ] Ressource `/smart_shading/smart-shading-card.js?v=4.6.0-beta.1` registriert
- [ ] Browser hart neu geladen

## Sun Presence

- [ ] Lux-Entität zeigt einen numerischen Rohzustand
- [ ] Sun-Presence-Attribute zeigen denselben geparsten Wert
- [ ] Profil „Ausgewogen“ zeigt ON 18.000 / OFF 9.000 lx
- [ ] Bei über 18.000 lx erscheint zunächst Pending ON
- [ ] nach drei Minuten wird Sun Presence ON
- [ ] Sektorgeometrie separat geprüft

## Manual Override

- [ ] Cover über HA manuell bewegen
- [ ] nur dieses Cover zeigt „Pausiert“
- [ ] konfigurierte Automatiksperre wird ON
- [ ] keine unmittelbare Gegenfahrt
- [ ] Automatiksperre OFF beendet Pause sofort
- [ ] lokaler Pauseablauf schaltet Sperre OFF
- [ ] Master-Hand EIN deaktiviert den Raum dauerhaft
- [ ] Master-Hand AUS evaluiert sofort neu

## Safety und Fenster

- [ ] geöffnetes/unsicheres Fenster blockiert die konfigurierte Fahrtrichtung
- [ ] sichere Fensterfreigabe löst sofortige Neuauswertung aus
- [ ] Safety fährt trotz lokaler Pause oder Master in die sichere Position

## Card

- [ ] keine rohen Entity-IDs sichtbar
- [ ] Sektorkürzel öffnet den Sun-Presence-Sensor
- [ ] Sonnenbalken öffnet `sun.sun`
- [ ] Icons passen vollständig in Chips und Buttons
- [ ] Advanced View bleibt bei Statusupdates geöffnet
- [ ] Animationen bei aktiver Sonne, Heat/Safety/Master sichtbar

## Diagnose

- [ ] offizielles HA-Diagnosepaket heruntergeladen
- [ ] Eingangszustände, Lux, Einheiten und effektive Grenzwerte enthalten
- [ ] keine wiederholte Eventflut identischer Einträge
