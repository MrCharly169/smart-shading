const htmlEscape = (value) => String(value ?? "").replace(/[&<>'"]/g, (char) => ({
  "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;",
}[char]));
const asArray = (value) => Array.isArray(value) ? value : [];
const asRecord = (value) => value && typeof value === "object" && !Array.isArray(value) ? value : {};
const asNumber = (value, fallback = null) => {
  if (value === null || value === undefined || value === "") return fallback;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
};
const clamp = (value, min, max) => Math.min(Math.max(value, min), max);
const localDateKey = (value = new Date()) => {
  const date = value instanceof Date ? value : new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  return [date.getFullYear(), String(date.getMonth() + 1).padStart(2, "0"), String(date.getDate()).padStart(2, "0")].join("-");
};
const isRawEntityId = (value) => /^(?:cover|switch|binary_sensor|sensor|number|select|button)\.[a-z0-9_]+$/i.test(String(value || "").trim());
const iconBox = (icon, className = "") => `<span class="icon-box ${htmlEscape(className)}" aria-hidden="true"><ha-icon icon="${htmlEscape(icon)}"></ha-icon></span>`;
const profileSupportsTilt = (profile) => ["venetian", "vertical_blind"].includes(String(profile || ""));
const visibleStateAttributes = (state) => {
  const attrs = asRecord(state?.attributes);
  return {
    state: state?.state ?? null,
    friendly_name: attrs.friendly_name ?? null,
    device_class: attrs.device_class ?? null,
    unit_of_measurement: attrs.unit_of_measurement ?? null,
    current_position: attrs.current_position ?? null,
    current_tilt_position: attrs.current_tilt_position ?? null,
    azimuth: attrs.azimuth ?? null,
    elevation: attrs.elevation ?? null,
    smart_shading_control_key: attrs.smart_shading_control_key ?? null,
  };
};
const cardRoomAttributes = (attrs) => ({
  name: attrs.name,
  reason: attrs.reason,
  active_sectors: attrs.active_sectors,
  targets: attrs.targets,
  sector_statuses: attrs.sector_statuses,
  cover_pauses: attrs.cover_pauses,
  manual_master_active: attrs.manual_master_active,
  pause_mode: attrs.pause_mode,
  pause_until: attrs.pause_until,
  night_enabled: attrs.night_enabled,
  night_active: attrs.night_active,
  night_source: attrs.night_source,
  night_entity: attrs.night_entity,
  schedule_active: attrs.schedule_active,
  temperature_settings: attrs.temperature_settings,
  easy_confirmation_state: attrs.easy_confirmation_state,
  easy_source_summary: attrs.easy_source_summary,
  outdoor_temperature_condition: attrs.outdoor_temperature_condition,
  configuration: attrs.configuration,
  sun_entity: attrs.sun_entity,
  smart_shading_layout: attrs.smart_shading_layout,
});
const eventElement = (event, selector) => {
  const pathMatch = event?.composedPath?.().find?.(
    (candidate) => candidate?.matches?.(selector),
  );
  return pathMatch || event?.target?.closest?.(selector) || null;
};
const sameDomKind = (current, next) => current?.nodeType === next?.nodeType
  && (current?.nodeType !== 1 || current.localName === next.localName);
