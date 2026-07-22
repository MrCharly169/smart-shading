# Review-Protokoll: Einrichtungsassistent

Dieses Dokument hält die gemeinsam abgenommenen Entscheidungen für den endgültigen Einrichtungsassistenten fest. Offene Punkte sind ausdrücklich als solche markiert.

## Review 1 – Auswahl Easy oder Advanced

Status: abgenommen

- Aufbau und Felder der ersten Seite bleiben bestehen.
- Der Einführungstext erklärt kurz Zweck und Philosophie von Smart Shading.
- Jede Fassade wird separat ausgewertet; nur zugeordnete Behänge werden gesteuert.
- Manuelle Bedienung bleibt möglich; konfigurierte Sicherheitsbedingungen haben Vorrang.
- Easy und Advanced verwenden dieselbe Automation. Advanced stellt zusätzliche Konfigurationsmöglichkeiten bereit.
- Unklare Funktionsnamen werden nicht ohne Erklärung aufgelistet.

## Review 2 – Ersten Raum einrichten

Status: abgenommen mit den folgenden Änderungen

### Behangtyp

Verbindliche Entscheidung:

- Der gewählte Behangtyp erzeugt ein technisches Profil für die zugeordneten Behänge. Behänge mit unterschiedlichen physischen Typen gehören in getrennte Behanggruppen.
- Dieses Profil steuert den gesamten weiteren Assistenten, die Runtime-Logik, die Darstellung und verfügbaren Funktionen der Card sowie alle Standardwerte.
- Alle späteren Optionen, Validierungen und Fahrziele müssen zum gewählten physischen Behangtyp passen.
- Nicht unterstützte Einstellungen dürfen nicht angezeigt werden. Beispiele: keine Lamellenwerte für Vorhänge, Screens oder Rollläden; keine Prozent-Zielwerte für reine Open/Close-Covers.
- Easy und Advanced müssen dieselbe Typdefinition verwenden.
- Ein Typwechsel muss die Oberfläche und die gespeicherten Standardwerte konsistent aktualisieren.
- Jeder unterstützte Behangtyp wird noch einzeln fachlich geprüft. Dabei werden Bauart, Home-Assistant-Semantik, Neutralstellung, Sonnen-, Hitze-, Nacht- und Safety-Ziel, Lamellenfähigkeit, relevante Einzeloptionen und Card-Darstellung festgelegt.
- Insbesondere der Begriff „Markise“ darf nicht pauschal behandelt werden; Bauart und sichere Fahrtrichtung müssen eindeutig definiert sein.

Technischer Befund:

- Die Runtime besitzt bereits unterschiedliche Profile und Standardwerte je Behangtyp.
- Teile des Options-Assistenten filtern Felder bereits nach Typ.
- Die Anpassung ist noch nicht durchgängig aus einer gemeinsamen Capability-Matrix abgeleitet; ein Typwechsel innerhalb eines bereits dargestellten Formulars aktualisiert die sichtbaren Felder nicht sofort.

### Außentemperatur-Freigabe

Technischer Befund:

- `Minimum outdoor temperature` wird nur ausgewertet, wenn `Use outdoor temperature gate` aktiviert ist.
- Unterhalb des Grenzwerts wird normale Easy-Beschattung verhindert.
- Als Quelle gilt zuerst der ausgewählte Außentemperatursensor, danach die Temperatur der Haus-Wetterentität.
- Fehlt vorübergehend ein gültiger Temperaturwert, bleibt die Beschattung freigegeben.

UX-Problem:

- Schalter, Quelle und Grenzwert werden gleichzeitig angezeigt, obwohl Quelle und Grenzwert bei ausgeschaltetem Schalter wirkungslos sind.

Verbindliche Entscheidung:

- Der zusätzliche Schalter `Use outdoor temperature gate` entfällt vollständig.
- Wird kein Außentemperatursensor gewählt, spielt die Außentemperatur für die Beschattung keine Rolle.
- Wird ein Außentemperatursensor gewählt, ist die Temperaturbedingung automatisch aktiv: Normale Beschattung wird erst ab der konfigurierten Mindesttemperatur freigegeben.
- Für diese Bedingung wird ausschließlich der ausdrücklich gewählte Außentemperatursensor verwendet; eine Wetterentität aktiviert sie nicht automatisch.
- Der Mindestwert wird nur abgefragt beziehungsweise angezeigt, wenn ein Außentemperatursensor gewählt wurde.

### Lux und externe Sonnenbestätigung

Technischer Befund:

- Der derzeit getestete Beta-Assistent zeigt beide Eingaben gleichzeitig, lehnt eine gleichzeitige Auswahl aber erst beim Absenden ab.
- Bei alten Konfigurationen mit beiden Quellen hat die externe Ein/Aus-Bestätigung Vorrang. Ist sie nicht verfügbar, folgt Lux; danach bleibt die Sonnengeometrie als Rückfall erhalten.

