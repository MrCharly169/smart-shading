# Kernreview und Regressionsmatrix – Smart Shading 4.6

| Bereich | Abgedeckter Fehlerfall |
|---|---|
| Zahlenlesen | `26398.72`, lokalisierte Trennzeichen, unavailable, keine stille Null |
| Sun Presence | Medium ON nach 3 min, Presets maßgeblich, Custom separat |
| Sektoren | Sun Presence ON kann bei Azimut außerhalb trotzdem keine Fahrt auslösen |
| Coverfeedback | eigener Befehl, Bewegung zum Ziel, Bewegung weg vom Ziel, veralteter Befehl |
| Startzustand | `None/unavailable → open` erzeugt keine Pause |
| Lokale Pause | externe Fahrt setzt Pause und Lock; nur betroffenes Cover |
| Lock | externe ON/OFF-Änderung, internes Feedback, sofortiges Benutzer-Unlock |
| Pauseablauf | exakter Timer, Lock OFF, genau eine Neuauswertung |
| Raum-Pause | exakter Timer unabhängig vom 20-Minuten-Intervall |
| Master | EIN ohne Gegenfahrt; AUS mit sofortiger Auswertung |
| Safety | übersteuert Pause/Lock und korrigiert manuelle Bewegung sofort |
| Fenster | Closing-Block und sofortige Neuauswertung bei Zustandsänderung |
| Trigger | normale Sensorupdates gebündelt, kritische Events sofort |
| Statistik | Routine-Cooldowns nicht als Blockierung; Legacy-Zähler zurückgesetzt |
| Card | lokale Pause, Master, Sun-Link, Icongrößen, Modal, Sections-Grid |
| Diagnose | Eingangszustände, effektive Einstellungen, Pausen, 500 Ereignisse |