const domNodeKey = (node) => {
  if (node?.nodeType !== 1) return "";
  if (node.id) return `id:${node.id}`;
  const keyAttributes = [
    "data-close", "data-press", "data-tool-press", "data-collapse-toggle",
    "data-more", "data-night-source", "data-preview-day", "data-preview-date",
    "data-advanced", "data-easy-layout", "data-advanced-layout", "data-card-mode",
  ];
  for (const name of keyAttributes) {
    if (node.hasAttribute?.(name)) return `${name}:${node.getAttribute(name) || ""}`;
  }
  return "";
};
const syncDomAttributes = (current, next) => {
  const desired = new Map(Array.from(next.attributes || []).map((attribute) => [attribute.name, attribute.value]));
  for (const attribute of Array.from(current.attributes || [])) {
    if (!desired.has(attribute.name)) current.removeAttribute(attribute.name);
  }
  for (const [name, value] of desired) {
    if (current.getAttribute(name) !== value) current.setAttribute(name, value);
  }
};
const reconcileDomNode = (current, next) => {
  if (!sameDomKind(current, next)) {
    current.replaceWith(next.cloneNode(true));
    return;
  }
  if (current.nodeType === 3 || current.nodeType === 8) {
    if (current.nodeValue !== next.nodeValue) current.nodeValue = next.nodeValue;
    return;
  }
  syncDomAttributes(current, next);
  reconcileDomChildren(current, next);
};
const reconcileDomChildren = (currentParent, nextParent) => {
  const desired = Array.from(nextParent.childNodes || []);
  for (let index = 0; index < desired.length; index += 1) {
    const next = desired[index];
    let current = currentParent.childNodes?.[index];
    const nextKey = domNodeKey(next);
    if (current && nextKey && domNodeKey(current) !== nextKey) {
      const match = Array.from(currentParent.childNodes || [])
        .slice(index + 1)
        .find((candidate) => domNodeKey(candidate) === nextKey);
      if (match) {
        currentParent.insertBefore(match, current);
        current = match;
      }
    }
    if (!current) {
      currentParent.appendChild(next.cloneNode(true));
      continue;
    }
    reconcileDomNode(current, next);
  }
  while (Number(currentParent.childNodes?.length || 0) > desired.length) {
    currentParent.lastChild?.remove?.();
  }
};
const updateStableMarkup = (root, markup) => {
  if (!root) return false;
  const template = globalThis.document?.createElement?.("template");
  if (!template?.content) {
    if (root.innerHTML === markup) return false;
    root.innerHTML = markup;
    return true;
  }
  template.innerHTML = markup;
  reconcileDomChildren(root, template.content);
  return true;
};
const humanizeToken = (value, fallback = "–") => {
  const token = String(value ?? "").trim();
  if (!token) return fallback;
  return token
    .replace(/[_-]+/g, " ")
    .replace(/\s+/g, " ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
};
// ``DecisionResult.as_dict`` contains a nested ``trace`` while the room
// sensor stores a live ``DecisionTrace`` directly.  Live Issue-79 payloads
// additionally wrap it as ``{decision: result}`` or, for simulations, as
// ``{results: [{result}]}``.  Accept every persisted shape so an in-flight
// integration update never turns an explanation into a blank card.
const tracePayload = (value) => {
  const record = asRecord(value);
  const results = asArray(record.results);
  const latest = asRecord(results[results.length - 1]);
  const candidates = [
    record,
    asRecord(record.decision),
    asRecord(record.result),
    asRecord(record.decision_result),
    latest,
    asRecord(latest.decision),
    asRecord(latest.result),
  ];
  for (const candidate of candidates) {
    const nested = asRecord(candidate.trace);
    if (Object.keys(nested).length) return nested;
    if (candidate.winner || candidate.entries || candidate.command_result) return candidate;
  }
  return {};
};
// A simulation normally contains one result per sector/layer pair.  Do not
// flatten this to the last result: different layers can legitimately choose
// different winners and targets in the same virtual evaluation.  Keep the
// legacy single-result shape as a fallback for already persisted beta data.
const simulationResultPayloads = (value) => {
  const record = asRecord(value);
  const rows = asArray(record.results);
  if (rows.length) {
    return rows.map((raw) => {
      const scope = asRecord(raw);
      const result = asRecord(scope.result);
      const trace = tracePayload(result);
      return {
        scope,
        result,
        trace: Object.keys(trace).length ? trace : tracePayload(scope),
      };
    });
  }
  const trace = tracePayload(record);
  return Object.keys(trace).length ? [{ scope: record, result: asRecord(record.result), trace }] : [];
};
const targetTracePayloads = (value) => asArray(asRecord(value).target_decisions)
  .map((scope) => ({ scope: asRecord(scope), trace: tracePayload(scope) }))
  .filter(({ trace }) => Object.keys(trace).length);
const protectedZonePayloads = (value) => [
  ...asArray(tracePayload(value).protected_zones),
  ...targetTracePayloads(value).flatMap(({ scope, trace }) => [
    ...asArray(trace.protected_zones)
      .map((zone) => ({ ...asRecord(zone), layer_name: scope.layer_name || scope.layer_id || "" })),
    ...asArray(scope.covers).flatMap((rawCover) => {
      const cover = asRecord(rawCover);
      return asArray(tracePayload(cover.command).protected_zones).map((zone) => ({
        ...asRecord(zone),
        layer_name: scope.layer_name || scope.layer_id || "",
        cover_entity: cover.entity_id || cover.cover_id || "",
      }));
    }),
  ]),
];
const protectedZoneCalculationPayloads = (attrs) => asArray(asRecord(attrs).targets)
  .flatMap((rawTarget) => {
    const target = asRecord(rawTarget);
    return asArray(target.protected_zone_calculations).map((rawZone) => ({
      ...asRecord(rawZone),
      cover_name: target.name || target.entity_id || "",
      cover_entity: target.entity_id || "",
      layer_name: target.layer || target.layer_id || "",
      ordinary_target: target.ordinary_target || null,
      final_target: target.final_target || {
        position: target.position,
        tilt: target.tilt,
      },
      decision_mode: target.decision_mode || target.mode || "",
      applied: asArray(target.protected_zone_applied_ids).includes(asRecord(rawZone).zone_id),
    }));
  });
const previewPayload = (value) => {
  const record = asRecord(value);
  const nested = asRecord(record.preview);
  return Object.keys(nested).length ? nested : record;
};
const profileIcon = (profile, closed = false) => ({
  venetian: closed ? "mdi:blinds-horizontal-closed" : "mdi:blinds-horizontal",
  roller_shutter: closed ? "mdi:window-shutter" : "mdi:window-shutter-open",
  exterior_screen: "mdi:roller-shade",
  curtain: closed ? "mdi:curtains-closed" : "mdi:curtains",
  vertical_blind: "mdi:blinds-vertical",
  awning: "mdi:storefront-outline",
  binary_cover: closed ? "mdi:blinds" : "mdi:blinds-open",
})[String(profile || "")] || (closed ? "mdi:blinds" : "mdi:blinds-open");

function cleanDisplayName(value, fallback) {
  let name = String(value || "").trim();
  if (!name || isRawEntityId(name)) return fallback;
  // Older beta versions sometimes stored a long technical identifier in brackets.
  const bracket = name.match(/\s*\(([^()]*)\)\s*$/);
  if (bracket) {
    const technical = bracket[1];
    const separators = (technical.match(/[-_]/g) || []).length;
    if (isRawEntityId(technical) || separators >= 2) name = name.slice(0, bracket.index).trim();
  }
  return name || fallback;
}

function localizedReason(value, language, fallback = "") {
  const text = String(value || "").trim();
  if (!text) return fallback;
  const de = String(language || "en").toLowerCase().startsWith("de");
  if (!de) return text;
  const translations = {
    "Not evaluated": "Noch nicht ausgewertet",
    "Evaluation started": "Auswertung gestartet",
    "Manual master override active": "Manuelle Sperre ist aktiv",
    "Manual Override is active": "Manuelle Sperre ist aktiv",
    "Room automation disabled": "Raumautomatik ist deaktiviert",
    "Automatic shading is paused": "Automatische Beschattung ist pausiert",
    "Automatic shading is paused; heat protection is not active": "Automatische Beschattung ist pausiert; Heat Protection ist nicht aktiv",
    "Reset by user": "Vom Benutzer zurückgesetzt",
    "Evening release held for imminent Night Mode": "Abendfreigabe wartet auf die bevorstehende Nachtfunktion",
    "Heat protection released for evening": "Heat Protection für den Abend aufgehoben",
    "Heat threshold / hysteresis active": "Heat-Schwelle oder Hysterese ist aktiv",
    "Normal adaptive solar shading": "Normale adaptive Beschattung",
    "Solar heat reduction": "Solare Wärmereduktion",
    "Glare / comfort protection": "Blend- oder Komfortschutz",
    "Sun outside this sector": "Sonne außerhalb dieses Sektors",
    "Sun below horizon": "Sonne unter dem Horizont",
    "Sun detected in sector": "Sonne im Sektor erkannt",
    "Sector disabled": "Sektor deaktiviert",
    "Morning transition holds Night target while shading conditions settle": "Morgenübergang hält die Nachtposition, bis die Beschattungsbedingungen geklärt sind",
    "Morning transition window ended; cover opened": "Morgenübergang beendet; Behang geöffnet",
    "No sectors configured": "Keine Sektoren eingerichtet",
    "This setup does not use an activity schedule": "Für diese Einrichtung wird kein Zeitplan verwendet",
    "Night function is not configured for this setup": "Für diese Einrichtung ist keine Nachtfunktion konfiguriert",
    "Sun position is unavailable; cover positions held": "Sonnenposition nicht verfügbar; Behangpositionen werden gehalten",
    "Sun is active in a configured facade sector": "Sonne ist in einem konfigurierten Fassadensektor aktiv",
    "Outdoor temperature condition blocks shading": "Die Außentemperaturbedingung blockiert die Beschattung",
    "Optional sun confirmation blocks shading": "Die optionale Sonnenbestätigung blockiert die Beschattung",
    "Sun is outside all configured facade sectors": "Sonne ist außerhalb aller konfigurierten Fassadensektoren",
    "Month outside shading season": "Monat außerhalb der Beschattungssaison",
    "Weekday outside shading schedule": "Wochentag außerhalb des Beschattungszeitplans",
    "Inside fixed shading time": "Innerhalb der festen Beschattungszeit",
    "Outside fixed shading time": "Außerhalb der festen Beschattungszeit",
    "Schedule permits normal shading": "Zeitplan erlaubt normale Beschattung",
    "Night function is not available in this setup": "Für diese Einrichtung ist keine Nachtfunktion verfügbar",
    "Night Mode disabled": "Nachtfunktion deaktiviert",
    "Night source is unknown or unavailable; positions held": "Nachtquelle ist unbekannt oder nicht verfügbar; Positionen werden gehalten",
    "Night source is on": "Nachtquelle ist aktiv",
    "Night source is off": "Nachtquelle ist inaktiv",
    "Sun source unavailable; positions held": "Sonnenquelle nicht verfügbar; Positionen werden gehalten",
    "Sun transitions unavailable; positions held": "Sonnenübergänge nicht verfügbar; Positionen werden gehalten",
    "Inside configured sun Night window": "Innerhalb des konfigurierten Sonnen-Nachtfensters",
    "Outside configured sun Night window": "Außerhalb des konfigurierten Sonnen-Nachtfensters",
  };
  if (translations[text]) return translations[text];
  if (text.startsWith("Safety active: ")) return `Safety aktiv: ${text.slice("Safety active: ".length)}`;
  if (text.startsWith("Waiting: ")) return `Wartet auf: ${text.slice("Waiting: ".length)}`;
  return text.split(" · ").map((part) => translations[part] || part).join(" · ");
}

class SmartShadingV4Dialog extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._hass = null;
    this._roomState = null;
    this._controls = [];
    this._owner = null;
    this._renderQueued = false;
    this._updateCount = 0;
    this._renderCount = 0;
    this._contentWriteCount = 0;
    this._mainHtml = "";
    this._selectedPreviewDate = "";
    this._toolStatus = "";
    this._toolsOpen = false;
    this._technicalOpen = false;
    this._runtimeSupportOpen = false;
    this._opener = null;
    this.shadowRoot?.addEventListener?.("click", (event) => {
      const element = eventElement(event,
        "[data-close],[data-press],[data-tool-press],[data-collapse-toggle],[data-more],[data-night-source],[data-preview-day]",
      );
      if (!element) return;
      if (element.hasAttribute?.("data-close")) {
        this.close();
        return;
      }
      if (element.dataset.press) {
        this._callEntity(element.dataset.press);
        return;
      }
      if (element.dataset.toolPress) {
        this._callEntity(element.dataset.toolPress, { testTool: true });
        return;
      }
      if (element.dataset.collapseToggle) {
        const key = element.dataset.collapseToggle;
        const property = key === "tools" ? "_toolsOpen" : key === "technical" ? "_technicalOpen" : "_runtimeSupportOpen";
        this[property] = !this[property];
        this._render();
        return;
      }
      if (element.dataset.more) {
        this._more(element.dataset.more);
        return;
      }
      if (element.dataset.nightSource) {
        this._openNightSource(element.dataset.nightSource);
        return;
      }
      if (element.hasAttribute?.("data-preview-day")) {
        const main = this.shadowRoot?.querySelector?.("main");
        const selected = main?.querySelector?.("[data-preview-date]")?.value || this._selectedPreviewDate;
        this._previewDay(element.dataset.previewRoom, element.dataset.previewEntry, selected);
      }
    });
    const syncPreviewDate = (event) => {
      const element = eventElement(event, "[data-preview-date]");
      if (!element) return;
      this._selectedPreviewDate = element.value || localDateKey();
    };
    this.shadowRoot?.addEventListener?.("input", syncPreviewDate);
    this.shadowRoot?.addEventListener?.("change", syncPreviewDate);
    this._keyHandler = (event) => {
      if (event.key === "Escape") {
        event.preventDefault?.();
        this.close();
        return;
      }
      if (event.key !== "Tab") return;
      const focusable = asArray(Array.from(this.shadowRoot?.querySelectorAll?.(
        'button:not([disabled]),input:not([disabled]),select:not([disabled]),textarea:not([disabled]),[href],[tabindex]:not([tabindex="-1"])',
      ) || [])).filter((element) => !element.hidden && element.getAttribute?.("aria-hidden") !== "true");
      if (!focusable.length) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      const active = this.shadowRoot?.activeElement;
      if (event.shiftKey && (active === first || !focusable.includes(active))) {
        event.preventDefault?.();
        last.focus?.({ preventScroll: true });
      } else if (!event.shiftKey && active === last) {
        event.preventDefault?.();
        first.focus?.({ preventScroll: true });
      }
    };
  }

  open({ hass, roomState, controls, owner, opener }) {
    this._hass = hass;
    this._roomState = roomState;
    this._controls = controls || [];
    this._owner = owner || null;
    this._opener = opener || this._opener || null;
    this._selectedPreviewDate = previewPayload(roomState?.attributes?.day_preview).day || localDateKey();
    if (!this.isConnected && document.body?.appendChild) document.body.appendChild(this);
    document.addEventListener?.("keydown", this._keyHandler);
    this._render();
    const closeButtons = this.shadowRoot?.querySelectorAll?.("[data-close]") || [];
    closeButtons[closeButtons.length - 1]?.focus?.({ preventScroll: true });
  }

  update({ hass, roomState, controls }) {
    this._updateCount += 1;
    this.dataset.updateCount = String(this._updateCount);
    if (hass) this._hass = hass;
    if (roomState) this._roomState = roomState;
    if (controls) this._controls = controls;
    if (this.isConnected && !this._renderQueued) {
      this._renderQueued = true;
      (globalThis.requestAnimationFrame || ((callback) => callback()))(() => {
        this._renderQueued = false;
        if (this.isConnected) this._render();
      });
    }
  }

  close() {
    document.removeEventListener?.("keydown", this._keyHandler);
    this.remove?.();
    this._opener?.focus?.({ preventScroll: true });
    this._opener = null;
  }

  disconnectedCallback() {
    document.removeEventListener?.("keydown", this._keyHandler);
    this._renderQueued = false;
  }

  _labels() {
    const de = String(this._hass?.language || "en").toLowerCase().startsWith("de");
    return de ? {
      title: "Smart Shading · Details",
      close: "Schließen",
      overview: "Laufzeitübersicht",
      sectors: "Sonnensektoren",
      covers: "Behänge",
      diagnostics: "Diagnosejournal",
      controls: "Steuerung",
      mode: "Modus",
      reason: "Grund",
      schedule: "Zeitplan",
      active: "aktiv",
      inactive: "inaktiv",
      pauseUntil: "Pausiert bis",
      sent: "Befehle gesendet",
      suppressed: "Befehle unterdrückt",
      last: "Letzte Auswertung",
      noEvents: "Keine Diagnoseereignisse vorhanden.",
      noReason: "Kein besonderer Grund",
      position: "Position",
      tilt: "Lamelle",
      target: "Ziel",
      current: "Ist",
      resume: "Fortsetzen",
      pause: "Pausieren",
      evaluate: "Jetzt auswerten",
      reset: "Zurücksetzen",
      exportLog: "Log exportieren",
      paused: "Pausiert",
      master: "Master",
      raw: "Rohwert",
      thresholds: "Schwellen",
      pending: "Umschaltung geplant",
      locked: "Manuell gesperrt",
      unsafeWindow: "Fenster nicht sicher",
      night: "Nachtfunktion",
      source: "Quelle",
      sourceState: "Quellstatus",
      nextTransition: "Nächster Wechsel",
      morningWindow: "Morgenfenster",
      eveningWindow: "Abendfenster",
      openSchedule: "Zeitplan öffnen",
      openSource: "Quelle öffnen",
      blocked: "blockiert",
      decision: "Entscheidungs-Trace",
      winner: "Gewinner",
      rejected: "Verworfene Kandidaten",
      noRejected: "Keine weiteren Kandidaten verworfen.",
      command: "Befehlsausgang",
      inputQuality: "Datenqualität",
      protectedZones: "Geschützte Zonen",
      currentCalculation: "Aktuelle Berechnung",
      ordinaryTarget: "Normales Ziel",
      zoneTarget: "Schutzziel",
      finalTarget: "Endgültiges Ziel",
      localSunEvidence: "Lokale Sonnenbestätigung",
      calculationReady: "Berechnung bereit",
      calculationUnavailable: "Keine gültige Berechnung",
      noTrace: "Noch keine Entscheidungsdaten vorhanden.",
      noProtectedZones: "Keine geschützten Zonen ausgewertet.",
      simulation: "Simulation",
      runSimulation: "Simulation ausführen",
      simulationActive: "Simulation aktiv",
      noSimulation: "Noch keine Simulation ausgeführt.",
      dayPreview: "Tagvorschau",
      previewDay: "Tagvorschau berechnen",
      previewDate: "Datum für Tagvorschau",
      noPreview: "Noch keine Tagvorschau berechnet.",
      samples: "Auswertungen",
      transitions: "Übergänge",
      result: "Ergebnis",
      rule: "Regel",
      quality: "Qualität",
      status: "Status",
      whatNow: "Was passiert gerade?",
      whyNow: "Warum?",
      nextNow: "Als Nächstes",
      tools: "Test & Vorschau",
      technical: "Technische Supportdaten",
      toolsHint: "Testläufe bewegen keine Behänge.",
      toolRunning: "Berechnung wird gestartet …",
      toolReady: "Ergebnis bereit – es wurden keine Behänge bewegt.",
      toolUnavailable: "Die Vorschau ist nach dem Update noch nicht verfügbar. Home Assistant bitte vollständig neu starten.",
      toolFailed: "Die Berechnung konnte nicht gestartet werden.",
    } : {
      title: "Smart Shading · Details",
      close: "Close",
      overview: "Runtime overview",
      sectors: "Sun sectors",
      covers: "Covers",
      diagnostics: "Diagnostic journal",
      controls: "Controls",
      mode: "Mode",
      reason: "Reason",
      schedule: "Schedule",
      active: "active",
      inactive: "inactive",
      pauseUntil: "Paused until",
      sent: "Commands sent",
      suppressed: "Commands suppressed",
      last: "Last evaluation",
      noEvents: "No diagnostic events available.",
      noReason: "No special reason",
      position: "Position",
      tilt: "Tilt",
      target: "Target",
      current: "Current",
      resume: "Resume",
      pause: "Pause",
      evaluate: "Evaluate now",
      reset: "Reset",
      exportLog: "Export log",
      paused: "Paused",
      master: "Master",
      raw: "Raw value",
      thresholds: "Thresholds",
      pending: "Transition scheduled",
      locked: "Manually locked",
      unsafeWindow: "Window not safe",
      night: "Night Mode",
      source: "Source",
      sourceState: "Source state",
      nextTransition: "Next transition",
      morningWindow: "Morning window",
      eveningWindow: "Evening window",
      openSchedule: "Open schedule",
      openSource: "Open source",
      blocked: "blocked",
      decision: "Decision trace",
      winner: "Winner",
      rejected: "Rejected candidates",
      noRejected: "No other candidates were rejected.",
      command: "Command outcome",
      inputQuality: "Input quality",
      protectedZones: "Protected zones",
      currentCalculation: "Current calculation",
      ordinaryTarget: "Ordinary target",
      zoneTarget: "Protected target",
      finalTarget: "Final target",
      localSunEvidence: "Local sun evidence",
      calculationReady: "Calculation ready",
      calculationUnavailable: "No valid calculation",
      noTrace: "No decision data is available yet.",
      noProtectedZones: "No protected zones were evaluated.",
      simulation: "Simulation",
      runSimulation: "Run simulation",
      simulationActive: "Simulation active",
      noSimulation: "No simulation has been run yet.",
      dayPreview: "Day preview",
      previewDay: "Calculate day preview",
      previewDate: "Date for day preview",
      noPreview: "No day preview has been calculated yet.",
      samples: "Evaluations",
      transitions: "Transitions",
      result: "Result",
      rule: "Rule",
      quality: "Quality",
      status: "Status",
      whatNow: "What is happening now?",
      whyNow: "Why?",
      nextNow: "What happens next?",
      tools: "Test & preview",
      technical: "Technical support data",
      toolsHint: "Test runs never move covers.",
      toolRunning: "Starting calculation …",
      toolReady: "Result ready – no covers were moved.",
      toolUnavailable: "Preview is not available after this update yet. Please fully restart Home Assistant.",
      toolFailed: "The calculation could not be started.",
    };
  }

  _modeText(mode, profile = "") {
    const de = String(this._hass?.language || "en").toLowerCase().startsWith("de");
    if (mode === "open" && profile === "awning") {
      return de ? "Eingefahren" : "Retracted";
    }
    const values = de ? {
      safety: "Safety", heat: "Heat Protection", glare: "Blendschutz", solar: "Sonnenschutz",
      comfort: "Komfort", paused: "Pausiert", open: "Offen", idle: "Bereit",
      disabled: "Master aktiv", finished: "Für heute beendet",
      night: "Nacht",
    } : {
      safety: "Safety", heat: "Heat protection", glare: "Glare protection", solar: "Solar shading",
      comfort: "Comfort", paused: "Paused", open: "Open", idle: "Ready",
      disabled: "Master active", finished: "Finished today",
      night: "Night",
    };
    return values[mode] || String(mode || "–");
  }

  _statusText(status) {
    const de = String(this._hass?.language || "en").toLowerCase().startsWith("de");
    const values = de ? {
      not_evaluated: "Noch nicht ausgewertet", outside_sun_sector: "Sonne außerhalb des Sektors",
      waiting_for_lux: "Wartet auf Sun Presence", sun_detected: "Sonne erkannt",
      shading_active: "Beschattung aktiv", waiting_conditions: "Wartet auf Bedingungen",
      sun_below_horizon: "Sonne unter Horizont", schedule_blocked: "Zeitplan blockiert", source_unavailable: "Quelle nicht verfügbar",
      paused: "Pausiert", heat: "Heat Protection", safety: "Safety", disabled: "Deaktiviert",
      night: "Nacht", night_blocked: "Nachtquelle blockiert", night_transition_hold: "Nachtübergang hält",
    } : {
      not_evaluated: "Not evaluated", outside_sun_sector: "Sun outside sector",
      waiting_for_lux: "Waiting for Sun Presence", sun_detected: "Sun detected",
      shading_active: "Shading active", waiting_conditions: "Waiting for conditions",
      sun_below_horizon: "Sun below horizon", schedule_blocked: "Schedule blocked", source_unavailable: "Source unavailable",
      paused: "Paused", heat: "Heat protection", safety: "Safety", disabled: "Disabled",
      night: "Night", night_blocked: "Night source blocked", night_transition_hold: "Night transition hold",
    };
    return values[status] || String(status || "–");
  }

  _suppressionText(reason) {
    const de = String(this._hass?.language || "en").toLowerCase().startsWith("de");
    const values = de ? {
      cover_paused_until_morning: "Pausiert bis zum nächsten Morgen",
      automation_lock: "Manuell gesperrt", unsafe_window: "Fenster nicht sicher",
      unsafe_window_closing_blocked: "Schließen durch Fensterkontakt blockiert",
      position_already_correct: "Position bereits korrekt", tilt_already_correct: "Lamelle bereits korrekt",
      position_command_cooldown: "Positionsbefehl im Cooldown", tilt_command_cooldown: "Lamellenbefehl im Cooldown",
      position_feedback_unknown: "Positionsrückmeldung fehlt", tilt_feedback_unknown: "Lamellenrückmeldung fehlt",
    } : {
      cover_paused_until_morning: "Paused until next morning",
      automation_lock: "Manually locked", unsafe_window: "Window not safe",
      unsafe_window_closing_blocked: "Closing blocked by window contact",
      position_already_correct: "Position already correct", tilt_already_correct: "Tilt already correct",
      position_command_cooldown: "Position command cooldown", tilt_command_cooldown: "Tilt command cooldown",
      position_feedback_unknown: "Position feedback missing", tilt_feedback_unknown: "Tilt feedback missing",
    };
    return values[reason] || this._traceText(reason);
  }

  _traceText(value) {
    const de = String(this._hass?.language || "en").toLowerCase().startsWith("de");
    const labels = de ? {
      safety: "Safety", manual_master_override: "Manuelle Sperre", room_pause: "Raumpause",
      local_cover_pause: "Lokale Behangpause", night_source_hold: "Nachtquelle hält", schedule_hold: "Zeitplan hält", night: "Nachtfunktion", heat_protection: "Heat Protection",
      input_quality_hold: "Halten wegen Eingabequalität", glare_protection: "Blendschutz", solar: "Sonnenschutz", comfort: "Komfort", open: "Öffnen", idle: "Halten",
      planned: "Geplant", queued: "Warteschlange", sent: "Gesendet", suppressed: "Unterdrückt", blocked: "Blockiert",
      target_reached: "Ziel erreicht", target_not_reached: "Ziel nicht erreicht", failed: "Fehlgeschlagen", cancelled: "Abgebrochen",
      not_planned: "Noch nicht geplant", simulated: "Simuliert", valid: "Gültig", stale: "Veraltet",
      unavailable: "Nicht verfügbar", invalid_value: "Ungültiger Wert", not_configured: "Nicht eingerichtet",
      pending: "Ausstehend", contradictory: "Widersprüchlich", hit: "Getroffen", miss: "Verfehlt", inactive: "Inaktiv", invalid: "Ungültig",
      winner: "Gewinner", rejected: "Verworfen",
      highest_matching_priority: "Höchste passende Priorität", rule_not_matched: "Regel nicht zutreffend",
      same_priority_tiebreaker_rule_order: "Gleiche Priorität: feste Regelreihenfolge",
      same_priority_tiebreaker_stable_order: "Gleiche Priorität: stabile Reihenfolge",
      no_decision_rule_matched: "Keine Entscheidungsregel zutreffend", rule_mode_mismatch: "Regelmodus passt nicht",
      safety_active: "Safety aktiv", safety_inactive: "Safety nicht aktiv",
      manual_master_override_active: "Manuelle Sperre aktiv", manual_master_override_inactive: "Manuelle Sperre nicht aktiv",
      room_pause_active: "Raumpause aktiv", room_pause_inactive: "Raumpause nicht aktiv",
      local_cover_pause_active: "Lokale Behangpause aktiv", local_cover_pause_inactive: "Lokale Behangpause nicht aktiv",
      night_source_unavailable_hold: "Nachtquelle nicht verfügbar – Position wird gehalten", night_source_available: "Nachtquelle verfügbar",
      night_active: "Nachtfunktion aktiv", night_inactive: "Nachtfunktion nicht aktiv",
      heat_protection_active: "Heat Protection aktiv", heat_protection_inactive: "Heat Protection nicht aktiv",
      schedule_outside_hold: "Außerhalb des Zeitplans – Position wird gehalten", schedule_active: "Zeitplan aktiv",
      normal_input_quality_invalid_hold: "Normale Eingaben ungültig – Position wird gehalten", normal_input_quality_valid: "Normale Eingaben gültig",
      solar_glare_target_adjusted: "Sonnenschutzziel durch Blendschutz angepasst", solar_conditions_met: "Sonnenschutzbedingungen erfüllt",
      solar_blocked_by_input_quality: "Sonnenschutz durch Eingabequalität blockiert", solar_inactive: "Sonnenschutz nicht aktiv",
      comfort_blocked_by_input_quality: "Komfort durch Eingabequalität blockiert", comfort_active: "Komfortbedingungen erfüllt", comfort_inactive: "Komfortbedingungen nicht aktiv",
      open_blocked_by_input_quality: "Öffnen durch Eingabequalität blockiert", open_fallback: "Öffnungsziel gewählt", open_inactive: "Öffnungsregel nicht aktiv",
      idle_hold_active: "Haltebedingung aktiv", idle_inactive: "Haltebedingung nicht aktiv",
      input_not_configured: "Eingabe nicht eingerichtet", input_unavailable: "Eingabe nicht verfügbar", input_invalid_value: "Eingabewert ungültig",
      input_stale: "Eingabe veraltet", input_valid: "Eingabe gültig",
      pure_decision_requires_command_planner: "Entscheidung wartet auf den Befehlsplaner",
      simulation_never_executes_services: "Simulation löst keine Dienste aus",
      simulation_advanced_mode_required: "Simulation benötigt die detaillierte Einrichtung",
      preview_advanced_mode_required: "Tagvorschau benötigt die detaillierte Einrichtung",
      preview_never_executes_services: "Tagvorschau löst keine Dienste aus",
      decision_changed: "Entscheidung geändert", decision_selected: "Entscheidung ausgewählt", command_dispatched: "Befehl ausgelöst", command_not_planned: "Kein Befehl geplant",
      command_adapter_result: "Befehlsausführung abgeschlossen", command_lifecycle_updated: "Befehlslebenszyklus aktualisiert", cover_command_sent: "Behangbefehl gesendet",
      cover_command_queued: "Behangbefehl eingereiht", cover_command_cancelled: "Behangbefehl abgebrochen", cover_command_suppressed: "Behangbefehl unterdrückt",
      cover_target_verification: "Behangziel wird geprüft", target_confirmed_by_trusted_feedback: "Ziel durch verlässliche Rückmeldung bestätigt",
      cover_removed_before_execution: "Behang vor Ausführung entfernt", cover_entity_missing: "Behang-Entität fehlt", cover_service_failed: "Behang-Service fehlgeschlagen",
      command_ownership_released: "Automatisierungsbesitz freigegeben", position_control_unsupported: "Positionssteuerung nicht unterstützt", tilt_control_unsupported: "Lamellensteuerung nicht unterstützt",
      target_already_active: "Ziel ist bereits aktiv", higher_priority_lifecycle_active: "Höherprioritärer Ablauf aktiv", authoritative_replacement: "Veraltetes Ziel durch aktuelle Auswertung ersetzt", safety_source_unavailable_hold: "Sicherheitssensor nicht verfügbar; automatische Fahrten angehalten",
      replaced_by_newer_target: "Durch neueres Ziel ersetzt", target_within_tolerance: "Ziel innerhalb der Toleranz",
      automatic_reverse_not_allowed: "Automatische Rückfahrt nicht erlaubt", target_planned: "Ziel geplant", safety_replacement: "Safety ersetzt laufendes Ziel",
      target_confirmed_at_deadline: "Ziel zum Prüftermin bestätigt", feedback_not_at_target_after_retry_limit: "Ziel nach Wiederholungsgrenze nicht erreicht",
      target_confirmed_before_retry: "Ziel vor Wiederholung bestätigt", verification_retry_planned: "Prüfwiederholung geplant",
      no_cover_target: "Kein Behangziel", room_or_cover_pause_active: "Raum- oder Behangpause aktiv", night_mode_active: "Nachtfunktion aktiv",
      solar_conditions_matched: "Sonnenschutzbedingungen erfüllt", comfort_conditions_matched: "Komfortbedingungen erfüllt", open_target_selected: "Öffnungsziel ausgewählt",
      conditions_waiting: "Wartet auf Bedingungen", selected_sun_source_unavailable: "Gewählte Sonnenquelle nicht verfügbar",
      sun_position_unavailable: "Sonnenposition nicht verfügbar", room_automation_paused: "Raumautomatik pausiert", room_automation_disabled: "Raumautomatik deaktiviert",
      night_source_unavailable: "Nachtquelle nicht verfügbar", evening_night_handoff_hold: "Abendübergabe an Nachtfunktion hält",
      night_transition_hold: "Nachtübergang hält",
      cover_paused_until_morning: "Pausiert bis zum nächsten Morgen", automation_lock: "Manuell gesperrt", unsafe_window: "Fenster nicht sicher",
      unsafe_window_closing_blocked: "Schließen durch Fensterkontakt blockiert", window_state_unavailable: "Fensterzustand nicht verfügbar",
      position_already_correct: "Position bereits korrekt", tilt_already_correct: "Lamelle bereits korrekt",
      position_command_cooldown: "Positionsbefehl im Cooldown", tilt_command_cooldown: "Lamellenbefehl im Cooldown",
      position_feedback_unknown: "Positionsrückmeldung fehlt", tilt_feedback_unknown: "Lamellenrückmeldung fehlt",
      protected_zone_direct_sun_hit: "Direkte Sonne trifft die Zone",
      protected_zone_lateral_miss: "Seitlich außerhalb der Zone",
      protected_zone_vertical_miss: "Vertikal außerhalb der Zone",
      protected_zone_sun_behind_facade: "Sonne hinter der Fassade",
      protected_zone_direct_sun_inactive: "Direkte Sonne nicht aktiv",
      protected_zone_disabled: "Zone deaktiviert",
      protected_zone_conditions_not_met: "Aktivierungsbedingungen nicht erfüllt",
      protected_zone_conditions_unavailable: "Aktivierungsbedingungen nicht auswertbar",
      protected_zone_invalid: "Zonengeometrie ungültig",
      protected_zone_valid: "Zonengeometrie gültig", protected_zone_sector_context_required: "Sonnensektor-Kontext fehlt",
      protected_zone_other_sector: "Andere Sonnensektoren-Zuordnung", protected_zone_group_context_required: "Behanggruppen-Kontext fehlt",
      protected_zone_other_group: "Andere Behanggruppen-Zuordnung", protected_zone_sun_below_horizon: "Sonne unter dem Horizont",
      protected_zone_lateral_geometry_required: "Seitliche Zonengeometrie fehlt",
      no_protected_zone_hit: "Keine Zone getroffen",
      protected_zone_target_adjusted: "Ziel durch Schutzzone angepasst",
      protected_zone_hit_no_stricter_target: "Schutzzone ohne strengeres Ziel",
      protected_zone_inactive: "Keine aktive Schutzzone",
      glare_blocked_by_input_quality: "Blendschutz wegen fehlender Sonnenwerte gehalten",
    } : {
      safety: "Safety", manual_master_override: "Manual Override", room_pause: "Room pause",
      local_cover_pause: "Local cover pause", night_source_hold: "Night source hold", schedule_hold: "Schedule hold", night: "Night Mode", heat_protection: "Heat protection",
      input_quality_hold: "Hold for input quality", glare_protection: "Glare protection", solar: "Solar shading", comfort: "Comfort", open: "Open", idle: "Hold",
      planned: "Planned", queued: "Queued", sent: "Sent", suppressed: "Suppressed", blocked: "Blocked",
      target_reached: "Target reached", target_not_reached: "Target not reached", failed: "Failed", cancelled: "Cancelled",
      not_planned: "Not planned", simulated: "Simulated", valid: "Valid", stale: "Stale",
      unavailable: "Unavailable", invalid_value: "Invalid value", not_configured: "Not configured",
      pending: "Pending", contradictory: "Contradictory", hit: "Hit", miss: "Miss", inactive: "Inactive", invalid: "Invalid",
      winner: "Winner", rejected: "Rejected",
      highest_matching_priority: "Highest matching priority", rule_not_matched: "Rule did not match",
      same_priority_tiebreaker_rule_order: "Same priority: fixed rule order",
      same_priority_tiebreaker_stable_order: "Same priority: stable order",
      no_decision_rule_matched: "No decision rule matched", rule_mode_mismatch: "Rule mode does not match",
      safety_active: "Safety active", safety_inactive: "Safety inactive",
      manual_master_override_active: "Manual override active", manual_master_override_inactive: "Manual override inactive",
      room_pause_active: "Room pause active", room_pause_inactive: "Room pause inactive",
      local_cover_pause_active: "Local cover pause active", local_cover_pause_inactive: "Local cover pause inactive",
      night_source_unavailable_hold: "Night source unavailable – target held", night_source_available: "Night source available",
      night_active: "Night mode active", night_inactive: "Night mode inactive",
      heat_protection_active: "Heat protection active", heat_protection_inactive: "Heat protection inactive",
      schedule_outside_hold: "Outside schedule – target held", schedule_active: "Schedule active",
      normal_input_quality_invalid_hold: "Normal inputs invalid – target held", normal_input_quality_valid: "Normal inputs valid",
      solar_glare_target_adjusted: "Solar target adjusted for glare", solar_conditions_met: "Solar conditions met",
      solar_blocked_by_input_quality: "Solar shading blocked by input quality", solar_inactive: "Solar shading inactive",
      comfort_blocked_by_input_quality: "Comfort blocked by input quality", comfort_active: "Comfort conditions met", comfort_inactive: "Comfort conditions inactive",
      open_blocked_by_input_quality: "Opening blocked by input quality", open_fallback: "Open target selected", open_inactive: "Open rule inactive",
      idle_hold_active: "Hold condition active", idle_inactive: "Hold condition inactive",
      input_not_configured: "Input not configured", input_unavailable: "Input unavailable", input_invalid_value: "Input value invalid",
      input_stale: "Input stale", input_valid: "Input valid",
      pure_decision_requires_command_planner: "Decision awaits the command planner",
      simulation_never_executes_services: "Simulation never executes services",
      simulation_advanced_mode_required: "Simulation requires detailed setup",
      preview_advanced_mode_required: "Day preview requires detailed setup",
      preview_never_executes_services: "Day preview never executes services",
      decision_changed: "Decision changed", decision_selected: "Decision selected", command_dispatched: "Command dispatched", command_not_planned: "No command planned",
      command_adapter_result: "Command execution completed", command_lifecycle_updated: "Command lifecycle updated", cover_command_sent: "Cover command sent",
      cover_command_queued: "Cover command queued", cover_command_cancelled: "Cover command cancelled", cover_command_suppressed: "Cover command suppressed",
      cover_target_verification: "Cover target verification", target_confirmed_by_trusted_feedback: "Target confirmed by trusted feedback",
      cover_removed_before_execution: "Cover removed before execution", cover_entity_missing: "Cover entity is missing", cover_service_failed: "Cover service failed",
      command_ownership_released: "Automation ownership released", position_control_unsupported: "Position control is unsupported", tilt_control_unsupported: "Tilt control is unsupported",
      target_already_active: "Target is already active", higher_priority_lifecycle_active: "Higher-priority lifecycle active", authoritative_replacement: "Obsolete target replaced by current evaluation", safety_source_unavailable_hold: "Safety sensor unavailable; automatic movements held",
      replaced_by_newer_target: "Replaced by newer target", target_within_tolerance: "Target within tolerance",
      automatic_reverse_not_allowed: "Automatic reverse is not allowed", target_planned: "Target planned", safety_replacement: "Safety replaced active target",
      target_confirmed_at_deadline: "Target confirmed at deadline", feedback_not_at_target_after_retry_limit: "Target not reached after retry limit",
      target_confirmed_before_retry: "Target confirmed before retry", verification_retry_planned: "Verification retry planned",
      no_cover_target: "No cover target", room_or_cover_pause_active: "Room or cover pause active", night_mode_active: "Night mode active",
      solar_conditions_matched: "Solar conditions matched", comfort_conditions_matched: "Comfort conditions matched", open_target_selected: "Open target selected",
      conditions_waiting: "Waiting for conditions", selected_sun_source_unavailable: "Selected sun source is unavailable",
      sun_position_unavailable: "Sun position is unavailable", room_automation_paused: "Room automation is paused", room_automation_disabled: "Room automation is disabled",
      night_source_unavailable: "Night source is unavailable", evening_night_handoff_hold: "Evening Night handoff holds",
      night_transition_hold: "Night transition holds",
      cover_paused_until_morning: "Paused until next morning", automation_lock: "Manually locked", unsafe_window: "Window not safe",
      unsafe_window_closing_blocked: "Closing blocked by window contact", window_state_unavailable: "Window state unavailable",
      position_already_correct: "Position already correct", tilt_already_correct: "Tilt already correct",
      position_command_cooldown: "Position command cooldown", tilt_command_cooldown: "Tilt command cooldown",
      position_feedback_unknown: "Position feedback missing", tilt_feedback_unknown: "Tilt feedback missing",
      protected_zone_direct_sun_hit: "Direct sun hits the zone",
      protected_zone_lateral_miss: "Outside the lateral zone range",
      protected_zone_vertical_miss: "Outside the vertical zone range",
      protected_zone_sun_behind_facade: "Sun is behind the facade",
      protected_zone_direct_sun_inactive: "Direct sun is inactive",
      protected_zone_disabled: "Zone disabled",
      protected_zone_conditions_not_met: "Activation conditions are not met",
      protected_zone_conditions_unavailable: "Activation conditions are unavailable",
      local_sensor: de ? "Lokaler Sensor" : "Local sensor",
      weather_fallback: de ? "Wetter-Fallback" : "Weather fallback",
      not_configured: de ? "Nicht eingerichtet" : "Not configured",
      on_threshold_met: de ? "Einschaltgrenze erreicht" : "On threshold reached",
      off_threshold_met: de ? "Ausschaltgrenze erreicht" : "Off threshold reached",
      hysteresis_active: de ? "Innerhalb Hysterese, aktiv" : "Inside hysteresis, active",
      hysteresis_inactive: de ? "Innerhalb Hysterese, inaktiv" : "Inside hysteresis, inactive",
      weather_sunny: de ? "Sunny bestätigt" : "Sunny confirmed",
      weather_not_sunny: de ? "Wetter nicht sunny" : "Weather is not sunny",
      weather_unavailable: de ? "Wetter nicht verfügbar" : "Weather unavailable",
      local_unavailable: de ? "Lokaler Sensor nicht verfügbar" : "Local sensor unavailable",
      invalid_thresholds: de ? "Ungültige Grenzwerte" : "Invalid thresholds",
      protected_zone_invalid: "Zone geometry is invalid",
      protected_zone_valid: "Zone geometry is valid", protected_zone_sector_context_required: "Sun-sector context is required",
      protected_zone_other_sector: "Assigned to another sun sector", protected_zone_group_context_required: "Cover-group context is required",
      protected_zone_other_group: "Assigned to another cover group", protected_zone_sun_below_horizon: "Sun is below the horizon",
      protected_zone_lateral_geometry_required: "Lateral zone geometry is required",
      no_protected_zone_hit: "No zone hit",
      protected_zone_target_adjusted: "Target adjusted by protected zone",
      protected_zone_hit_no_stricter_target: "Protected zone had no stricter target",
      protected_zone_inactive: "No active protected zone",
      glare_blocked_by_input_quality: "Glare protection held because sun data is unavailable",
    };
    const key = String(value || "").trim();
    if (key.startsWith("lower_priority_than_")) {
      const winner = this._traceText(key.slice("lower_priority_than_".length));
      return de ? `Niedrigere Priorität als ${winner}` : `Lower priority than ${winner}`;
    }
    return labels[key] || humanizeToken(key);
  }

  _diagnosticEventTitle(value) {
    const de = String(this._hass?.language || "en").toLowerCase().startsWith("de");
    const labels = de ? {
      room_evaluated: "Raumstatus aktualisiert",
      room_mode_changed: "Raummodus geändert",
      evaluation_started: "Auswertung gestartet",
      external_cover_movement_confirmed: "Externe Behangfahrt erkannt",
      cover_change_observed: "Behangbewegung geprüft",
      room_automation_paused: "Raumautomatik pausiert",
      room_pause_ended: "Raumautomatik fortgesetzt",
      manual_override_group_started: "Behanggruppe pausiert",
      manual_override_group_ended: "Behanggruppe fortgesetzt",
      diagnostic_level: "Diagnoseumfang geändert",
    } : {
      room_evaluated: "Room status updated",
      room_mode_changed: "Room mode changed",
      evaluation_started: "Evaluation started",
      external_cover_movement_confirmed: "External cover movement detected",
      cover_change_observed: "Cover movement checked",
      room_automation_paused: "Room automation paused",
      room_pause_ended: "Room automation resumed",
      manual_override_group_started: "Cover group paused",
      manual_override_group_ended: "Cover group resumed",
      diagnostic_level: "Diagnostic level changed",
    };
    const key = String(value || "").trim();
    return labels[key] || this._traceText(key);
  }

  _diagnosticEventDetails(event) {
    const de = String(this._hass?.language || "en").toLowerCase().startsWith("de");
    const eventName = String(event.event || event.type || "");
    const fieldLabels = de ? {
      room: "Raum", previous: "Vorher", mode: "Modus", reason: "Grund",
      trigger: "Auslöser", status: "Status", targets: "Behangziele",
      active_sectors: "Aktive Bereiche", cover: "Behang", entity_id: "Entität",
      axis: "Bewegung", direction: "Richtung", level: "Umfang",
    } : {
      room: "Room", previous: "Previous", mode: "Mode", reason: "Reason",
      trigger: "Trigger", status: "Status", targets: "Cover targets",
      active_sectors: "Active areas", cover: "Cover", entity_id: "Entity",
      axis: "Movement", direction: "Direction", level: "Level",
    };
    const preferred = eventName === "room_evaluated"
      ? ["room", "mode", "reason", "active_sectors", "targets"]
      : ["room", "cover", "mode", "previous", "reason", "status", "axis", "direction", "trigger", "level", "entity_id"];
    return preferred.flatMap((key) => {
      if (!(key in event) || event[key] == null || event[key] === "") return [];
      let value = event[key];
      if (key === "mode" || key === "previous") value = this._modeText(value);
      else if (["reason", "status", "direction", "axis"].includes(key)) value = this._traceText(value);
      else if (key === "entity_id") value = cleanDisplayName(this._hass?.states?.[value]?.attributes?.friendly_name, value);
      else if (Array.isArray(value)) value = value.length ? value.map((item) => cleanDisplayName(item, item)).join(", ") : (de ? "Keine" : "None");
      return [`${fieldLabels[key] || humanizeToken(key)}: ${String(value)}`];
    }).join(" · ") || (de ? "Keine weiteren Angaben" : "No further details");
  }

  _traceTarget(target, L) {
    const value = asRecord(target);
    const position = asNumber(value.position, null);
    const tilt = asNumber(value.tilt, null);
    const parts = [];
    if (position != null) parts.push(`${L.position}: ${Math.round(position)}%`);
    if (tilt != null) parts.push(`${L.tilt}: ${Math.round(tilt)}%`);
    return parts.join(" · ") || "–";
  }

  _decisionTraceHtml(attrs, L) {
    // The details dialog is only ever opened from the Advanced card, but keep
    // the guard here too: status attributes can outlive a mode switch briefly.
    if (attrs.smart_shading_layout !== "detailed") return "";
    const trace = tracePayload(attrs.decision_trace);
    const winner = asRecord(trace.winner);
    const traceEntries = asArray(trace.entries);
    const winnerEntry = traceEntries.find((raw) => asRecord(raw).outcome === "winner");
    const rejected = traceEntries.length
      ? traceEntries
        .filter((raw) => asRecord(raw).outcome !== "winner")
        .map((raw) => {
          const entry = asRecord(raw);
          return {
            ...asRecord(entry.candidate),
            resolution_reason_code: entry.resolution_reason_code,
          };
        })
      : asArray(trace.rejected);
    const command = asRecord(trace.command_result);
    const commandRows = asArray(asRecord(attrs.decision_trace).command_results);
    const firstCommandRow = asRecord(commandRows[0]);
    const commandStatus = command.status && command.status !== "not_planned"
      ? command.status
      : firstCommandRow.status || command.status;
    const commandReason = command.reason_code && command.status !== "not_planned"
      ? command.reason_code
      : firstCommandRow.reason_code || command.reason_code;
    const targetTraces = targetTracePayloads(attrs.decision_trace);
    const scopedRejected = targetTraces.flatMap(({ scope, trace: targetTrace }) => {
      const entries = asArray(targetTrace.entries);
      const candidates = entries.length
        ? entries
          .filter((raw) => asRecord(raw).outcome !== "winner")
          .map((raw) => {
            const entry = asRecord(raw);
            return {
              ...asRecord(entry.candidate),
              resolution_reason_code: entry.resolution_reason_code,
            };
          })
        : asArray(targetTrace.rejected).map(asRecord);
      return candidates.map((candidate) => ({
        ...candidate,
        layer_name: scope.layer_name || scope.layer_id || "",
      }));
    });
    const snapshot = asRecord(trace.input_snapshot);
    const inputs = Object.entries(asRecord(snapshot.inputs));
    const calculatedZones = protectedZoneCalculationPayloads(attrs);
    const zones = calculatedZones.length
      ? calculatedZones
      : protectedZonePayloads(attrs.decision_trace);
    const simulate = this._control("simulate");
    const previewButton = this._control("preview_day");
    const simulationResults = simulationResultPayloads(attrs.simulation_trace).map(({ scope, result, trace: resultTrace }, index) => {
      const winner = asRecord(resultTrace.winner);
      const command = asRecord(resultTrace.command_result);
      const winnerTarget = asRecord(winner.target);
      const resultTarget = asRecord(result.target);
      const commandTarget = asRecord(command.target);
      const sector = String(scope.sector_name || result.sector_name || "").trim()
        || humanizeToken(scope.sector_id || result.sector_id, "");
      const layer = String(scope.layer_name || result.layer_name || "").trim()
        || humanizeToken(scope.layer_id || result.layer_id, "");
      const covers = asArray(scope.cover_targets).map((raw, coverIndex) => {
        const cover = asRecord(raw);
        const name = cleanDisplayName(cover.name, humanizeToken(cover.cover_id, `${L.cover} ${coverIndex + 1}`));
        const constraints = asArray(cover.constraints).map((reason) => this._suppressionText(reason));
        const target = {
          position: cover.command_position ?? cover.position,
          tilt: cover.command_tilt ?? cover.tilt,
        };
        return {
          name,
          status: cover.command_result || "simulated",
          reason: cover.reason_code || "simulation_never_executes_services",
          target,
          constraints,
        };
      });
      return {
        scope: [sector, layer].filter(Boolean).join(" · ") || `${L.result} ${index + 1}`,
        winner: winner.rule || result.rule || winner.mode || result.mode || scope.mode,
        mode: winner.mode || result.mode || scope.mode,
        target: Object.keys(winnerTarget).length
          ? winnerTarget
          : Object.keys(resultTarget).length
            ? resultTarget
            : commandTarget,
        reason: winner.reason_code || result.reason_code || command.reason_code || scope.reason_code,
        status: command.status || result.status || scope.status || "simulated",
        covers,
      };
    });
    const preview = previewPayload(attrs.day_preview);
    const transitions = asArray(preview.transitions);
    const samples = asArray(preview.samples);
    const previewDate = this._selectedPreviewDate || preview.day || localDateKey();
    const roomId = String(attrs.smart_shading_room_id || "");
    const entryId = String(attrs.smart_shading_entry_id || "");
    const traceAvailable = Object.keys(trace).length > 0;
    const inputHtml = inputs.length ? inputs.map(([key, raw]) => {
      const input = asRecord(raw);
      const quality = String(input.quality || "not_configured");
      const measured = input.value ?? input.raw_value;
      const unit = input.unit ? ` ${input.unit}` : "";
      return `<div class="trace-item">
        <strong>${htmlEscape(humanizeToken(key))}</strong>
        <span class="trace-status ${quality === "valid" ? "ok" : "warn"}">${htmlEscape(this._traceText(quality))}</span>
        <small>${htmlEscape(measured == null ? "–" : `${measured}${unit}`)} · ${htmlEscape(this._traceText(input.reason_code))}</small>
      </div>`;
    }).join("") : `<div class="empty">${htmlEscape(L.noTrace)}</div>`;
    const allRejected = [...rejected, ...scopedRejected];
    const rejectedHtml = allRejected.length ? allRejected.map((raw) => {
      const candidate = asRecord(raw);
      const resolution = candidate.resolution_reason_code
        ? ` · ${this._traceText(candidate.resolution_reason_code)}`
        : "";
      return `<div class="trace-item">
        <strong>${htmlEscape(`${this._traceText(candidate.rule)}${candidate.layer_name ? ` · ${candidate.layer_name}` : ""}`)}</strong>
        <span class="trace-status">${htmlEscape(this._modeText(candidate.mode))}</span>
        <small>${htmlEscape(`${this._traceText(candidate.reason_code)}${resolution}`)}</small>
      </div>`;
    }).join("") : `<div class="empty">${htmlEscape(L.noRejected)}</div>`;
    const zoneHtml = zones.length ? zones.map((raw) => {
      const zone = asRecord(raw);
      const status = String(zone.status || "inactive");
      const details = asRecord(zone.details);
      const projected = asArray(
        zone.projected_height_range_m || details.projected_height_range_m
      );
      const calculation = String(details.calculation || "").trim();
      const calculatedPosition = asNumber(details.calculated_position, null);
      const calculatedTilt = asNumber(details.calculated_tilt, null);
      const calculationParts = [
        calculation ? humanizeToken(calculation) : "",
        projected.length === 2
          ? `${projected.map((value) => Number(value).toFixed(2)).join("–")} m`
          : "",
        asNumber(details.relative_azimuth_degrees, null) != null
          ? `${Math.round(Number(details.relative_azimuth_degrees))}°`
          : "",
      ].filter(Boolean);
      const evidenceValue = asNumber(details.sun_evidence_value, null);
      const evidenceUnit = String(details.sun_evidence_unit || "").trim();
      const evidenceSource = String(details.sun_evidence_source || "").trim();
      const evidenceStatus = String(details.sun_evidence_status || "").trim();
      const evidenceEntityId = String(details.sun_evidence_entity_id || "").trim();
      const evidenceEntityName = evidenceEntityId
        ? cleanDisplayName(
          this.hass?.states?.[evidenceEntityId]?.attributes?.friendly_name,
          humanizeToken(evidenceEntityId.split(".").pop(), evidenceEntityId),
        )
        : "";
      const evidenceParts = [
        evidenceSource ? this._traceText(evidenceSource) : "",
        evidenceEntityName,
        evidenceValue != null ? `${Math.round(evidenceValue)}${evidenceUnit ? ` ${evidenceUnit}` : ""}` : "",
        asNumber(details.sun_evidence_on_threshold, null) != null
          ? `ON ≥ ${Math.round(Number(details.sun_evidence_on_threshold))}`
          : "",
        asNumber(details.sun_evidence_off_threshold, null) != null
          ? `OFF ≤ ${Math.round(Number(details.sun_evidence_off_threshold))}`
          : "",
        evidenceStatus ? this._traceText(evidenceStatus) : "",
      ].filter(Boolean);
      const zoneTarget = zone.target || (
        calculatedPosition != null || calculatedTilt != null
          ? { position: calculatedPosition, tilt: calculatedTilt }
          : null
      );
      return `<div class="trace-item">
        <strong>${htmlEscape(`${cleanDisplayName(zone.name, humanizeToken(zone.zone_id, L.protectedZones))}${zone.cover_name ? ` · ${zone.cover_name}` : zone.layer_name ? ` · ${zone.layer_name}` : ""}`)}</strong>
        <span class="trace-status ${status === "hit" ? "ok" : "warn"}">${htmlEscape(this._traceText(status))}</span>
        <small>${htmlEscape(this._traceText(zone.reason_code))}${calculationParts.length ? ` · ${htmlEscape(calculationParts.join(" · "))}` : ""}</small>
        ${evidenceParts.length ? `<small data-zone-sun-evidence>${htmlEscape(`${L.localSunEvidence}: ${evidenceParts.join(" · ")}`)}</small>` : ""}
        <small data-zone-targets>${htmlEscape(`${L.ordinaryTarget}: ${this._traceTarget(zone.ordinary_target, L)} · ${L.zoneTarget}: ${this._traceTarget(zoneTarget, L)} · ${L.finalTarget}: ${this._traceTarget(zone.final_target, L)}`)}</small>
      </div>`;
    }).join("") : `<div class="empty">${htmlEscape(L.noProtectedZones)}</div>`;
    const simulationHtml = simulationResults.length ? `<div class="trace-list" data-simulation-results>${simulationResults.map((simulated) => `<div class="trace-item" data-simulation-result>
        <strong>${htmlEscape(simulated.scope)}</strong>
        <span class="trace-status">${htmlEscape(this._traceText(simulated.status))}</span>
        <small>${htmlEscape(`${L.winner}: ${this._traceText(simulated.winner)} · ${L.mode}: ${this._modeText(simulated.mode)} · ${L.target}: ${this._traceTarget(simulated.target, L)} · ${L.reason}: ${this._traceText(simulated.reason)}`)}</small>
        ${simulated.covers.length ? `<small data-simulation-cover-targets>${simulated.covers.map((cover) => htmlEscape(`${cover.name}: ${this._traceText(cover.status)} · ${this._traceTarget(cover.target, L)} · ${this._traceText(cover.reason)}${cover.constraints.length ? ` · ${cover.constraints.join(", ")}` : ""}`)).join("<br>")}</small>` : ""}
      </div>`).join("")}</div>`
      : `<div class="empty">${htmlEscape(L.noSimulation)}</div>`;
    const transitionHtml = transitions.length ? transitions.slice(0, 12).map((raw) => {
      const transition = asRecord(raw);
      return `<div class="trace-item">
        <strong>${htmlEscape(this._formatDate(transition.at))}</strong>
        <span class="trace-status">${htmlEscape(this._modeText(transition.previous_mode))} → ${htmlEscape(this._modeText(transition.mode))}</span>
        <small>${htmlEscape(this._traceTarget(transition.target, L))} · ${htmlEscape(this._traceText(transition.reason_code))}</small>
      </div>`;
    }).join("") : `<div class="empty">${htmlEscape(L.noPreview)}</div>`;
    const commandHtml = commandRows.length ? commandRows.map((raw) => {
      const row = asRecord(raw);
      return `<div class="trace-item">
        <strong>${htmlEscape(humanizeToken(row.cover_id, L.command))}</strong>
        <span class="trace-status">${htmlEscape(this._traceText(row.status))}</span>
        <small>${htmlEscape(this._traceText(row.reason_code))}</small>
      </div>`;
    }).join("") : `<div class="trace-item">
      <strong>${htmlEscape(L.command)}</strong>
      <span class="trace-status">${htmlEscape(this._traceText(command.status))}</span>
      <small>${htmlEscape(this._traceText(command.reason_code))}</small>
    </div>`;
    const explanation = traceAvailable
      ? `${this._traceText(winner.reason_code || commandReason)}${winnerEntry ? ` · ${this._traceText(asRecord(winnerEntry).resolution_reason_code)}` : ""}`
      : L.noTrace;
    const toolsAvailable = Boolean(simulate?.entity_id || previewButton?.entity_id);
    return `
      <section data-decision-trace><h3>${htmlEscape(L.whatNow)}</h3>
        ${traceAvailable ? `<div class="summary trace-summary">
          <div><small>${htmlEscape(L.mode)}</small><strong>${htmlEscape(this._modeText(winner.mode))}</strong></div>
          <div><small>${htmlEscape(L.target)}</small><strong>${htmlEscape(this._traceTarget(winner.target, L))}</strong></div>
          <div><small>${htmlEscape(L.command)}</small><strong>${htmlEscape(this._traceText(commandStatus))}</strong></div>
        </div>` : `<div class="empty">${htmlEscape(L.noTrace)}</div>`}
      </section>
      <section data-decision-explanation><h3>${htmlEscape(L.whyNow)}</h3><div class="muted">${htmlEscape(explanation)}</div></section>
      ${toolsAvailable ? `<section class="collapsible" data-test-tools>
        <button class="collapsible-toggle" data-collapse-toggle="tools" aria-expanded="${this._toolsOpen}"><span>${htmlEscape(L.tools)}</span>${iconBox(this._toolsOpen ? "mdi:chevron-up" : "mdi:chevron-down", "action-icon")}</button>
        <div class="collapsible-content" ${this._toolsOpen ? "" : "hidden"}>
          <p class="muted">${htmlEscape(L.toolsHint)}</p>
          ${this._toolStatus ? `<div class="warning" data-tool-status>${htmlEscape(this._toolStatus)}</div>` : ""}
          <section data-simulation><h3>${htmlEscape(L.simulation)}</h3>
            ${simulationHtml}
            ${simulate?.entity_id ? `<div class="actions"><button data-tool-press="${htmlEscape(simulate.entity_id)}">${iconBox("mdi:flask-outline", "action-icon")}${htmlEscape(L.runSimulation)}</button></div>` : ""}
          </section>
          <section data-day-preview><h3>${htmlEscape(L.dayPreview)}</h3>
            ${Object.keys(preview).length ? `<div class="summary trace-summary"><div><small>${htmlEscape(L.transitions)}</small><strong>${htmlEscape(transitions.length)}</strong></div><div><small>${htmlEscape(L.dayPreview)}</small><strong>${htmlEscape(preview.day || "–")}</strong></div></div>` : ""}
            <div class="trace-list">${transitionHtml}</div>
            ${previewButton?.entity_id ? `<div class="actions preview-actions"><label class="preview-date"><span>${htmlEscape(L.previewDate)}</span><input type="date" data-preview-date value="${htmlEscape(previewDate)}"></label><button data-preview-day data-preview-room="${htmlEscape(roomId)}" data-preview-entry="${htmlEscape(entryId)}">${iconBox("mdi:calendar-search-outline", "action-icon")}${htmlEscape(L.previewDay)}</button></div>` : ""}
          </section>
        </div>
      </section>` : ""}
      <section class="collapsible" data-technical-details>
        <button class="collapsible-toggle" data-collapse-toggle="technical" aria-expanded="${this._technicalOpen}"><span>${htmlEscape(L.technical)}</span>${iconBox(this._technicalOpen ? "mdi:chevron-up" : "mdi:chevron-down", "action-icon")}</button>
        <div class="collapsible-content" ${this._technicalOpen ? "" : "hidden"}>
          <section data-input-quality><h3>${htmlEscape(L.inputQuality)}</h3><div class="trace-list">${inputHtml}</div></section>
          <section data-command-results><h3>${htmlEscape(L.command)}</h3><div class="trace-list">${commandHtml}</div></section>
          <section data-rejected-candidates><h3>${htmlEscape(L.rejected)}</h3><div class="trace-list">${rejectedHtml}</div></section>
          <section data-protected-zones><h3>${htmlEscape(`${L.protectedZones} · ${L.currentCalculation}`)}</h3><div class="trace-list">${zoneHtml}</div></section>
        </div>
      </section>`;
  }

  _control(key) {
    return this._controls.find((state) => state?.attributes?.smart_shading_control_key === key);
  }

  async _callEntity(entityId, { testTool = false } = {}) {
    if (!this._hass || !entityId) return false;
    const domain = entityId.split(".")[0];
    const service = domain === "button" ? "press" : domain === "switch" ? "toggle" : null;
    if (!service) return false;
    if (testTool) {
      this._toolsOpen = true;
      this._toolStatus = this._labels().toolRunning;
      this._render();
    }
    try {
      await this._hass.callService(domain, service, { entity_id: entityId });
      if (testTool) {
        this._toolStatus = this._labels().toolReady;
        this._render();
      }
      return true;
    } catch (_error) {
      if (testTool) {
        this._toolStatus = this._labels().toolFailed;
        this._render();
      }
      return false;
    }
  }

  async _previewDay(roomId, entryId, date) {
    const selected = /^\d{4}-\d{2}-\d{2}$/.test(String(date || ""))
      ? String(date)
      : localDateKey();
    if (!this._hass?.callService || !roomId) {
      this._toolsOpen = true;
      this._toolStatus = this._labels().toolUnavailable;
      this._render();
      return false;
    }
    const request = { room_id: roomId, date: selected };
    if (entryId) request.entry_id = entryId;
    this._toolsOpen = true;
    this._toolStatus = this._labels().toolRunning;
    this._render();
    try {
      await this._hass.callService("smart_shading", "preview_day", request);
      this._toolStatus = this._labels().toolReady;
      this._render();
      return true;
    } catch (_error) {
      this._toolStatus = this._labels().toolUnavailable;
      this._render();
      return false;
    }
  }

  _more(entityId) {
    if (!entityId) return;
    if (this._owner?._more) this._owner._more(entityId);
    else {
      this.dispatchEvent(new CustomEvent("hass-more-info", { bubbles: true, composed: true, detail: { entityId } }));
    }
  }

  _openNightSource(entityId) {
    if (this._owner?._openNightSource) return this._owner._openNightSource(entityId);
    this._more(entityId);
    return Promise.resolve();
  }

  _formatDate(value) {
    if (!value) return "–";
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return "–";
    return new Intl.DateTimeFormat(undefined, {
      day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit",
    }).format(date);
  }

  _render() {
    const existingDialog = this.shadowRoot?.querySelector?.(".dialog");
    if (!this.shadowRoot || !this._roomState) return;
    this._renderCount += 1;
    this.dataset.renderCount = String(this._renderCount);
    const L = this._labels();
    const attrs = this._roomState.attributes || {};
    const configuration = attrs.configuration || {};
    const targets = asArray(attrs.targets);
    const sectors = asArray(attrs.sector_statuses);
    const events = asArray(attrs.diagnostic_events).slice().reverse();
    const covers = asArray(configuration.sectors).flatMap((sector) =>
      asArray(sector.layers).flatMap((layer) => asArray(layer.covers).map((cover) => ({ ...cover, layer, sector })))
    );
    const targetByEntity = new Map(targets.map((target) => [target.entity_id, target]));
    const coverPauseByEntity = new Map(asArray(attrs.cover_pauses).map((item) => [item.entity_id, item]));
    const roomName = cleanDisplayName(attrs.name, "Smart Shading");
    const pause = this._control("pause_default");
    const resume = this._control("resume");
    const evaluate = this._control("evaluate");
    const exportLog = this._control("export_room_diagnostics") || this._control("export_diagnostics");
    const master = this._control("manual_master");
    const configuredNightSource = attrs.night_source === "entity" ? attrs.night_entity : "";
    const nightSource = configuredNightSource && this._hass?.states?.[configuredNightSource]
      ? configuredNightSource
      : "";
    const nightSourceLabel = String(nightSource || "").startsWith("schedule.") ? L.openSchedule : L.openSource;
    const nightHtml = attrs.night_enabled ? `
      <section><h3>${htmlEscape(L.night)}</h3><div class="summary">
        <div><small>${htmlEscape(L.mode)}</small><strong>${htmlEscape(attrs.night_blocked ? L.blocked : attrs.night_active ? L.active : L.inactive)}</strong></div>
        <div><small>${htmlEscape(L.source)}</small><strong>${htmlEscape(attrs.night_source || "–")}</strong></div>
        <div><small>${htmlEscape(L.sourceState)}</small><strong>${htmlEscape(attrs.night_source_state || "–")}</strong></div>
        <div><small>${htmlEscape(L.nextTransition)}</small><strong>${htmlEscape(this._formatDate(attrs.night_next_transition))}</strong></div>
        <div><small>${htmlEscape(L.morningWindow)}</small><strong>${htmlEscape(attrs.night_morning_transition_minutes ?? 0)} min</strong></div>
        <div><small>${htmlEscape(L.eveningWindow)}</small><strong>${htmlEscape(attrs.night_evening_transition_minutes ?? 0)} min</strong></div>
      </div>
      ${nightSource ? `<div class="actions"><button data-night-source="${htmlEscape(nightSource)}">${iconBox("mdi:calendar-clock", "action-icon")}${htmlEscape(nightSourceLabel)}</button></div>` : ""}
      ${attrs.night_reason ? `<div class="muted">${htmlEscape(localizedReason(attrs.night_reason, this._hass?.language))}</div>` : ""}
      </section>` : "";

    const sectorHtml = sectors.map((sector) => {
      const settings = sector.sun_settings || {};
      const raw = sector.lux_raw_state == null ? "–" : String(sector.lux_raw_state);
      const parsed = sector.lux == null ? "–" : `${Math.round(Number(sector.lux))} lx`;
      const pending = sector.pending_until ? this._formatDate(sector.pending_until) : "–";
      return `
      <div class="data-card">
        <div class="data-title"><span>${htmlEscape(cleanDisplayName(sector.name, sector.short || "Sektor"))}</span><strong>${htmlEscape(this._statusText(sector.status))}</strong></div>
        <div class="muted">${htmlEscape(localizedReason(sector.reason, this._hass?.language, L.noReason))}</div>
        <div class="facts">
          <span>☀ ${sector.sun_presence ? "ON" : "OFF"}</span>
          <span>${htmlEscape(parsed)}</span>
          <span>${sector.geometry_active ? "Az/El ✓" : "Az/El –"}</span>
        </div>
      </div>`;
    }).join("");

    const coverHtml = covers.map((cover, index) => {
      const fallback = `${L.covers} ${index + 1}`;
      const name = cleanDisplayName(cover.name, fallback);
      const state = this._hass?.states?.[cover.entity];
      const currentPosition = asNumber(state?.attributes?.current_position, null);
      const currentTilt = profileSupportsTilt(cover.layer?.profile)
        ? asNumber(state?.attributes?.current_tilt_position, null)
        : null;
      const target = targetByEntity.get(cover.entity) || {};
      const openingLimit = target.maximum_opening || {};
      const localPause = coverPauseByEntity.get(cover.entity) || {};
      const suppressionText = asArray(target.suppressed).map((item) => this._suppressionText(item));
      return `
        <div class="data-card ${localPause.active ? "pause-card" : ""}">
          <div class="data-title"><span>${htmlEscape(name)}</span><strong>${htmlEscape(localPause.active ? L.paused : this._modeText(target.mode || this._roomState.state, cover.layer?.profile))}</strong></div>
          <div class="facts">
            <span>${L.current}: ${currentPosition == null ? "–" : `${Math.round(currentPosition)}%`}</span>
            <span>${L.tilt}: ${currentTilt == null ? "–" : `${Math.round(currentTilt)}%`}</span>
            <span>${L.target}: ${target.position == null ? "–" : `${Math.round(Number(target.position))}%`}${target.tilt == null ? "" : ` / ${Math.round(Number(target.tilt))}%`}</span>
          </div>
          ${openingLimit.enabled ? `<div class="muted">${htmlEscape(`${L.normalTarget}: ${Math.round(Number(target.ordinary_position))}% · ${L.openingLimit}: ${Math.round(Number(openingLimit.limit))}% · ${L.effectiveTarget}: ${Math.round(Number(openingLimit.effective_position))}%`)}</div>` : ""}
          ${localPause.active ? `<div class="warning">${htmlEscape(L.pauseUntil)} ${htmlEscape(this._formatDate(localPause.until))}</div>` : ""}
          ${suppressionText.length ? `<div class="warning">${htmlEscape(suppressionText.join(" · "))}</div>` : ""}
        </div>`;
    }).join("");

    const eventHtml = events.length ? events.map((event) => {
      const time = event.time || event.timestamp || event.created_at;
      const eventName = event.event || event.type || "event";
      return `<div class="event"><time>${htmlEscape(this._formatDate(time))}</time><strong>${htmlEscape(this._diagnosticEventTitle(eventName))}</strong><span>${htmlEscape(this._diagnosticEventDetails(event))}</span></div>`;
    }).join("") : `<div class="empty">${htmlEscape(L.noEvents)}</div>`;
    const decisionHtml = this._decisionTraceHtml(attrs, L);

    const mainHtml = `
      <section><h3>${htmlEscape(L.overview)}</h3><div class="summary">
        <div><small>${htmlEscape(L.mode)}</small><strong>${htmlEscape(this._modeText(this._roomState.state))}</strong></div>
        <div><small>${htmlEscape(L.reason)}</small><strong>${htmlEscape(localizedReason(attrs.reason, this._hass?.language, L.noReason))}</strong></div>
        <div><small>${htmlEscape(L.schedule)}</small><strong>${attrs.schedule_active === false ? L.inactive : L.active}</strong></div>
        <div><small>${htmlEscape(L.last)}</small><strong>${htmlEscape(this._formatDate(attrs.last_evaluation))}</strong></div>
      </div></section>
      ${decisionHtml}
      ${nightHtml}
      <section><h3>${htmlEscape(L.controls)}</h3><div class="actions">
        ${attrs.pause_mode && attrs.pause_mode !== "auto"
          ? (resume?.entity_id ? `<button data-press="${htmlEscape(resume.entity_id)}">${iconBox("mdi:play", "action-icon")}${htmlEscape(L.resume)}</button>` : "")
          : (pause?.entity_id ? `<button data-press="${htmlEscape(pause.entity_id)}">${iconBox("mdi:pause", "action-icon")}${htmlEscape(L.pause)}</button>` : "")}
        ${master?.entity_id ? `<button data-press="${htmlEscape(master.entity_id)}">${iconBox("mdi:hand-back-right", "action-icon")}${htmlEscape(L.master)}</button>` : ""}
      </div></section>
      <section><h3>${htmlEscape(L.sectors)}</h3><div class="grid">${sectorHtml || `<div class="empty">–</div>`}</div></section>
      <section><h3>${htmlEscape(L.covers)}</h3><div class="grid">${coverHtml || `<div class="empty">–</div>`}</div></section>
      <section class="collapsible" data-runtime-support>
        <button class="collapsible-toggle" data-collapse-toggle="runtimeSupport" aria-expanded="${this._runtimeSupportOpen}"><span>${htmlEscape(L.technical)}</span>${iconBox(this._runtimeSupportOpen ? "mdi:chevron-up" : "mdi:chevron-down", "action-icon")}</button>
        <div class="collapsible-content" ${this._runtimeSupportOpen ? "" : "hidden"}>
          <section><h3>${htmlEscape(L.diagnostics)}</h3><div>${eventHtml}</div></section>
          ${exportLog?.entity_id ? `<div class="actions"><button data-press="${htmlEscape(exportLog.entity_id)}">${iconBox("mdi:file-download-outline", "action-icon")}${htmlEscape(L.exportLog)}</button></div>` : ""}
        </div>
      </section>`;

    const dialogHtml = `
      <style>
        :host{position:fixed;inset:0;z-index:99999;display:block;font-family:var(--paper-font-body1_-_font-family,system-ui,sans-serif);color:var(--primary-text-color,#fff)}
        *{box-sizing:border-box}
        .backdrop{position:absolute;inset:0;background:rgba(0,0,0,.68);backdrop-filter:blur(5px)}
        .dialog{position:absolute;left:50%;top:50%;transform:translate(-50%,-50%);width:min(760px,calc(100vw - 24px));max-height:min(900px,calc(100vh - 24px));max-height:min(900px,calc(100dvh - 24px));overflow:auto;overflow-anchor:none;overscroll-behavior:contain;-webkit-overflow-scrolling:touch;scrollbar-gutter:stable;background:var(--ha-card-background,var(--card-background-color,#1d1d1d));border:1px solid rgba(255,255,255,.13);border-radius:24px;box-shadow:0 24px 80px rgba(0,0,0,.55)}
        header{position:sticky;top:0;z-index:2;display:flex;align-items:center;justify-content:space-between;gap:12px;padding:18px 20px;background:color-mix(in srgb,var(--ha-card-background,var(--card-background-color,#1d1d1d)) 94%,transparent);backdrop-filter:blur(12px);border-bottom:1px solid rgba(255,255,255,.08)}
        h2{margin:0;font-size:19px} .room{font-size:12px;opacity:.62;margin-top:3px}
        button{border:0;border-radius:999px;background:rgba(255,255,255,.09);color:inherit;min-width:34px;height:34px;cursor:pointer;font:inherit}button:hover{background:rgba(255,255,255,.16)}button[data-close]{display:grid;place-items:center;align-content:center;justify-content:center;padding:0;line-height:0}
        .icon-box{--icon-box-size:16px;--icon-size:14px;width:var(--icon-box-size);height:var(--icon-box-size);min-width:var(--icon-box-size);max-width:var(--icon-box-size);flex:0 0 var(--icon-box-size);display:grid;place-items:center;align-content:center;justify-content:center;align-self:center;justify-self:center;line-height:0;margin:0;padding:0}.icon-box>ha-icon{display:grid;place-items:center;width:var(--icon-size);height:var(--icon-size);min-width:var(--icon-size);max-width:var(--icon-size);--mdc-icon-size:var(--icon-size);line-height:0;margin:0;padding:0;position:static}.dialog-close-icon{--icon-box-size:18px;--icon-size:16px}.action-icon{--icon-box-size:16px;--icon-size:15px}
        main{padding:18px 20px 24px;display:grid;gap:18px}
        section{display:grid;gap:9px} h3{margin:0;font-size:14px;letter-spacing:.2px}
        .grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(240px,100%),1fr));gap:9px;min-width:0}
        .data-card{min-width:0;padding:12px;border-radius:15px;background:rgba(255,255,255,.055);border:1px solid rgba(255,255,255,.055)}
        .data-title{display:flex;gap:10px;justify-content:space-between;align-items:center;font-size:12px}.data-title span{font-weight:800;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.data-title strong{font-size:10px;opacity:.7;text-transform:uppercase;white-space:nowrap}
        .muted,.empty{font-size:11px;opacity:.62;line-height:1.35;margin-top:5px}.facts{display:flex;gap:8px;flex-wrap:wrap;font-size:11px;opacity:.78;margin-top:7px}.warning{font-size:10px;color:var(--warning-color,#ffbf69);margin-top:7px;overflow-wrap:anywhere}.details{display:grid;gap:3px;font-size:10px;opacity:.55;margin-top:8px}.pause-card{border-color:rgba(255,90,72,.35)}
        .trace-summary{grid-template-columns:repeat(auto-fit,minmax(135px,1fr))}.trace-list{display:grid;gap:5px}.trace-item{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:3px 8px;padding:8px 9px;border-radius:10px;background:rgba(255,255,255,.04);font-size:11px}.trace-item strong{min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.trace-item small{grid-column:1/-1;opacity:.58;overflow-wrap:anywhere}.trace-status{font-size:9px;line-height:1.25;opacity:.72;text-align:right;white-space:nowrap}.trace-status.ok{color:var(--success-color,#8be29a);opacity:1}.trace-status.warn{color:var(--warning-color,#ffbf69);opacity:1}
        .summary{display:grid;grid-template-columns:repeat(auto-fit,minmax(120px,1fr));gap:8px}.summary div{padding:11px;border-radius:14px;background:rgba(255,255,255,.055)}.summary small{display:block;opacity:.55;margin-bottom:4px}.summary strong{font-size:12px;overflow-wrap:anywhere}
        .actions{display:flex;gap:8px;flex-wrap:wrap}.actions button{height:34px;padding:0 12px;display:inline-flex;align-items:center;justify-content:center;gap:6px;font-size:12px;line-height:1}.preview-date{display:inline-flex;align-items:center;gap:6px;font-size:10px;opacity:.82}.preview-date input{min-height:34px;max-width:145px;border:1px solid rgba(255,255,255,.16);border-radius:10px;padding:0 8px;background:rgba(255,255,255,.06);color:inherit;font:inherit}.collapsible{gap:0;border:1px solid rgba(255,255,255,.08);border-radius:14px;overflow:hidden;background:rgba(255,255,255,.025)}.collapsible-toggle{width:100%;height:42px;padding:0 12px;border-radius:0;background:transparent;display:flex;align-items:center;justify-content:space-between;gap:8px;text-align:left;font-size:12px;font-weight:700}.collapsible-content{display:grid;gap:13px;padding:2px 12px 13px}.collapsible-content[hidden]{display:none}
        .event{display:grid;grid-template-columns:95px minmax(100px,170px) 1fr;gap:8px;padding:8px 0;border-bottom:1px solid rgba(255,255,255,.06);font-size:10px;align-items:start}.event time{opacity:.55}.event strong{font-size:10px}.event span{opacity:.66;overflow-wrap:anywhere}
        @media(max-width:560px){header,main{padding-left:14px;padding-right:14px}.event{grid-template-columns:1fr}.dialog{border-radius:18px}.summary{grid-template-columns:1fr 1fr}.actions{width:100%}.actions button{flex:1 1 auto}.facts{align-items:flex-start}}
      </style>
      <div class="backdrop" data-close></div>
      <article class="dialog" role="dialog" aria-modal="true" aria-label="${htmlEscape(L.title)}">
        <header>
          <div><h2>${htmlEscape(L.title)}</h2><div class="room">${htmlEscape(roomName)}</div></div>
          <button data-close title="${htmlEscape(L.close)}">${iconBox("mdi:close", "dialog-close-icon")}</button>
        </header>
        <main>${mainHtml}</main>
      </article>`;

    if (!existingDialog) updateStableMarkup(this.shadowRoot, dialogHtml);

    const dialog = this.shadowRoot.querySelector?.(".dialog");
    const main = this.shadowRoot.querySelector?.("main");
    const contentChanged = !existingDialog || this._mainHtml !== mainHtml;
    if (existingDialog && main && contentChanged) updateStableMarkup(main, mainHtml);
    if (contentChanged) {
      this._mainHtml = mainHtml;
      this._contentWriteCount += 1;
      this.dataset.contentWriteCount = String(this._contentWriteCount);
    }
  }
}

