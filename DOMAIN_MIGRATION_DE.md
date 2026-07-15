# Domainwechsel auf `smart_shading`

Ab Version 4.4 verwendet die Integration dauerhaft die Home-Assistant-Domain und den Ordner:

```text
/config/custom_components/smart_shading
```

Die frühere Beta-Domain `smart_shading_v3` ist eine andere Home-Assistant-Integration. Domains können nicht umbenannt werden. Deshalb:

1. Alten Smart-Shading-Beta-Eintrag in **Einstellungen → Geräte & Dienste** entfernen.
2. Alte Dashboard-Ressource entfernen.
3. Alten Ordner `/config/custom_components/smart_shading_v3` sichern oder löschen.
4. V4.4 nach `/config/custom_components/smart_shading` installieren.
5. Home Assistant vollständig neu starten.
6. **Smart Shading** neu hinzufügen und Räume neu konfigurieren.
7. Neue Ressource registrieren: `/smart_shading/smart-shading-card.js?v=4.6.0-beta.1`.

Direktes Bearbeiten von `.storage/core.config_entries` wird nicht empfohlen.