Verbindliche Entscheidung:

- Pro Sektor wird in einem Dropdown genau eine Sonnenbestätigung gewählt: keine zusätzliche Bestätigung (nur Sonnengeometrie), lokaler Lux-Sensor oder externe Ein/Aus-Bestätigung.
- Der lokale Lux-Sensor wird als empfohlene und präzisere Variante erklärt.
- Die externe Ein/Aus-Bestätigung bleibt als optionale Alternative für bereits vorhandene Sonnenlogik verfügbar.
- Danach zeigt der Assistent ausschließlich die Einstellungen der ausgewählten Quelle.

## Review 3 – Easy: Room and sensors

Status: abgenommen mit reduzierten Feldern

Technischer Befund:

- Die getestete Beta-Seite verwendet ein gemeinsames Basisformular und zeigt dadurch `Indoor temperature` sowie Wind-, Frost-, Regen- und andere Safety-Sensoren auch im Easy Mode an.
- Die Easy-Runtime verwendet keine Raumtemperaturstufen und der Easy-Assistent bietet keine Safety-Konfiguration an. Die sichtbaren Felder versprechen daher Funktionen, die nicht zum gewählten Setup gehören.
- Der aktuelle `develop`-Stand filtert Raumtemperatur und Safety bereits aus dieser Easy-Seite; der noch vorhandene Temperature-Gate-Schalter muss entsprechend Review 2 ebenfalls entfernt werden.

Verbindliche Entscheidung für Easy:

- Angezeigt werden der Raumname und optional ein Außentemperatursensor.
- Wird ein Außentemperatursensor gewählt, wird zusätzlich die Mindesttemperatur für normale Beschattung konfiguriert.
- Ohne Außentemperatursensor wird kein Mindestwert angezeigt und keine Temperaturbedingung ausgewertet.
- `Indoor temperature` wird nicht angezeigt.
- Wind-, Frost-, Regen- und andere Safety-Sensoren werden nicht angezeigt.
- Weitere Advanced-spezifische Sensorbezeichnungen oder Optionen werden auf dieser Seite ebenfalls nicht angezeigt.

## Review 4 – Easy: Sonnensektor hinzufügen / direkte Sonne erkennen

Status: abgenommen mit vereinfachter Sonnenquellen-Auswahl

Technischer Befund:

- Die getestete Beta zeigt einen Lux-Sensor, die Lux-Empfindlichkeit und `sun_presence_entity` gleichzeitig an.
- `sun_presence_entity` besitzt auf dieser Options-Seite keine korrekt aufgelöste Übersetzung und erscheint deshalb als technischer Schlüssel.
- Obwohl Lux und externe Bestätigung gleichzeitig sichtbar sind, lehnt der Assistent die gemeinsame Auswahl erst beim Absenden ab.
- Ein bestehender benutzerdefinierter Lux-Preset kann dazu führen, dass `Custom` auch im Easy Mode weiterhin angeboten wird.

Verbindliche Entscheidung für Easy:

- Benutzerdefinierte Fassadengeometrie und benutzerdefinierte Lux-Grenzen sind ausschließlich im Advanced Mode verfügbar.
- Bei der Lux-Empfindlichkeit werden im Easy Mode nur die vordefinierten Profile angeboten; `Custom` entfällt vollständig.
- Vor den Sensorfeldern steht ein Dropdown zur Wahl genau einer Sonnenbestätigung:
  - `Lokaler Lux-Sensor (empfohlen)`
  - `Externer Ein/Aus-Sonnensensor`
  - `Keine zusätzliche Bestätigung – nur Sonnenstand verwenden`
- Beim lokalen Lux-Sensor werden anschließend der Lux-Sensor und eines der vordefinierten Empfindlichkeitsprofile abgefragt. Smart Shading erzeugt daraus seinen eigenen sektorbezogenen Sun-Presence-Sensor mit Hysterese und Verzögerungen.
- Bei der externen Bestätigung wird ausschließlich eine vorhandene Binary-, Input-Boolean- oder Switch-Entität abgefragt. `on` bedeutet direkte Sonne. Lux-Preset und Lux-Grenzen werden nicht angezeigt.
- Bei reiner Sonnengeometrie werden keine Sensor- oder Empfindlichkeitsfelder angezeigt.
- Der lokale Lux-Sensor wird empfohlen, weil Smart Shading dessen Grenzwerte, Hysterese, Verzögerungen, Status und Diagnose selbst konsistent verwalten kann.
- Der technische Schlüssel `sun_presence_entity` darf nirgends im Kundenassistenten sichtbar sein.