class SmartShadingV4Card extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._config = {};
    this._hass = null;
    this._selectedRoom = null;
    this._dialog = null;
    this._renderQueued = false;
    this._forceRender = false;
    this._renderCount = 0;
    this._lastRenderSignature = "";
    this._cardHtml = "";
    this.shadowRoot?.addEventListener?.("click", (event) => {
      const element = eventElement(event,
        "[data-more],[data-night-source],[data-press],[data-advanced]",
      );
      if (!element) return;
      if (element.dataset.more) {
        event.stopPropagation?.();
        this._more(element.dataset.more);
        return;
      }
      if (element.dataset.nightSource) {
        event.stopPropagation?.();
        this._openNightSource(element.dataset.nightSource);
        return;
      }
      if (element.dataset.press) {
        this._callEntity(element.dataset.press);
        return;
      }
      if (element.hasAttribute?.("data-advanced")) {
        const roomState = this._resolvedRoomState();
        if (roomState) {
          this._openAdvanced(
            roomState,
            this._controls(roomState),
            element,
          );
        }
      }
    });
  }

  static getStubConfig() {
    return { show_sun_track: true, show_covers: true, show_actions: true };
  }

  static async getConfigElement() {
    return document.createElement("smart-shading-card-editor");
  }

  setConfig(config = {}) {
    if (!config || typeof config !== "object") throw new Error("Invalid Smart Shading card configuration");
    this._config = {
      show_sun_track: true,
      show_covers: true,
      show_actions: true,
      ...config,
    };
    this._lastRenderSignature = "";
    this._queueRender(true);
  }

  set hass(hass) {
    this._hass = hass;
    this._queueRender(false);
    if (this._dialog?.isConnected) {
      const state = this._resolvedRoomState();
      if (state) this._dialog.update({ hass, roomState: state, controls: this._controls(state) });
    }
  }

  disconnectedCallback() {
    this._renderQueued = false;
    if (this._dialog) {
      this._dialog.close?.();
      this._dialog = null;
    }
  }

  getCardSize() { return 6; }

  getGridOptions() {
    return { columns: 6, min_columns: 6, max_columns: 12 };
  }

  _modeText(mode, profile = "") {
    const de = String(this._hass?.language || "en").toLowerCase().startsWith("de");
    if (mode === "open" && profile === "awning") return de ? "Eingefahren" : "Retracted";
    const values = de ? {
      safety: "Safety", heat: "Heat Protection", glare: "Blendschutz", solar: "Sonnenschutz",
      comfort: "Komfort", paused: "Pausiert", open: "Offen", idle: "Bereit",
      disabled: "Master aktiv", finished: "Für heute beendet", night: "Nacht",
    } : {
      safety: "Safety", heat: "Heat protection", glare: "Glare protection", solar: "Solar shading",
      comfort: "Comfort", paused: "Paused", open: "Open", idle: "Ready",
      disabled: "Master active", finished: "Finished today", night: "Night",
    };
    return values[mode] || String(mode || "–");
  }

  _viewSignature() {
    const roomState = this._resolvedRoomState();
    if (!roomState) {
      return JSON.stringify([
        this._config,
        this._hass?.language || "en",
        Boolean(this._hass),
      ]);
    }
    const attrs = roomState.attributes || {};
    const room = attrs.configuration || {};
    const entityIds = new Set([
      roomState.entity_id,
      attrs.sun_entity || room.sun_entity || "sun.sun",
      room.indoor_temperature,
      room.outdoor_temperature,
      attrs.night_entity,
      ...asArray(room.safety_blockers),
    ].filter(Boolean));
    asArray(room.sectors).forEach((sector) => {
      entityIds.add(sector.lux_sensor);
      entityIds.add(sector.sun_presence_entity);
      asArray(sector.layers).forEach((layer) => asArray(layer.covers).forEach((cover) => {
        entityIds.add(cover.entity);
        entityIds.add(cover.lock);
        entityIds.add(cover.window);
      }));
    });
    this._controls(roomState).forEach((control) => entityIds.add(control.entity_id));
    const states = [...entityIds].filter(Boolean).sort().map((entityId) => [
      entityId,
      visibleStateAttributes(this._hass?.states?.[entityId]),
    ]);
    try {
      return JSON.stringify([
        this._config,
        this._hass?.language || "en",
        roomState.state,
        cardRoomAttributes(attrs),
        states,
      ]);
    } catch (_error) {
      return `${roomState.entity_id}:${roomState.state}:${roomState.last_changed || ""}`;
    }
  }

  _queueRender(force = false) {
    this._forceRender = this._forceRender || force;
    if (this._renderQueued) return;
    const render = () => {
      this._renderQueued = false;
      const signature = this._viewSignature();
      if (!this._forceRender && signature === this._lastRenderSignature) return;
      this._forceRender = false;
      this._lastRenderSignature = signature;
      this._render();
    };
    if (this.isConnected && globalThis.requestAnimationFrame) {
      this._renderQueued = true;
      globalThis.requestAnimationFrame(render);
    } else {
      render();
    }
  }

  _labels() {
    const de = String(this._hass?.language || "en").toLowerCase().startsWith("de");
    return de ? {
      title: "Shading", room: "Raum", noEntity: "Smart-Shading-Raum auswählen", unavailable: "Smart-Shading-Status nicht verfügbar",
      noRoom: "Noch kein Raum eingerichtet", noCovers: "Noch keine Behänge zugeordnet", cover: "Behang", sector: "Sektor",
      safety: "Safety", heat: "Heat", night: "Nacht", glare: "Blendschutz", solar: "Sonnenschutz", comfort: "Komfort", paused: "Pause", open: "Offen", idle: "Bereit", disabled: "Aus", finished: "Fertig",
      retracted: "Eingefahren",
      normalTarget: "Normales Ziel", openingLimit: "Öffnungsgrenze", effectiveTarget: "Effektives Ziel",
      wind: "Wind", frost: "Frost", windows: "Fenster", sun: "Sonne", temp: "Temperatur", position: "Position", tilt: "Lamelle", manual: "Manuell", master: "Master",
      blocked: "Blockiert", pauseUntil: "Pausiert bis", schedule: "Zeitplan inaktiv", sunMissing: "Sonnenentität fehlt", advanced: "Details",
      pause: "Pausieren", resume: "Fortsetzen", evaluate: "Neu auswerten", copy: "Card-YAML kopieren", copied: "Kopiert",
      belowHorizon: "Nacht", outsideSector: "Außerhalb", waitingLux: "Wartet auf Sonne", waiting: "Wartet", active: "Aktiv", detected: "Sonne erkannt",
      automatic: "Automatik", manualOverride: "Manuelle Sperre", sunInSector: "Sonne im Sektor", sunOutsideSector: "Sonne außerhalb", nightSchedule: "Nachtzeitplan bearbeiten",
      sourceGeometry: "Sonnenposition", sourceBinary: "Sonnensensor", sourceLux: "Luxsensor", sourceWeather: "Wetter", sourceMixed: "Verschiedene Quellen",
      confirmed: "Sonne bestätigt", confirmationBlocked: "Sonne nicht bestätigt", geometryFallback: "Nur Sonnenposition", inactiveSignal: "Nicht aktiv", sourceUnavailable: "Gewählte Sonnenquelle nicht verfügbar", temperatureBlocked: "Temperatur zu niedrig",
      sunUnavailable: "Sonnenstatus nicht verfügbar",
      roomContext: "Raum", scheduleContext: "Zeitplan", overrideContext: "Override",
      decision: "Entscheidung", winner: "Gewinner", command: "Befehl", quality: "Datenqualität", protectedZones: "Schutzzonen",
      simulation: "Simulation", runSimulation: "Simulation ausführen", previewDay: "Tagvorschau berechnen", simulationActive: "Simulation aktiv",
    } : {
      title: "Shading", room: "Room", noEntity: "Select a Smart Shading room", unavailable: "Smart Shading status unavailable",
      noRoom: "No room configured", noCovers: "No covers assigned", cover: "Cover", sector: "Sector",
      safety: "Safety", heat: "Heat", night: "Night", glare: "Glare protection", solar: "Solar", comfort: "Comfort", paused: "Paused", open: "Open", idle: "Ready", disabled: "Off", finished: "Done",
      retracted: "Retracted",
      normalTarget: "Normal target", openingLimit: "Opening limit", effectiveTarget: "Effective target",
      wind: "Wind", frost: "Frost", windows: "Windows", sun: "Sun", temp: "Temperature", position: "Position", tilt: "Tilt", manual: "Manual", master: "Master",
      blocked: "Blocked", pauseUntil: "Paused until", schedule: "Schedule inactive", sunMissing: "Sun entity missing", advanced: "Details",
      pause: "Pause", resume: "Resume", evaluate: "Evaluate again", copy: "Copy card YAML", copied: "Copied",
      belowHorizon: "Night", outsideSector: "Outside", waitingLux: "Waiting for sun", waiting: "Waiting", active: "Active", detected: "Sun detected",
      automatic: "Automatic", manualOverride: "Manual Override", sunInSector: "Sun in sector", sunOutsideSector: "Sun outside sector", nightSchedule: "Edit night schedule",
      sourceGeometry: "Sun position", sourceBinary: "Sun sensor", sourceLux: "Lux sensor", sourceWeather: "Weather", sourceMixed: "Mixed sources",
      confirmed: "Sun confirmed", confirmationBlocked: "Sun not confirmed", geometryFallback: "Sun position only", inactiveSignal: "Inactive", sourceUnavailable: "Selected sun source unavailable", temperatureBlocked: "Temperature too low",
      sunUnavailable: "Sun status unavailable",
      roomContext: "Room", scheduleContext: "Schedule", overrideContext: "Override",
      decision: "Decision", winner: "Winner", command: "Command", quality: "Input quality", protectedZones: "Protected zones",
      simulation: "Simulation", runSimulation: "Run simulation", previewDay: "Calculate day preview", simulationActive: "Simulation active",
    };
  }

  _roomStates(entryId) {
    if (!this._hass || !entryId) return [];
    return Object.values(this._hass.states || {}).filter((state) =>
      state?.entity_id?.startsWith("sensor.") &&
      state?.attributes?.smart_shading_entry_id === entryId &&
      Boolean(state?.attributes?.smart_shading_room_id) &&
      Boolean(state?.attributes?.configuration)
    );
  }

  _resolvedRoomState() {
    const configured = this._config?.entity;
    if (!configured || !this._hass?.states) return null;
    const state = this._hass.states[configured];
    if (!state) return null;
    if (state.attributes?.configuration) return state;
    const entryId = state.attributes?.smart_shading_entry_id;
    const rooms = this._roomStates(entryId);
    if (!rooms.length) return null;
    if (this._selectedRoom && rooms.some((room) => room.entity_id === this._selectedRoom)) return this._hass.states[this._selectedRoom];
    this._selectedRoom = rooms[0].entity_id;
    return rooms[0];
  }

  _controls(roomState) {
    if (!this._hass || !roomState) return [];
    const entryId = roomState.attributes?.smart_shading_entry_id;
    const roomId = roomState.attributes?.smart_shading_room_id;
    const allowed = new Set(["number", "select", "switch", "button", "binary_sensor"]);
    return Object.values(this._hass.states || {}).filter((state) => {
      const domain = String(state?.entity_id || "").split(".")[0];
      return state?.attributes?.smart_shading_entry_id === entryId && state?.attributes?.smart_shading_room_id === roomId && allowed.has(domain);
    });
  }

  _control(controls, key) { return controls.find((state) => state?.attributes?.smart_shading_control_key === key); }
  _state(entityId) { return entityId ? this._hass?.states?.[entityId] : null; }

  _displayName(entityId, configuredName, fallback) {
    const configured = cleanDisplayName(configuredName, "");
    if (configured) return configured;
    const friendly = cleanDisplayName(this._state(entityId)?.attributes?.friendly_name, "");
    return friendly || fallback;
  }

  _short(value, fallback) {
    const text = String(value || "").trim().toUpperCase().replace(/\s+/g, "");
    return text ? text.slice(0, 4) : fallback;
  }

  _modeInfo(mode, L) {
    return ({
      safety: ["mdi:shield-alert", L.safety, "danger"], heat: ["mdi:shield-sun", L.heat, "heat"],
      night: ["mdi:weather-night", L.night, "night"],
      glare: ["mdi:shield-sun-outline", L.glare, "glare"],
      solar: ["mdi:weather-sunny-alert", L.solar, "solar"], comfort: ["mdi:sun-angle", L.comfort, "comfort"],
      paused: ["mdi:pause-circle", L.paused, "paused"], disabled: ["mdi:power", L.disabled, "disabled"],
      finished: ["mdi:calendar-check", L.finished, "done"], open: ["mdi:blinds-open", L.open, "open"],
      idle: ["mdi:blinds-horizontal", L.idle, "idle"],
    })[mode] || ["mdi:blinds-horizontal", L.idle, "idle"];
  }

  _importantMessage(roomState, L) {
    const attrs = roomState.attributes || {};
    const mode = roomState.state;
    if (mode === "safety") return localizedReason(attrs.reason, this._hass?.language, L.safety);
    if (mode === "heat") return localizedReason(attrs.reason, this._hass?.language, L.heat);
    if (mode === "paused") return attrs.pause_until ? `${L.pauseUntil} ${this._formatDate(attrs.pause_until)}` : L.paused;
    if (mode === "disabled") return L.disabled;
    if (attrs.schedule_active === false) return localizedReason(attrs.schedule_reason, this._hass?.language, L.schedule);
    const sunState = this._state(attrs.sun_entity || "sun.sun");
    if (!sunState || ["unknown", "unavailable"].includes(sunState.state)) return L.sunMissing;
    return "";
  }

  _formatDate(value) {
    if (!value) return "–";
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return "–";
    return new Intl.DateTimeFormat(undefined, { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" }).format(date);
  }

  _more(entityId) {
    if (!entityId) return;
    this.dispatchEvent(new CustomEvent("hass-more-info", { bubbles: true, composed: true, detail: { entityId } }));
  }

  async _openNightSource(entityId) {
    if (!entityId?.startsWith("schedule.") || !this._hass?.callWS) {
      this._more(entityId);
      return;
    }
    try {
      const entry = await this._hass.callWS({
        type: "config/entity_registry/get",
        entity_id: entityId,
      });
      const configEntryId = entry?.config_entry_id;
      if (!configEntryId || !window?.history?.pushState) throw new Error("Schedule helper route unavailable");
      window.history.pushState(null, "", `/config/helpers/edit/${configEntryId}`);
      window.dispatchEvent?.(new Event("location-changed"));
    } catch (_error) {
      this._more(entityId);
    }
  }

  _callEntity(entityId) {
    if (!entityId || !this._hass) return;
    const domain = entityId.split(".")[0];
    const service = domain === "button" ? "press" : domain === "switch" ? "toggle" : null;
    if (service) this._hass.callService(domain, service, { entity_id: entityId });
  }

  _copy(text, button) {
    navigator.clipboard?.writeText?.(text).then(() => {
      if (button) {
        const old = button.getAttribute("title");
        button.setAttribute("title", this._labels().copied);
        setTimeout(() => button.setAttribute("title", old || this._labels().copy), 1200);
      }
    });
  }

  _openAdvanced(roomState, controls, opener = null) {
    if (!this._dialog) this._dialog = document.createElement("smart-shading-dialog");
    this._dialog.open({ hass: this._hass, roomState, controls, owner: this, opener });
  }

  _sectorStatusText(status, L) {
    return ({
      shading_active: L.active, sun_detected: L.detected, waiting_for_lux: L.waitingLux,
      waiting_conditions: L.waiting, outside_sun_sector: L.outsideSector, sun_below_horizon: L.belowHorizon,
      schedule_blocked: L.blocked, paused: L.paused, heat: L.heat, safety: L.safety, disabled: L.disabled,
      night: L.night, night_blocked: L.blocked, night_transition_hold: L.waiting,
    })[status] || L.waiting;
  }

  _effectiveSectorActive(runtime) {
    if (typeof runtime?.effective_active === "boolean") return runtime.effective_active;
    return ["shading_active", "sun_detected"].includes(runtime?.status);
  }

  _sourceText(value, L) {
    const normalized = String(value || "").trim().toLowerCase();
    return ({
      binary: L.sourceBinary, "binary sensor": L.sourceBinary,
      lux: L.sourceLux, "lux sensor": L.sourceLux,
      weather: L.sourceWeather,
      geometry: L.sourceGeometry, "sun geometry": L.sourceGeometry,
      mixed: L.sourceMixed,
    })[normalized] || String(value || L.sourceGeometry);
  }

  _confirmationText(value, effectiveActive, sunAboveHorizon, L) {
    if (!sunAboveHorizon) return L.belowHorizon;
    return ({
      confirmed: effectiveActive ? L.sunInSector : L.confirmed,
      blocked: L.confirmationBlocked,
      geometry_fallback: effectiveActive ? L.sunInSector : L.geometryFallback,
      mixed: effectiveActive ? L.sunInSector : L.confirmationBlocked,
      inactive: L.inactiveSignal,
      unavailable: L.sourceUnavailable,
    })[value] || (effectiveActive ? L.sunInSector : L.sunOutsideSector);
  }

  _render() {
    if (!this.shadowRoot) return;
    this._renderCount += 1;
    this.dataset.renderCount = String(this._renderCount);
    const L = this._labels();
    if (!this._config?.entity) {
      const nextHtml = this._messageCard(L.noEntity);
      if (nextHtml !== this._cardHtml) {
        this._cardHtml = nextHtml;
        updateStableMarkup(this.shadowRoot, nextHtml);
      }
      return;
    }
    const roomState = this._resolvedRoomState();
    if (!roomState) {
      const nextHtml = this._messageCard(L.unavailable);
      if (nextHtml !== this._cardHtml) {
        this._cardHtml = nextHtml;
        updateStableMarkup(this.shadowRoot, nextHtml);
      }
      return;
    }

    const attrs = roomState.attributes || {};
    const advancedMode = attrs.smart_shading_layout === "detailed";
    const room = attrs.configuration || {};
    const controls = this._controls(roomState);
    const sectors = asArray(room.sectors);
    const sectorStatuses = new Map(asArray(attrs.sector_statuses).map((sector) => [sector.id, sector]));
    const covers = sectors.flatMap((sector) => asArray(sector.layers).flatMap((layer) =>
      asArray(layer.covers).map((cover) => ({ ...cover, sector, layer }))
    ));
    const mode = roomState.state || "idle";
    let [modeIcon, modeLabel, modeClass] = this._modeInfo(mode, L);
    if (
      mode === "open"
      && covers.length
      && covers.every((cover) => cover.layer?.profile === "awning")
    ) {
      modeIcon = "mdi:storefront-outline";
      modeLabel = L.retracted;
    }
    const activeSectorNames = asArray(attrs.active_sectors).filter(Boolean);
    const detailedModeLabel = attrs.manual_master_active
      ? `${L.manual} · ${L.overrideContext}`
      : mode === "paused"
        ? `${L.paused} · ${L.roomContext}`
        : mode === "night"
          ? `${L.night} · ${L.scheduleContext}`
          : mode === "safety"
            ? `${L.safety} · ${L.blocked}`
            : advancedMode && ["glare", "solar", "comfort"].includes(mode) && activeSectorNames.length
              ? `${modeLabel} · ${activeSectorNames.join(", ")}`
              : modeLabel;
    const roomName = cleanDisplayName(attrs.name || room.name, L.room);
    const temperatureState = this._state(room.indoor_temperature);
    const temperature = asNumber(temperatureState?.state, null);
    const temperatureSettings = attrs.temperature_settings || {};
    const heatThreshold = asNumber(temperatureSettings.heat_temperature ?? room.heat_temperature, 27);
    const normalThreshold = asNumber(
      temperatureSettings.normal_shading_temperature ?? room.normal_shading_temperature ?? room.comfort_temperature,
      23.5,
    );
    const temperatureClass = temperature == null ? "" : temperature >= heatThreshold ? "temp-hot" : temperature >= normalThreshold ? "temp-warm" : "temp-ok";
    const sunEntity = attrs.sun_entity || "sun.sun";
    const sunState = this._state(sunEntity);
    const azimuth = asNumber(sunState?.attributes?.azimuth, 0);
    const elevation = asNumber(sunState?.attributes?.elevation, 0);
    const important = this._importantMessage(roomState, L);
    const targets = asArray(attrs.targets);
    const targetByEntity = new Map(targets.map((target) => [target.entity_id, target]));
    const coverPauseByEntity = new Map(asArray(attrs.cover_pauses).map((item) => [item.entity_id, item]));
    const coverChips = covers.map((cover, index) => {
      const locked = cover.lock && this._state(cover.lock)?.state === "on";
      return `<button class="mini-part ${locked ? "bad" : "good"}" data-more="${htmlEscape(cover.lock || cover.entity)}" title="${htmlEscape(this._displayName(cover.entity, cover.name, `${L.cover} ${index + 1}`))}">${htmlEscape(this._short(cover.short, String(index + 1)))}</button>`;
    }).join("");

    const sectorChips = sectors.map((sector, index) => {
      const runtime = sectorStatuses.get(sector.id) || {};
      const active = this._effectiveSectorActive(runtime);
      return `<button class="mini-part ${active ? "sunny" : "neutral"}" data-more="${htmlEscape(runtime.sun_presence_entity_id || sunEntity)}" title="${htmlEscape(cleanDisplayName(sector.name, `${L.sector} ${index + 1}`))}">${htmlEscape(this._short(sector.short, String(index + 1)))}</button>`;
    }).join("");

    const safetyBlockers = asArray(room.safety_blockers);
    const safetyActive = safetyBlockers.some((entity) => this._state(entity)?.state === "on");
    const safetyChips = safetyBlockers.map((entity) => {
      const state = this._state(entity);
      const friendly = cleanDisplayName(state?.attributes?.friendly_name, L.safety);
      const token = `${friendly} ${state?.attributes?.device_class || ""}`.toLowerCase();
      const icon = token.includes("wind") ? "mdi:weather-windy" : token.includes("frost") || token.includes("cold") ? "mdi:snowflake-alert" : token.includes("rain") || token.includes("moist") ? "mdi:weather-pouring" : "mdi:shield-alert";
      const active = state?.state === "on";
      return `<button class="chip icon-only ${active ? "alert" : ""}" data-more="${htmlEscape(entity)}" title="${htmlEscape(friendly)}">${iconBox(icon, "chip-icon")}</button>`;
    }).join("");
    const windows = covers.filter((cover) => cover.window);
    const unsafeWindows = windows.filter((cover) => this._state(cover.window)?.state !== (cover.window_safe_state || "on"));
    const windowParts = windows.map((cover, index) => {
      const safe = this._state(cover.window)?.state === (cover.window_safe_state || "on");
      return `<button class="mini-part ${safe ? "good" : "bad"}" data-more="${htmlEscape(cover.window)}" title="${htmlEscape(this._displayName(cover.entity, cover.name, `${L.cover} ${index + 1}`))}">${htmlEscape(this._short(cover.short, String(index + 1)))}</button>`;
    }).join("");

    const sectorBars = sectors.map((sector, index) => {
      const start = asNumber(sector.azimuth_start, 0);
      const end = asNumber(sector.azimuth_end, 359);
      const runtime = sectorStatuses.get(sector.id) || {};
      const ready = this._effectiveSectorActive(runtime);
      const segments = start <= end ? [[start, end]] : [[start, 360], [0, end]];
      return segments.map(([from, to]) => {
        const left = clamp(from / 360 * 100, 0, 100);
        const width = clamp((to - from) / 360 * 100, 0, 100);
        return `<span class="sector-bar ${ready ? "ready" : ""}" style="left:${left}%;width:${width}%" title="${htmlEscape(cleanDisplayName(sector.name, `${L.sector} ${index + 1}`))}"></span>`;
      }).join("");
    }).join("");

    const sectorCards = sectors.map((sector, index) => {
      const runtime = sectorStatuses.get(sector.id) || {};
      const status = runtime.status || "outside_sun_sector";
      const active = this._effectiveSectorActive(runtime);
      const name = cleanDisplayName(sector.name, `${L.sector} ${index + 1}`);
      const range = `${Math.round(asNumber(sector.azimuth_start, 0))}°–${Math.round(asNumber(sector.azimuth_end, 359))}°`;
      const source = this._sourceText(runtime.confirmation_source, L);
      return `<button class="sector-card ${active ? "active" : ""}" data-more="${htmlEscape(runtime.sun_presence_entity_id || sunEntity)}">
        <span><strong>${htmlEscape(name)}</strong><small>${htmlEscape(`${range} · ${this._sectorStatusText(status, L)} · ${source}`)}</small></span>
        ${iconBox(active ? "mdi:weather-sunny" : "mdi:circle-outline", "sector-icon")}
      </button>`;
    }).join("");

    const coverRows = covers.map((cover, index) => {
      const state = this._state(cover.entity);
      const fallback = `${L.cover} ${index + 1}`;
      const name = this._displayName(cover.entity, cover.name, fallback);
      const rawPosition = asNumber(state?.attributes?.current_position, null);
      const position = rawPosition == null ? null : clamp(rawPosition, 0, 100);
      const tilt = profileSupportsTilt(cover.layer?.profile)
        ? asNumber(state?.attributes?.current_tilt_position, null)
        : null;
      const locked = cover.lock && this._state(cover.lock)?.state === "on";
      const unsafe = cover.window && this._state(cover.window)?.state !== (cover.window_safe_state || "on");
      const target = targetByEntity.get(cover.entity) || {};
      const targetMode = target.decision_mode || target.mode || roomState.state;
      const openingLimit = target.maximum_opening || {};
      const localPause = coverPauseByEntity.get(cover.entity) || {};
      const locallyPaused = Boolean(localPause.active);
      const roomPaused = attrs.pause_mode && attrs.pause_mode !== "auto";
      const manualMaster = attrs.manual_master_active;
      const rowClass = locked || unsafe || roomPaused || locallyPaused || manualMaster ? "warning" : "";
      const leadingIcon = manualMaster ? "mdi:hand-back-right" : (roomPaused || locallyPaused) ? "mdi:pause-circle" : locked ? "mdi:lock" : unsafe ? "mdi:window-open-variant" : profileIcon(cover.layer?.profile, state?.state === "closed");
      return `<div class="cover-row ${rowClass}">
        <button class="cover-head" data-more="${htmlEscape(cover.entity)}" title="${htmlEscape(locallyPaused ? `${L.pauseUntil} ${this._formatDate(localPause.until)}` : name)}">
          <span class="cover-name">${iconBox(leadingIcon, "cover-icon")}<strong>${htmlEscape(name)}</strong></span>
          <span class="values">${manualMaster ? `${L.master} · ` : (roomPaused || locallyPaused) ? `${L.paused} · ` : locked ? `${L.manual} · ` : ""}${position == null ? "–" : `${Math.round(position)}%`}${tilt == null ? "" : ` · ${L.tilt} ${Math.round(tilt)}%`}</span>
        </button>
        <div class="bar ${position == null ? "unknown" : ""}">${position == null ? "" : `<i style="width:${position}%"></i>`}</div>
        ${tilt == null ? "" : `<div class="bar tilt"><i style="width:${clamp(tilt, 0, 100)}%"></i></div>`}
        ${advancedMode && target.position != null ? `<div class="target-line"><strong>${htmlEscape(this._modeText(targetMode, cover.layer?.profile))}</strong> · ${openingLimit.enabled ? `${L.normalTarget} ${Math.round(Number(target.ordinary_position))}% · ${L.openingLimit} ${Math.round(Number(openingLimit.limit))}% · ${L.effectiveTarget} ${Math.round(Number(openingLimit.effective_position))}%` : `${L.position} ${Math.round(Number(target.position))}%${target.tilt == null ? "" : ` · ${L.tilt} ${Math.round(Number(target.tilt))}%`}`}</div>` : ""}
      </div>`;
    }).join("");

    const easyCoverRows = covers.map((cover, index) => {
      const state = this._state(cover.entity);
      const fallback = `${L.cover} ${index + 1}`;
      const name = this._displayName(cover.entity, cover.name, fallback);
      const rawPosition = asNumber(state?.attributes?.current_position, null);
      const position = rawPosition == null ? null : clamp(rawPosition, 0, 100);
      const coverIcon = attrs.manual_master_active
        ? "mdi:hand-back-right"
        : profileIcon(cover.layer?.profile, state?.state === "closed");
      return `<button class="easy-cover-row ${attrs.manual_master_active ? "manual" : ""}" data-more="${htmlEscape(cover.entity)}" title="${htmlEscape(name)}">
        ${iconBox(coverIcon, "easy-cover-icon")}
        <span class="easy-cover-name">${htmlEscape(name)}</span>
        <strong class="easy-cover-value">${position == null ? "–" : `${Math.round(position)}%`}</strong>
        <span class="easy-cover-progress ${position == null ? "unknown" : ""}" aria-hidden="true">${position == null ? "" : `<i style="width:${position}%"></i>`}</span>
      </button>`;
    }).join("");

    const anyLocalPause = asArray(attrs.cover_pauses).some((item) => item.active);
    const anyLock = covers.some((cover) => cover.lock && this._state(cover.lock)?.state === "on");
    const manualIntervention = Boolean(attrs.manual_master_active || anyLocalPause || anyLock);
    const runtimeSectors = asArray(attrs.sector_statuses);
    const effectiveSunActive = runtimeSectors.some((item) => this._effectiveSectorActive(item));
    const sunAvailable = Boolean(sunState && !["unknown", "unavailable"].includes(sunState.state));
    const sunAboveHorizon = sunAvailable && (sunState.state === "above_horizon" || elevation > 0);
    const sourceTypes = [...new Set(runtimeSectors.map((item) => item.confirmation_source).filter(Boolean))];
    const sourceSummary = attrs.easy_source_summary
      || (sourceTypes.length > 1 ? "mixed" : sourceTypes[0])
      || "geometry";
    const effectiveSourceLabel = this._sourceText(sourceSummary, L);
    const confirmationState = String(attrs.easy_confirmation_state || "");
    const temperatureCondition = attrs.outdoor_temperature_condition && typeof attrs.outdoor_temperature_condition === "object"
      ? attrs.outdoor_temperature_condition
      : {};
    const temperatureBlocked = temperatureCondition.enabled === true && temperatureCondition.passed === false;
    const easySunActive = sunAvailable && sunAboveHorizon && effectiveSunActive && !temperatureBlocked;
    const easySunLabel = !sunAvailable
      ? L.sunUnavailable
      : temperatureBlocked
      ? L.temperatureBlocked
      : this._confirmationText(confirmationState, easySunActive, sunAboveHorizon, L);
    const easySunIcon = !sunAvailable || confirmationState === "unavailable" ? "mdi:help-circle-outline" : !sunAboveHorizon ? "mdi:weather-night" : easySunActive ? "mdi:white-balance-sunny" : "mdi:weather-sunset";

    const pauseButton = this._control(controls, "pause_default");
    const resumeButton = this._control(controls, "resume");
    const evaluateButton = this._control(controls, "evaluate");
    const simulateButton = this._control(controls, "simulate");
    const previewButton = this._control(controls, "preview_day");
    const masterButton = this._control(controls, "manual_master");
    const paused = attrs.pause_mode && attrs.pause_mode !== "auto";
    const cardClass = htmlEscape(`${modeClass} ${temperatureClass} ${(advancedMode ? manualIntervention : attrs.manual_master_active) ? "manual" : ""} ${attrs.manual_master_active ? "master" : ""}`);

    const nextCardHtml = `
      <style>
        :host{display:block;width:100%;max-width:100%;min-width:0;overflow:visible;overflow-anchor:none;font-family:var(--paper-font-body1_-_font-family,system-ui,sans-serif);container-type:inline-size;container-name:shading-card}
        *{box-sizing:border-box;min-width:0}
        ha-card{display:block;width:100%;max-width:100%;min-width:0;overflow:hidden;border-radius:22px;border:1px solid rgba(255,255,255,.09);box-shadow:none;background:var(--ha-card-background,var(--card-background-color,#202020));color:var(--primary-text-color,#fff)}
        ha-card.danger{background:linear-gradient(135deg,rgba(255,67,57,.27),rgba(30,27,27,.96))} ha-card.heat{background:linear-gradient(135deg,rgba(255,94,65,.23),rgba(29,27,27,.96))}
        ha-card.glare{background:linear-gradient(135deg,rgba(255,197,61,.22),rgba(31,29,23,.97))} ha-card.solar{background:linear-gradient(135deg,rgba(255,154,65,.18),rgba(30,29,27,.97))} ha-card.comfort{background:linear-gradient(135deg,rgba(80,200,115,.16),rgba(24,34,28,.97))}
        ha-card.temp-ok.open,ha-card.temp-ok.idle{background:linear-gradient(135deg,rgba(55,190,105,.13),rgba(25,32,28,.97))} ha-card.temp-warm.open,ha-card.temp-warm.idle{background:linear-gradient(135deg,rgba(255,164,65,.14),rgba(33,29,25,.97))} ha-card.temp-hot{background:linear-gradient(135deg,rgba(255,74,56,.24),rgba(35,25,25,.97))}
        ha-card.paused,ha-card.muted{background:linear-gradient(135deg,rgba(80,120,190,.18),rgba(24,28,36,.97))} ha-card.disabled,ha-card.master:not(.danger):not(.heat){background:linear-gradient(135deg,rgba(185,55,55,.28),rgba(38,22,22,.98))} ha-card.manual:not(.paused):not(.disabled):not(.danger):not(.heat){background:linear-gradient(135deg,rgba(190,62,54,.20),rgba(37,24,24,.97))}
        .icon-box{--icon-box-size:18px;--icon-size:16px;width:var(--icon-box-size);height:var(--icon-box-size);min-width:var(--icon-box-size);flex:0 0 var(--icon-box-size);display:grid;place-items:center;align-content:center;justify-content:center;align-self:center;justify-self:center;vertical-align:middle;line-height:0;margin:0;padding:0;overflow:visible;transform-origin:center}.icon-box>ha-icon{display:grid;place-items:center;width:var(--icon-size);height:var(--icon-size);min-width:var(--icon-size);max-width:var(--icon-size);--mdc-icon-size:var(--icon-size);line-height:0;margin:0;padding:0;transform:none;position:static}.mode-icon{--icon-box-size:16px;--icon-size:14px}.chip-icon{--icon-box-size:14px;--icon-size:12px}.sector-icon{--icon-box-size:18px;--icon-size:14px;opacity:.7}.cover-icon{--icon-box-size:14px;--icon-size:12px}.action-icon{--icon-box-size:18px;--icon-size:16px}.advanced-icon{--icon-box-size:17px;--icon-size:15px}.easy-status-icon{--icon-box-size:18px;--icon-size:16px}.easy-sun-icon{--icon-box-size:30px;--icon-size:23px}.easy-cover-icon{--icon-box-size:24px;--icon-size:18px}
        .wrap{width:100%;padding:16px;display:grid;gap:11px;overflow:hidden}
        .header{display:flex;justify-content:space-between;align-items:flex-start;gap:12px}.heading{flex:1;overflow:hidden}.title{font-size:18px;font-weight:850;line-height:1.08}.room-name{font-size:11px;opacity:.56;margin-top:4px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.important{font-size:11px;opacity:.72;margin-top:4px;line-height:1.3;overflow-wrap:anywhere}
        .mode{display:inline-flex;align-items:center;justify-content:center;gap:6px;padding:6px 10px;border-radius:999px;background:rgba(255,255,255,.10);font-size:10px;font-weight:900;text-transform:uppercase;white-space:nowrap;line-height:1}.danger .mode .mode-icon,.heat .mode .mode-icon,.paused .mode .mode-icon,.disabled .mode .mode-icon,.manual .mode .mode-icon,.active-master .icon-box,.sector-card.active .sector-icon,.cover-row.warning .cover-icon,.easy-cover-row.manual .easy-cover-icon,.calm-pulse{--pulse-transform:translateZ(0);animation:calmPulse 4.2s ease-in-out infinite;transform-origin:center}.sun-dot.calm-pulse{--pulse-transform:translate(-50%,-50%)}@keyframes calmPulse{0%,100%{opacity:.76;transform:var(--pulse-transform) scale(.98)}50%{opacity:1;transform:var(--pulse-transform) scale(1.045)}}
        .chips{display:flex;flex-wrap:wrap;gap:6px}.chip{height:26px;display:inline-flex;align-items:center;justify-content:center;gap:5px;padding:3px 7px;border:0;border-radius:999px;background:rgba(255,255,255,.065);color:inherit;font-size:10px;line-height:1;cursor:pointer}.chip.icon-only{width:26px;padding:0}.parts{display:inline-flex;align-items:center;gap:2px}.mini-part{min-width:19px;height:18px;border:0;padding:0 4px;border-radius:999px;color:inherit;font-size:9px;font-weight:900;line-height:1;cursor:pointer}.mini-part.good{background:rgba(130,220,150,.20)}.mini-part.bad{background:rgba(255,85,70,.38)}.mini-part.sunny{background:rgba(255,196,78,.28)}.mini-part.neutral{background:rgba(255,255,255,.07);opacity:.56}.chip.alert{background:rgba(255,80,66,.19)}
        .sunbox{padding:10px 12px;border-radius:16px;background:rgba(255,255,255,.047);overflow:hidden}.sun-title{display:flex;justify-content:space-between;gap:10px;font-size:11px;font-weight:750}.sun-title span:last-child{font-weight:500;opacity:.55;white-space:nowrap}.track{position:relative;height:31px;margin:6px 0}.track:before{content:"";position:absolute;left:0;right:0;top:50%;height:4px;transform:translateY(-50%);border-radius:99px;background:rgba(255,255,255,.11)}.sector-bar{position:absolute;top:50%;height:7px;transform:translateY(-50%);border-radius:99px;background:rgba(255,183,76,.24)}.sector-bar.ready{height:9px;background:rgba(255,185,72,.55)}.sun-dot{position:absolute;left:${clamp(azimuth / 360 * 100,0,100)}%;top:50%;width:14px;height:14px;transform:translate(-50%,-50%);border-radius:50%;background:#ffe08c;box-shadow:0 0 14px rgba(255,200,75,.35)}.track-labels{display:flex;justify-content:space-between;font-size:9px;opacity:.38}
        .sectors{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(118px,100%),1fr));gap:7px}.sector-card{border:0;border-radius:14px;background:rgba(255,255,255,.047);color:inherit;padding:9px 10px;display:flex;justify-content:space-between;align-items:center;gap:7px;text-align:left;cursor:pointer}.sector-card.active{background:rgba(255,188,72,.12)}.sector-card strong{display:block;font-size:11px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.sector-card small{display:block;font-size:9px;opacity:.57;margin-top:2px}
        .covers{display:grid;gap:7px}.cover-row{padding:7px;border-radius:12px;background:rgba(255,255,255,.018)}.cover-row.warning{background:rgba(255,78,65,.09)}.cover-head{width:100%;border:0;background:none;color:inherit;padding:0;display:flex;align-items:center;justify-content:space-between;gap:9px;cursor:pointer;text-align:left}.cover-name{display:flex;align-items:center;gap:5px;overflow:hidden}.cover-name strong{font-size:11px;font-weight:700;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.values{font-size:10px;opacity:.70;white-space:nowrap;flex:none}.bar{height:5px;border-radius:99px;background:rgba(255,255,255,.10);overflow:hidden;margin-top:5px}.bar.unknown:after{content:"";display:block;width:100%;height:100%;background:rgba(255,255,255,.04)}.bar i{display:block;height:100%;border-radius:inherit;background:rgba(255,255,255,.62)}.bar.tilt{height:3px;margin-top:3px}.bar.tilt i{background:rgba(255,204,102,.58)}.warning .bar i{background:rgba(255,102,87,.78)}.target-line{font-size:9px;opacity:.58;margin-top:4px;overflow-wrap:anywhere}.target-line strong{font-weight:750;opacity:1}
        .footer{display:flex;align-items:center;justify-content:flex-end;gap:8px;padding-top:2px}.actions{display:flex;align-items:center;gap:6px;margin-left:auto}.round{width:36px;height:36px;border:0;border-radius:50%;display:grid;place-items:center;align-content:center;justify-content:center;background:rgba(255,255,255,.075);color:inherit;cursor:pointer;padding:0;line-height:0}.round:hover{background:rgba(255,255,255,.14)}.round.active-master{background:rgba(255,70,60,.34)}.advanced-button{width:auto;border-radius:999px;padding:0 11px;gap:6px;display:flex;align-items:center;justify-content:center;font-size:10px;line-height:1}
        .easy-wrap{width:100%;padding:16px;display:grid;gap:12px;overflow:hidden}.easy-header{display:flex;align-items:flex-start;justify-content:space-between;gap:12px}.easy-brand{font-size:9px;font-weight:850;letter-spacing:.12em;text-transform:uppercase;opacity:.45}.easy-room{margin-top:3px;font-size:19px;font-weight:850;line-height:1.08;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.easy-status{height:30px;max-width:48%;display:inline-flex;align-items:center;justify-content:center;gap:6px;padding:0 10px;border-radius:999px;background:rgba(255,255,255,.085);font-size:10px;font-weight:850;line-height:1;white-space:nowrap}.easy-status span:last-child{overflow:hidden;text-overflow:ellipsis}.master .easy-status{background:rgba(255,70,60,.28)}
        .easy-sun{width:100%;border:0;border-radius:17px;padding:11px 12px 9px;background:rgba(255,255,255,.048);color:inherit;display:grid;gap:3px;text-align:left;cursor:pointer}.easy-sun-head{display:flex;align-items:center;gap:9px}.easy-sun-copy{display:grid;gap:1px}.easy-sun-copy small{font-size:9px;text-transform:uppercase;letter-spacing:.08em;opacity:.48}.easy-sun-copy strong{font-size:12px}.easy-track{height:23px;margin:2px 0 0}.easy-track .sector-bar{height:6px}.easy-track .sector-bar.ready{height:8px}.easy-track .sun-dot{width:13px;height:13px}
        .easy-covers{display:grid;gap:6px}.easy-cover-row{position:relative;width:100%;min-height:43px;border:0;border-radius:13px;padding:8px 10px 10px;display:grid;grid-template-columns:24px minmax(0,1fr) auto;grid-template-rows:auto 3px;align-items:center;gap:7px 9px;background:rgba(255,255,255,.035);color:inherit;text-align:left;cursor:pointer}.easy-cover-row.manual{background:rgba(255,76,63,.12)}.easy-cover-name{font-size:11px;font-weight:720;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.easy-cover-value{font-size:11px;opacity:.72}.easy-cover-progress{grid-column:2/4;width:100%;height:3px;border-radius:99px;background:rgba(255,255,255,.09);overflow:hidden}.easy-cover-progress.unknown{background:rgba(255,255,255,.04)}.easy-cover-progress i{display:block;height:100%;border-radius:inherit;background:rgba(255,255,255,.56)}.easy-cover-row.manual .easy-cover-progress i{background:rgba(255,104,88,.80)}
        .easy-actions{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:7px}.easy-action{height:38px;border:0;border-radius:13px;padding:0 11px;display:inline-flex;align-items:center;justify-content:center;gap:7px;background:rgba(255,255,255,.07);color:inherit;font-size:10px;font-weight:760;line-height:1;cursor:pointer}.easy-action:only-child{grid-column:1/-1}.easy-action.active-master{background:rgba(255,70,60,.28)}
        .message{padding:18px;font-size:13px;opacity:.75}
        @container shading-card (max-width:480px){.wrap,.easy-wrap{padding:13px}.values{font-size:9px}.mode{max-width:52%;font-size:9px}.mode span:last-child{overflow:hidden;text-overflow:ellipsis}.advanced-button span:last-child{display:none}.advanced-button{width:36px;padding:0;justify-content:center}.easy-status{max-width:52%;font-size:9px}.easy-action{padding:0 8px}.easy-action span:last-child{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}}
        @media(max-width:480px){.wrap,.easy-wrap{padding:13px}.values{font-size:9px}.advanced-button span:last-child{display:none}.advanced-button{width:36px;padding:0}}
        @media(prefers-reduced-motion:reduce){.calm-pulse,.mode-icon,.active-master .icon-box,.sector-card.active .sector-icon,.cover-row.warning .cover-icon,.easy-cover-row.manual .easy-cover-icon{animation:none!important}}
      </style>
      ${advancedMode ? `<ha-card data-card-mode="advanced" class="${cardClass}">
        <div class="wrap" data-advanced-layout>
          <div class="header">
            <div class="heading"><div class="title">${htmlEscape(this._config.title || L.title)}</div><div class="room-name">${htmlEscape(roomName)}</div>${important ? `<div class="important">${htmlEscape(important)}</div>` : ""}</div>
            <div class="mode">${iconBox(modeIcon, "mode-icon")}<span>${htmlEscape(detailedModeLabel)}</span></div>
          </div>
          <div class="chips">
            ${covers.length ? `<span class="chip">${iconBox("mdi:autorenew", "chip-icon")}<span class="parts">${coverChips}</span></span>` : ""}
            ${safetyChips}
            ${windows.length ? `<span class="chip ${unsafeWindows.length ? "alert" : ""}">${iconBox("mdi:window-closed-variant", "chip-icon")}<span class="parts">${windowParts}</span></span>` : ""}
            ${sectors.length ? `<span class="chip">${iconBox("mdi:white-balance-sunny", "chip-icon")}<span class="parts">${sectorChips}</span></span>` : ""}
            ${temperature != null ? `<button class="chip" data-more="${htmlEscape(room.indoor_temperature || "")}">${iconBox("mdi:thermometer", "chip-icon")}${temperature.toFixed(1)}°</button>` : ""}
          </div>
          ${this._config.show_sun_track !== false && sectors.length ? `<button class="sunbox" data-more="${htmlEscape(sunEntity)}" style="border:0;color:inherit;text-align:left;width:100%;cursor:pointer"><div class="sun-title"><span>${htmlEscape(`${L.sun} · ${effectiveSourceLabel}`)}</span><span>${sunAvailable ? `Az ${Math.round(azimuth)}° · El ${Math.round(elevation)}°` : htmlEscape(L.sunUnavailable)}</span></div><div class="track">${sectorBars}${sunAvailable ? `<span class="sun-dot ${effectiveSunActive ? "calm-pulse" : ""}"></span>` : ""}</div><div class="track-labels"><span>0°</span><span>180°</span><span>360°</span></div></button>` : ""}
          ${sectors.length ? `<div class="sectors" data-advanced-sectors>${sectorCards}</div>` : ""}
          ${this._config.show_covers !== false ? `<div class="covers">${coverRows || `<div class="message">${htmlEscape(L.noCovers)}</div>`}</div>` : ""}
          <div class="footer"><div class="actions">
            ${this._config.show_actions !== false ? `${paused
              ? (resumeButton?.entity_id ? `<button class="round" data-press="${htmlEscape(resumeButton.entity_id)}" title="${htmlEscape(L.resume)}">${iconBox("mdi:play", "action-icon")}</button>` : "")
              : (pauseButton?.entity_id ? `<button class="round" data-press="${htmlEscape(pauseButton.entity_id)}" title="${htmlEscape(L.pause)}">${iconBox("mdi:pause", "action-icon")}</button>` : "")}
            ${masterButton ? `<button class="round ${attrs.manual_master_active ? "active-master" : ""}" data-press="${htmlEscape(masterButton.entity_id || "")}" title="${htmlEscape(attrs.manual_master_active ? `${L.master}: ON` : `${L.master}: OFF`)}">${iconBox("mdi:hand-back-right", "action-icon")}</button>` : ""}
            ${attrs.night_enabled && attrs.night_source === "entity" && attrs.night_entity && this._state(attrs.night_entity) ? `<button class="round" data-night-source="${htmlEscape(attrs.night_entity)}" title="${htmlEscape(L.nightSchedule)}">${iconBox("mdi:calendar-clock", "action-icon")}</button>` : ""}` : ""}
            <button class="round advanced-button" data-advanced title="${htmlEscape(L.advanced)}">${iconBox("mdi:tune-variant", "advanced-icon")}<span>${htmlEscape(L.advanced)}</span></button>
          </div></div>
        </div>
      </ha-card>` : `<ha-card data-card-mode="easy" class="easy-card ${cardClass}">
        <div class="easy-wrap" data-easy-layout>
          <div class="easy-header">
            <div class="heading"><div class="easy-brand">${htmlEscape(this._config.title || L.title)}</div><div class="easy-room">${htmlEscape(roomName)}</div></div>
            <div class="easy-status">${iconBox(attrs.manual_master_active ? "mdi:hand-back-right" : modeIcon, "easy-status-icon")}<span>${htmlEscape(attrs.manual_master_active ? L.manualOverride : modeLabel)}</span></div>
          </div>
          ${this._config.show_sun_track !== false && sectors.length ? `<button class="easy-sun" data-easy-sun data-more="${htmlEscape(sunEntity)}">
            <span class="easy-sun-head">${iconBox(easySunIcon, `easy-sun-icon ${easySunActive ? "calm-pulse" : ""}`)}<span class="easy-sun-copy"><small>${htmlEscape(`${L.sun} · ${effectiveSourceLabel}`)}</small><strong>${htmlEscape(easySunLabel)}</strong></span></span>
            <span class="track easy-track">${sectorBars}${sunAvailable ? `<span class="sun-dot ${easySunActive ? "calm-pulse" : ""}"></span>` : ""}</span>
          </button>` : ""}
          ${this._config.show_covers !== false ? `<div class="easy-covers" data-easy-covers>${easyCoverRows || `<div class="message">${htmlEscape(L.noCovers)}</div>`}</div>` : ""}
          ${this._config.show_actions !== false && masterButton?.entity_id ? `<div class="easy-actions">
            <button class="easy-action ${attrs.manual_master_active ? "active-master" : ""}" data-press="${htmlEscape(masterButton.entity_id)}" title="${htmlEscape(L.manualOverride)}">${iconBox("mdi:hand-back-right", "action-icon")}<span>${htmlEscape(L.manualOverride)}</span></button>
          </div>` : ""}
        </div>
      </ha-card>`}`;

    if (nextCardHtml === this._cardHtml) {
      return;
    }
    this._cardHtml = nextCardHtml;
    updateStableMarkup(this.shadowRoot, nextCardHtml);

  }

  _messageCard(message) {
    return `<style>:host{display:block;width:100%;max-width:100%}ha-card{padding:18px;border-radius:20px}.message{font-size:13px;opacity:.72}</style><ha-card><div class="message">${htmlEscape(message)}</div></ha-card>`;
  }
}

class SmartShadingBadge extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._config = {};
    this._hass = null;
    this._lastRenderSignature = "";
  }

  static getStubConfig(hass) {
    const state = Object.values(hass?.states || {}).find((candidate) =>
      candidate?.entity_id?.startsWith("sensor.") && candidate.attributes?.smart_shading_entry_id
      && (candidate.attributes?.smart_shading_room_id || Array.isArray(candidate.attributes?.rooms)));
    return state ? { entity: state.entity_id, tap_action: { action: "more-info" } } : {};
  }
  static async getConfigElement() { return document.createElement("smart-shading-badge-editor"); }

  setConfig(config = {}) {
    if (!config || typeof config !== "object") throw new Error("Invalid Smart Shading badge configuration");
    this._config = { tap_action: { action: "more-info" }, ...config };
    this._lastRenderSignature = "";
    this._render();
  }

  set hass(hass) {
    this._hass = hass;
    const state = hass?.states?.[this._config.entity];
    let signature;
    try {
      signature = JSON.stringify([this._config, hass?.language || "en", state?.state, state?.attributes]);
    } catch (_error) {
      signature = `${this._config.entity || ""}:${state?.state || ""}:${state?.last_changed || ""}`;
    }
    if (signature === this._lastRenderSignature) return;
    this._lastRenderSignature = signature;
    this._render();
  }

  _performNativeTapAction() {
    const entityId = String(this._config.entity || "");
    if (!entityId) return;
    this.dispatchEvent(new CustomEvent("hass-action", {
      bubbles: true,
      composed: true,
      detail: { action: "tap", config: { ...this._config, entity: entityId } },
    }));
  }

  _bindInteraction() {
    const badge = this.shadowRoot?.querySelector?.("ha-badge");
    if (!badge || !this._config.entity) return;
    badge.addEventListener?.("click", (event) => {
      event.stopPropagation?.();
      this._performNativeTapAction();
    });
    badge.addEventListener?.("keydown", (event) => {
      if (event.key !== "Enter" && event.key !== " ") return;
      event.preventDefault?.();
      this._performNativeTapAction();
    });
  }

  _labels() {
    const de = String(this._hass?.language || "en").toLowerCase().startsWith("de");
    const modes = de ? {
      safety: "Sicherheit", night: "Nachtmodus", heat: "Hitzeschutz", glare: "Blendschutz",
      solar: "Sonnenschutz", comfort: "Komfort", paused: "Pausiert", finished: "Tag beendet",
      open: "Offen", idle: "Bereit", disabled: "Manuell", unavailable: "Nicht verfügbar",
    } : {
      safety: "Safety", night: "Night mode", heat: "Heat protection", glare: "Glare protection",
      solar: "Solar shading", comfort: "Comfort", paused: "Paused", finished: "Day finished",
      open: "Open", idle: "Ready", disabled: "Manual", unavailable: "Unavailable",
    };
    return de ? {
      modes, auto: "Auto", pauseUntil: "Pause bis", roomsPaused: "pausiert", roomsManual: "manuell",
      choose: "Smart-Shading-Status auswählen", house: "Haus", room: "Raum",
    } : {
      modes, auto: "Auto", pauseUntil: "Paused until", roomsPaused: "paused", roomsManual: "manual",
      choose: "Select a Smart Shading status", house: "House", room: "Room",
    };
  }

  _formatPause(value) {
    if (!value) return "";
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return "";
    const now = new Date();
    const sameDay = date.getFullYear() === now.getFullYear()
      && date.getMonth() === now.getMonth() && date.getDate() === now.getDate();
    return new Intl.DateTimeFormat(undefined, sameDay
      ? { hour: "2-digit", minute: "2-digit" }
      : { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" }).format(date);
  }

  _profile(state) {
    const attrs = asRecord(state?.attributes);
    if (attrs.badge_profile) return String(attrs.badge_profile);
    const room = asRecord(attrs.configuration);
    const roomProfiles = asArray(room.sectors).flatMap((sector) =>
      asArray(asRecord(sector).layers).map((layer) => String(asRecord(layer).profile || "")).filter(Boolean));
    if (roomProfiles.length) return roomProfiles[0];
    const houseProfiles = asArray(attrs.cover_profiles).map(String).filter(Boolean);
    return houseProfiles.length === 1 ? houseProfiles[0] : "venetian";
  }

  _coverIcon(state, mode) {
    const closed = ["comfort", "solar", "glare", "heat", "night", "safety"].includes(mode);
    return profileIcon(this._profile(state), closed);
  }

  _stateIcon(mode) {
    return ({
      safety: "mdi:shield-alert", night: "mdi:weather-night", heat: "mdi:thermometer-high",
      glare: "mdi:eye-outline", solar: "mdi:weather-sunny", comfort: "mdi:account-check-outline",
      paused: "mdi:pause", disabled: "mdi:hand-back-right", finished: "mdi:check",
      open: "mdi:auto-mode", idle: "mdi:auto-mode", unavailable: "mdi:alert-circle-outline",
    })[mode] || "mdi:auto-mode";
  }

  _color(mode) {
    return ({
      safety: "var(--error-color,var(--red-color,#db4437))",
      disabled: "var(--error-color,var(--red-color,#db4437))",
      paused: "var(--info-color,var(--primary-color,#039be5))",
      night: "var(--purple-color,#926bc7)",
      heat: "var(--deep-orange-color,#ff5722)",
      glare: "var(--amber-color,#ffc107)",
      solar: "var(--amber-color,#ffc107)",
      comfort: "var(--green-color,#4caf50)",
      unavailable: "var(--error-color,var(--red-color,#db4437))",
    })[mode] || "var(--state-inactive-color,var(--secondary-text-color,#727272))";
  }

  _status(state, L) {
    const attrs = asRecord(state?.attributes);
    const rooms = asArray(attrs.rooms).map(asRecord);
    const isRoom = Boolean(attrs.smart_shading_room_id);
    if (isRoom) {
      const disabled = attrs.manual_master_active === true;
      const paused = attrs.pause_mode && attrs.pause_mode !== "auto";
      const mode = disabled ? "disabled" : paused ? "paused" : String(state?.state || "idle");
      const pauseTime = paused ? this._formatPause(attrs.pause_until) : "";
      const label = mode === "paused" && pauseTime
        ? `${L.pauseUntil} ${pauseTime}`
        : ["idle", "open", "comfort", "solar", "glare", "heat", "finished"].includes(mode)
          ? `${L.auto} · ${L.modes[mode] || humanizeToken(mode)}`
          : L.modes[mode] || humanizeToken(mode);
      return { mode, label, name: attrs.name || state?.attributes?.friendly_name || L.room, title: attrs.reason || label };
    }

    const pausedRooms = rooms.filter((room) => room.pause_mode && room.pause_mode !== "auto");
    const manualRooms = rooms.filter((room) => room.enabled === false);
    let mode = String(state?.state || "idle");
    if (mode !== "safety" && manualRooms.length) mode = "disabled";
    else if (mode !== "safety" && pausedRooms.length) mode = "paused";
    const parts = [];
    if (pausedRooms.length) parts.push(`${pausedRooms.length} ${L.roomsPaused}`);
    if (manualRooms.length) parts.push(`${manualRooms.length} ${L.roomsManual}`);
    const pauseTimes = [...new Set(pausedRooms.map((room) => this._formatPause(room.pause_until)).filter(Boolean))];
    let label = ["idle", "open", "comfort", "solar", "glare", "heat", "finished"].includes(mode)
      ? `${L.auto} · ${L.modes[mode] || humanizeToken(mode)}`
      : L.modes[mode] || humanizeToken(mode);
    if (mode === "paused" && pauseTimes.length === 1) label = `${L.pauseUntil} ${pauseTimes[0]}`;
    else if (parts.length) label = `${label} · ${parts.join(" · ")}`;
    const roomDetails = rooms.map((room) => `${room.name || room.id}: ${L.modes[room.mode] || humanizeToken(room.mode)}`).join(" · ");
    return { mode, label, name: attrs.name || state?.attributes?.friendly_name || L.house, title: roomDetails || label };
  }

  _render() {
    if (!this.shadowRoot) return;
    const L = this._labels();
    const state = this._hass?.states?.[this._config.entity];
    if (!this._config.entity || !state) {
      this.shadowRoot.innerHTML = `
        <style>:host{display:block;width:var(--ha-badge-size,36px);height:var(--ha-badge-size,36px)}ha-badge{--badge-color:var(--error-color,var(--red-color,#db4437))}.badge-symbol{position:relative;display:grid;place-items:center;width:22px;height:22px;color:var(--badge-color)}.cover-symbol{--mdc-icon-size:20px}.state-marker{position:absolute;right:-4px;bottom:-4px;display:grid;place-items:center;width:12px;height:12px;border-radius:50%;background:var(--ha-card-background,var(--card-background-color,#fff));box-shadow:0 0 0 1px var(--ha-card-border-color,var(--divider-color,#ddd));color:var(--badge-color)}.state-marker ha-icon{--mdc-icon-size:9px}</style>
        <ha-badge icon-only title="${htmlEscape(L.choose)}" aria-label="${htmlEscape(L.choose)}">
          <span slot="icon" class="badge-symbol">
            <ha-icon class="cover-symbol" icon="mdi:blinds-horizontal"></ha-icon>
            <span class="state-marker"><ha-icon icon="mdi:alert-circle-outline"></ha-icon></span>
          </span>
        </ha-badge>`;
      return;
    }
    const status = this._status(state, L);
    const name = this._config.name || status.name;
    const tooltip = [name, status.label, status.title !== status.label ? status.title : ""].filter(Boolean).join(" · ");
    this.shadowRoot.innerHTML = `
      <style>
        :host{display:block;width:var(--ha-badge-size,36px);height:var(--ha-badge-size,36px)}
        ha-badge{--badge-color:${htmlEscape(this._color(status.mode))}}
        .badge-symbol{position:relative;display:grid;place-items:center;width:22px;height:22px;color:var(--badge-color)}
        .cover-symbol{--mdc-icon-size:20px}
        .state-marker{position:absolute;right:-4px;bottom:-4px;display:grid;place-items:center;width:12px;height:12px;border-radius:50%;background:var(--ha-card-background,var(--card-background-color,#fff));box-shadow:0 0 0 1px var(--ha-card-border-color,var(--divider-color,#ddd));color:var(--badge-color)}
        .state-marker ha-icon{--mdc-icon-size:9px}
      </style>
      <ha-badge type="button" icon-only data-mode="${htmlEscape(status.mode)}" title="${htmlEscape(tooltip)}" aria-label="${htmlEscape(tooltip)}">
        <span slot="icon" class="badge-symbol">
          <ha-icon class="cover-symbol" icon="${htmlEscape(this._coverIcon(state, status.mode))}"></ha-icon>
          <span class="state-marker"><ha-icon icon="${htmlEscape(this._stateIcon(status.mode))}"></ha-icon></span>
        </span>
      </ha-badge>`;
    this._bindInteraction();
  }
}

class SmartShadingBadgeEditor extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._config = {};
    this._hass = null;
    this._form = null;
    this._help = null;
    this._formLanguage = null;
    this._handleFormChange = (event) => {
      this._config = { ...this._config, ...(event.detail?.value || {}) };
      this._emit();
    };
  }

  set hass(hass) {
    this._hass = hass;
    this._ensureStructure();
    this._syncForm(false);
  }
  setConfig(config = {}) {
    const nextConfig = { ...(config || {}) };
    const dataChanged = nextConfig.entity !== this._config.entity || nextConfig.name !== this._config.name;
    this._config = nextConfig;
    this._ensureStructure();
    this._syncForm(dataChanged);
  }
  _emit() {
    this.dispatchEvent(new CustomEvent("config-changed", {
      detail: { config: { ...this._config } }, bubbles: true, composed: true,
    }));
  }

  _ensureStructure() {
    if (!this.shadowRoot || this._form) return;
    this.shadowRoot.innerHTML = `
      <style>:host{display:block;padding:4px 0}.help{margin-top:12px;font-size:11px;line-height:1.4;color:var(--secondary-text-color)}</style>
      <div class="editor">
        <ha-form></ha-form>
        <div class="help"></div>
      </div>`;
    this._form = this.shadowRoot.querySelector?.("ha-form") || null;
    this._help = this.shadowRoot.querySelector?.(".help") || null;
    if (!this._form) return;
    this._form.schema = [
      { name: "entity", required: true, selector: { entity: { domain: "sensor", integration: "smart_shading" } } },
      { name: "name", selector: { text: {} } },
    ];
    this._form.addEventListener("value-changed", this._handleFormChange);
  }

  _syncForm(dataChanged) {
    if (!this._form) return;
    const language = String(this._hass?.language || "en").toLowerCase();
    const de = language.startsWith("de");
    if (this._form.hass !== this._hass) this._form.hass = this._hass;
    if (dataChanged || this._form.data == null) this._form.data = { ...this._config };
    if (this._formLanguage !== language) {
      this._formLanguage = language;
      this._form.computeLabel = (schema) => ({
        entity: de ? "Status-Entität für Haus oder Raum" : "House or room status entity",
        name: de ? "Name im Tooltip (optional)" : "Tooltip name (optional)",
      }[schema.name] || schema.name);
      if (this._help) this._help.textContent = de
        ? "Logo, Zusatzsymbol und Farbe folgen dem Status. Entität, Interaktion und Sichtbarkeit werden mit Home Assistants nativen Editoren konfiguriert; dieses Badge besitzt keine eigenen Navigate-, Hidden- oder Zustandslisten."
        : "Logo, marker and color follow the status. Configure the entity, interaction and visibility with Home Assistant's native editors; this Badge has no separate Navigate, Hidden or state lists.";
    }
  }
}

class SmartShadingV4CardEditor extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._hass = null;
    this._config = { show_sun_track: true, show_covers: true, show_actions: true };
  }

  set hass(hass) { this._hass = hass; this._render(); }
  setConfig(config = {}) { this._config = { ...this._config, ...(config && typeof config === "object" ? config : {}) }; this._render(); }

  _labels() {
    const de = String(this._hass?.language || "en").toLowerCase().startsWith("de");
    return de ? {
      entity: "Raumstatus-Entität", title: "Überschrift", sun: "Sonnenverlauf anzeigen", covers: "Behänge anzeigen", actions: "Aktionsbuttons anzeigen",
    } : {
      entity: "Room status entity", title: "Title", sun: "Show sun track", covers: "Show covers", actions: "Show action buttons",
    };
  }

  _emit() { this.dispatchEvent(new CustomEvent("config-changed", { detail: { config: { ...this._config } }, bubbles: true, composed: true })); }
  _toggle(key, checked) { this._config = { ...this._config, [key]: checked }; this._emit(); this._render(); }

  _render() {
    if (!this.shadowRoot) return;
    const L = this._labels();
    const entities = this._hass ? Object.values(this._hass.states || {}).filter((state) => state.entity_id?.startsWith("sensor.") && state.attributes?.configuration && state.attributes?.smart_shading_room_id) : [];
    this.shadowRoot.innerHTML = `
      <style>*{box-sizing:border-box}.editor{display:grid;gap:15px;padding:4px 0;color:var(--primary-text-color)}label{display:grid;gap:6px;font-size:12px}select,input{width:100%;padding:11px;border:1px solid rgba(255,255,255,.15);border-radius:8px;background:var(--secondary-background-color,#292929);color:inherit}.toggle{display:flex;justify-content:space-between;align-items:center;gap:14px}.toggle input{width:20px;height:20px}.help{font-size:10px;opacity:.58;line-height:1.35}</style>
      <div class="editor">
        <label>${htmlEscape(L.entity)}<select data-entity><option value=""></option>${entities.map((state) => `<option value="${htmlEscape(state.entity_id)}" ${state.entity_id === this._config.entity ? "selected" : ""}>${htmlEscape(cleanDisplayName(state.attributes?.name, state.attributes?.friendly_name || "Smart Shading"))}</option>`).join("")}</select></label>
        <label>${htmlEscape(L.title)}<input data-title value="${htmlEscape(this._config.title || "")}"></label>
        <label class="toggle"><span>${htmlEscape(L.sun)}</span><input type="checkbox" data-toggle="show_sun_track" ${this._config.show_sun_track !== false ? "checked" : ""}></label>
        <label class="toggle"><span>${htmlEscape(L.covers)}</span><input type="checkbox" data-toggle="show_covers" ${this._config.show_covers !== false ? "checked" : ""}></label>
        <label class="toggle"><span>${htmlEscape(L.actions)}</span><input type="checkbox" data-toggle="show_actions" ${this._config.show_actions !== false ? "checked" : ""}></label>
      </div>`;
    this.shadowRoot.querySelector?.("[data-entity]")?.addEventListener("change", (event) => { this._config = { ...this._config, entity: event.target.value }; this._emit(); });
    this.shadowRoot.querySelector?.("[data-title]")?.addEventListener("change", (event) => { this._config = { ...this._config, title: event.target.value }; this._emit(); });
    this.shadowRoot.querySelectorAll?.("[data-toggle]").forEach((element) => element.addEventListener("change", () => this._toggle(element.dataset.toggle, element.checked)));
  }
}

if (!customElements.get("smart-shading-dialog")) customElements.define("smart-shading-dialog", SmartShadingV4Dialog);
if (!customElements.get("smart-shading-card")) customElements.define("smart-shading-card", SmartShadingV4Card);
if (!customElements.get("smart-shading-card-editor")) customElements.define("smart-shading-card-editor", SmartShadingV4CardEditor);
if (!customElements.get("smart-shading-badge")) customElements.define("smart-shading-badge", SmartShadingBadge);
if (!customElements.get("smart-shading-badge-editor")) customElements.define("smart-shading-badge-editor", SmartShadingBadgeEditor);

window.customCards = window.customCards || [];
if (!window.customCards.some((card) => card.type === "smart-shading-card")) {
  window.customCards.push({ type: "smart-shading-card", name: "Smart Shading", description: "Smart Shading room card with an optional details dialog", preview: true });
}
window.customBadges = window.customBadges || [];
if (!window.customBadges.some((badge) => badge.type === "smart-shading-badge")) {
  window.customBadges.push({ type: "smart-shading-badge", name: "Smart Shading status", description: "Native round live status badge for a house or room", preview: true });
}
console.info("%c SMART-SHADING %c loaded ", "color:white;background:#0aa4d6;font-weight:700", "color:#0aa4d6;background:#111");
