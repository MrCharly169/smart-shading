const htmlEscape = (value) => String(value ?? "").replace(/[&<>'"]/g, (char) => ({
  "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;",
}[char]));
const asArray = (value) => Array.isArray(value) ? value : [];
const asNumber = (value, fallback = null) => {
  if (value === null || value === undefined || value === "") return fallback;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
};
const clamp = (value, min, max) => Math.min(Math.max(value, min), max);
const isRawEntityId = (value) => /^(?:cover|switch|binary_sensor|sensor|number|select|button)\.[a-z0-9_]+$/i.test(String(value || "").trim());
const iconBox = (icon, className = "") => `<span class="icon-box ${htmlEscape(className)}" aria-hidden="true"><ha-icon icon="${htmlEscape(icon)}"></ha-icon></span>`;

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
    "Easy Mode has no schedule": "Easy Mode verwendet keinen Zeitplan",
    "Night Mode is unavailable in Easy Mode": "Die Nachtfunktion ist im Easy Mode nicht verfügbar",
    "Sun position is unavailable; cover positions held": "Sonnenposition nicht verfügbar; Behangpositionen werden gehalten",
    "Sun is active in a configured facade sector": "Sonne ist in einem konfigurierten Fassadensektor aktiv",
    "Outdoor temperature gate blocks Easy Mode shading": "Die Außentemperaturfreigabe blockiert die Easy-Mode-Beschattung",
    "Optional Sun confirmation blocks Easy Mode shading": "Die optionale Sonnenbestätigung blockiert die Easy-Mode-Beschattung",
    "Sun is outside all configured facade sectors": "Sonne ist außerhalb aller konfigurierten Fassadensektoren",
    "Month outside shading season": "Monat außerhalb der Beschattungssaison",
    "Weekday outside shading schedule": "Wochentag außerhalb des Beschattungszeitplans",
    "Inside fixed shading time": "Innerhalb der festen Beschattungszeit",
    "Outside fixed shading time": "Außerhalb der festen Beschattungszeit",
    "Schedule permits normal shading": "Zeitplan erlaubt normale Beschattung",
    "Night Mode requires Advanced Mode": "Die Nachtfunktion benötigt den Advanced Mode",
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
    this._opener = null;
    this._keyHandler = (event) => {
      if (event.key === "Escape") {
        event.preventDefault?.();
        this.close();
        return;
      }
      if (event.key !== "Tab") return;
      const focusable = asArray(Array.from(this.shadowRoot?.querySelectorAll?.(
        'button:not([disabled]),[href],[tabindex]:not([tabindex="-1"])',
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
      title: "Smart Shading · Erweiterte Ansicht",
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
    } : {
      title: "Smart Shading · Advanced view",
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
    };
  }

  _modeText(mode) {
    const de = String(this._hass?.language || "en").toLowerCase().startsWith("de");
    const values = de ? {
      safety: "Safety", heat: "Heat Protection", solar: "Sonnenschutz",
      comfort: "Komfort", paused: "Pausiert", open: "Offen", idle: "Bereit",
      disabled: "Master aktiv", finished: "Für heute beendet",
      night: "Nacht",
    } : {
      safety: "Safety", heat: "Heat protection", solar: "Solar shading",
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
      sun_below_horizon: "Sonne unter Horizont", schedule_blocked: "Zeitplan blockiert",
      paused: "Pausiert", heat: "Heat Protection", safety: "Safety", disabled: "Deaktiviert",
      night: "Nacht", night_blocked: "Nachtquelle blockiert", night_transition_hold: "Nachtübergang hält",
    } : {
      not_evaluated: "Not evaluated", outside_sun_sector: "Sun outside sector",
      waiting_for_lux: "Waiting for Sun Presence", sun_detected: "Sun detected",
      shading_active: "Shading active", waiting_conditions: "Waiting for conditions",
      sun_below_horizon: "Sun below horizon", schedule_blocked: "Schedule blocked",
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
    return values[reason] || String(reason || "");
  }

  _control(key) {
    return this._controls.find((state) => state?.attributes?.smart_shading_control_key === key);
  }

  _callEntity(entityId) {
    if (!this._hass || !entityId) return;
    const domain = entityId.split(".")[0];
    const service = domain === "button" ? "press" : domain === "switch" ? "toggle" : null;
    if (service) this._hass.callService(domain, service, { entity_id: entityId });
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
    const previousScrollTop = existingDialog?.scrollTop || 0;
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
        <div class="details">
          <span>${htmlEscape(L.raw)}: ${htmlEscape(raw)} ${htmlEscape(sector.lux_unit || "")}</span>
          <span>${htmlEscape(L.thresholds)}: ON ${htmlEscape(settings.sun_on_lux ?? "–")} / OFF ${htmlEscape(settings.sun_off_lux ?? "–")} lx</span>
          ${sector.pending_until ? `<span>${htmlEscape(L.pending)}: ${htmlEscape(pending)}</span>` : ""}
        </div>
      </div>`;
    }).join("");

    const coverHtml = covers.map((cover, index) => {
      const fallback = `${L.covers} ${index + 1}`;
      const name = cleanDisplayName(cover.name, fallback);
      const state = this._hass?.states?.[cover.entity];
      const currentPosition = asNumber(state?.attributes?.current_position, null);
      const currentTilt = asNumber(state?.attributes?.current_tilt_position, null);
      const target = targetByEntity.get(cover.entity) || {};
      const localPause = coverPauseByEntity.get(cover.entity) || {};
      const suppressionText = asArray(target.suppressed).map((item) => this._suppressionText(item));
      return `
        <div class="data-card ${localPause.active ? "pause-card" : ""}">
          <div class="data-title"><span>${htmlEscape(name)}</span><strong>${htmlEscape(localPause.active ? L.paused : this._modeText(target.mode || this._roomState.state))}</strong></div>
          <div class="facts">
            <span>${L.current}: ${currentPosition == null ? "–" : `${Math.round(currentPosition)}%`}</span>
            <span>${L.tilt}: ${currentTilt == null ? "–" : `${Math.round(currentTilt)}%`}</span>
            <span>${L.target}: ${target.position == null ? "–" : `${Math.round(Number(target.position))}%`}${target.tilt == null ? "" : ` / ${Math.round(Number(target.tilt))}%`}</span>
          </div>
          ${localPause.active ? `<div class="warning">${htmlEscape(L.pauseUntil)} ${htmlEscape(this._formatDate(localPause.until))}</div>` : ""}
          ${suppressionText.length ? `<div class="warning">${htmlEscape(suppressionText.join(" · "))}</div>` : ""}
        </div>`;
    }).join("");

    const eventHtml = events.length ? events.map((event) => {
      const time = event.time || event.timestamp || event.created_at;
      const data = Object.entries(event)
        .filter(([key]) => !["time", "timestamp", "created_at", "event", "type"].includes(key))
        .map(([key, value]) => `${key}: ${Array.isArray(value) ? value.join(", ") : String(value ?? "")}`)
        .join(" · ");
      return `<div class="event"><time>${htmlEscape(this._formatDate(time))}</time><strong>${htmlEscape(event.event || event.type || "event")}</strong><span>${htmlEscape(data)}</span></div>`;
    }).join("") : `<div class="empty">${htmlEscape(L.noEvents)}</div>`;

    const mainHtml = `
      <section><h3>${htmlEscape(L.overview)}</h3><div class="summary">
        <div><small>${htmlEscape(L.mode)}</small><strong>${htmlEscape(this._modeText(this._roomState.state))}</strong></div>
        <div><small>${htmlEscape(L.reason)}</small><strong>${htmlEscape(localizedReason(attrs.reason, this._hass?.language, L.noReason))}</strong></div>
        <div><small>${htmlEscape(L.schedule)}</small><strong>${attrs.schedule_active === false ? L.inactive : L.active}</strong></div>
        <div><small>${htmlEscape(L.last)}</small><strong>${htmlEscape(this._formatDate(attrs.last_evaluation))}</strong></div>
        <div><small>${htmlEscape(L.sent)}</small><strong>${htmlEscape(attrs.sent_commands ?? 0)}</strong></div>
        <div><small>${htmlEscape(L.suppressed)}</small><strong>${htmlEscape(attrs.suppressed_commands ?? 0)}</strong></div>
      </div></section>
      ${nightHtml}
      <section><h3>${htmlEscape(L.controls)}</h3><div class="actions">
        ${attrs.pause_mode && attrs.pause_mode !== "auto"
          ? (resume?.entity_id ? `<button data-press="${htmlEscape(resume.entity_id)}">${iconBox("mdi:play", "action-icon")}${htmlEscape(L.resume)}</button>` : "")
          : (pause?.entity_id ? `<button data-press="${htmlEscape(pause.entity_id)}">${iconBox("mdi:pause", "action-icon")}${htmlEscape(L.pause)}</button>` : "")}
        ${evaluate?.entity_id ? `<button data-press="${htmlEscape(evaluate.entity_id)}">${iconBox("mdi:refresh", "action-icon")}${htmlEscape(L.evaluate)}</button>` : ""}
        ${master?.entity_id ? `<button data-press="${htmlEscape(master.entity_id)}">${iconBox("mdi:hand-back-right", "action-icon")}${htmlEscape(L.master)}</button>` : ""}
        ${exportLog?.entity_id ? `<button data-press="${htmlEscape(exportLog.entity_id)}">${iconBox("mdi:file-download-outline", "action-icon")}${htmlEscape(L.exportLog)}</button>` : ""}
      </div></section>
      <section><h3>${htmlEscape(L.sectors)}</h3><div class="grid">${sectorHtml || `<div class="empty">–</div>`}</div></section>
      <section><h3>${htmlEscape(L.covers)}</h3><div class="grid">${coverHtml || `<div class="empty">–</div>`}</div></section>
      <section><h3>${htmlEscape(L.diagnostics)}</h3><div>${eventHtml}</div></section>`;

    if (!existingDialog) this.shadowRoot.innerHTML = `
      <style>
        :host{position:fixed;inset:0;z-index:99999;display:block;font-family:var(--paper-font-body1_-_font-family,system-ui,sans-serif);color:var(--primary-text-color,#fff)}
        *{box-sizing:border-box}
        .backdrop{position:absolute;inset:0;background:rgba(0,0,0,.68);backdrop-filter:blur(5px)}
        .dialog{position:absolute;left:50%;top:50%;transform:translate(-50%,-50%);width:min(760px,calc(100vw - 24px));max-height:min(900px,calc(100vh - 24px));max-height:min(900px,calc(100dvh - 24px));overflow:auto;overscroll-behavior:contain;-webkit-overflow-scrolling:touch;scrollbar-gutter:stable;background:var(--ha-card-background,var(--card-background-color,#1d1d1d));border:1px solid rgba(255,255,255,.13);border-radius:24px;box-shadow:0 24px 80px rgba(0,0,0,.55)}
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
        .summary{display:grid;grid-template-columns:repeat(auto-fit,minmax(120px,1fr));gap:8px}.summary div{padding:11px;border-radius:14px;background:rgba(255,255,255,.055)}.summary small{display:block;opacity:.55;margin-bottom:4px}.summary strong{font-size:12px;overflow-wrap:anywhere}
        .actions{display:flex;gap:8px;flex-wrap:wrap}.actions button{height:34px;padding:0 12px;display:inline-flex;align-items:center;justify-content:center;gap:6px;font-size:12px;line-height:1}
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

    const dialog = this.shadowRoot.querySelector?.(".dialog");
    const main = this.shadowRoot.querySelector?.("main");
    const activeElement = this.shadowRoot.activeElement;
    const focusToken = activeElement && activeElement !== main
      ? ["press", "more", "nightSource"].find((key) => activeElement.dataset?.[key])
      : null;
    const focusValue = focusToken ? activeElement.dataset[focusToken] : null;
    const contentChanged = !existingDialog || this._mainHtml !== mainHtml;
    if (existingDialog && main && contentChanged) main.innerHTML = mainHtml;
    if (contentChanged) {
      this._mainHtml = mainHtml;
      this._contentWriteCount += 1;
      this.dataset.contentWriteCount = String(this._contentWriteCount);
    }
    if (!existingDialog) this.shadowRoot.querySelectorAll?.("[data-close]").forEach((element) => element.addEventListener("click", () => this.close()));
    if (contentChanged) {
      main?.querySelectorAll?.("[data-press]").forEach((element) => element.addEventListener("click", () => this._callEntity(element.dataset.press)));
      main?.querySelectorAll?.("[data-more]").forEach((element) => element.addEventListener("click", () => this._more(element.dataset.more)));
      main?.querySelectorAll?.("[data-night-source]").forEach((element) => element.addEventListener("click", () => this._openNightSource(element.dataset.nightSource)));
      if (focusToken && focusValue) {
        const attribute = focusToken === "nightSource" ? "data-night-source" : `data-${focusToken}`;
        const replacement = asArray(Array.from(main?.querySelectorAll?.(`[${attribute}]`) || []))
          .find((element) => element.dataset?.[focusToken] === focusValue);
        replacement?.focus?.({ preventScroll: true });
      }
    }
    if (dialog) dialog.scrollTop = previousScrollTop;
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
    const states = [...entityIds].filter(Boolean).sort().map((entityId) => {
      const state = this._hass?.states?.[entityId];
      return [entityId, state?.state ?? null, state?.attributes ?? null];
    });
    try {
      return JSON.stringify([this._config, this._hass?.language || "en", states]);
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
      safety: "Safety", heat: "Heat", night: "Nacht", solar: "Sonnenschutz", comfort: "Komfort", paused: "Pause", open: "Offen", idle: "Bereit", disabled: "Aus", finished: "Fertig",
      wind: "Wind", frost: "Frost", windows: "Fenster", sun: "Sonne", temp: "Temperatur", position: "Position", tilt: "Lamelle", manual: "Manuell", master: "Master",
      blocked: "Blockiert", pauseUntil: "Pausiert bis", schedule: "Zeitplan inaktiv", sunMissing: "Sonnenentität fehlt", advanced: "Erweiterte Ansicht",
      pause: "Pausieren", resume: "Fortsetzen", evaluate: "Neu auswerten", copy: "Card-YAML kopieren", copied: "Kopiert",
      belowHorizon: "Nacht", outsideSector: "Außerhalb", waitingLux: "Wartet auf Sonne", waiting: "Wartet", active: "Aktiv", detected: "Sonne erkannt",
      automatic: "Automatik", manualOverride: "Manuelle Sperre", sunInSector: "Sonne im Sektor", sunOutsideSector: "Sonne außerhalb", nightSchedule: "Nachtzeitplan bearbeiten",
      sourceGeometry: "Sonnenposition", sourceBinary: "Sonnensensor", sourceLux: "Luxsensor", sourceWeather: "Wetter", sourceMixed: "Kombiniert",
      confirmed: "Sonne bestätigt", confirmationBlocked: "Sonne nicht bestätigt", geometryFallback: "Nur Sonnenposition", inactiveSignal: "Nicht aktiv", temperatureBlocked: "Temperatur zu niedrig",
      sunUnavailable: "Sonnenstatus nicht verfügbar",
      roomContext: "Raum", scheduleContext: "Zeitplan", overrideContext: "Override",
    } : {
      title: "Shading", room: "Room", noEntity: "Select a Smart Shading room", unavailable: "Smart Shading status unavailable",
      noRoom: "No room configured", noCovers: "No covers assigned", cover: "Cover", sector: "Sector",
      safety: "Safety", heat: "Heat", night: "Night", solar: "Solar", comfort: "Comfort", paused: "Paused", open: "Open", idle: "Ready", disabled: "Off", finished: "Done",
      wind: "Wind", frost: "Frost", windows: "Windows", sun: "Sun", temp: "Temperature", position: "Position", tilt: "Tilt", manual: "Manual", master: "Master",
      blocked: "Blocked", pauseUntil: "Paused until", schedule: "Schedule inactive", sunMissing: "Sun entity missing", advanced: "Advanced view",
      pause: "Pause", resume: "Resume", evaluate: "Evaluate again", copy: "Copy card YAML", copied: "Copied",
      belowHorizon: "Night", outsideSector: "Outside", waitingLux: "Waiting for sun", waiting: "Waiting", active: "Active", detected: "Sun detected",
      automatic: "Automatic", manualOverride: "Manual Override", sunInSector: "Sun in sector", sunOutsideSector: "Sun outside sector", nightSchedule: "Edit night schedule",
      sourceGeometry: "Sun position", sourceBinary: "Sun sensor", sourceLux: "Lux sensor", sourceWeather: "Weather", sourceMixed: "Combined",
      confirmed: "Sun confirmed", confirmationBlocked: "Sun not confirmed", geometryFallback: "Sun position only", inactiveSignal: "Inactive", temperatureBlocked: "Temperature too low",
      sunUnavailable: "Sun status unavailable",
      roomContext: "Room", scheduleContext: "Schedule", overrideContext: "Override",
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
    })[value] || (effectiveActive ? L.sunInSector : L.sunOutsideSector);
  }

  _render() {
    if (!this.shadowRoot) return;
    this._renderCount += 1;
    this.dataset.renderCount = String(this._renderCount);
    const L = this._labels();
    if (!this._config?.entity) {
      this.shadowRoot.innerHTML = this._messageCard(L.noEntity);
      return;
    }
    const roomState = this._resolvedRoomState();
    if (!roomState) {
      this.shadowRoot.innerHTML = this._messageCard(L.unavailable);
      return;
    }

    const attrs = roomState.attributes || {};
    const advancedMode = attrs.smart_shading_advanced_mode === true;
    const room = attrs.configuration || {};
    const controls = this._controls(roomState);
    const sectors = asArray(room.sectors);
    const sectorStatuses = new Map(asArray(attrs.sector_statuses).map((sector) => [sector.id, sector]));
    const covers = sectors.flatMap((sector) => asArray(sector.layers).flatMap((layer) =>
      asArray(layer.covers).map((cover) => ({ ...cover, sector, layer }))
    ));
    const mode = roomState.state || "idle";
    const [modeIcon, modeLabel, modeClass] = this._modeInfo(mode, L);
    const activeSectorNames = asArray(attrs.active_sectors).filter(Boolean);
    const detailedModeLabel = attrs.manual_master_active
      ? `${L.manual} · ${L.overrideContext}`
      : mode === "paused"
        ? `${L.paused} · ${L.roomContext}`
        : mode === "night"
          ? `${L.night} · ${L.scheduleContext}`
          : mode === "safety"
            ? `${L.safety} · ${L.blocked}`
            : advancedMode && ["solar", "comfort"].includes(mode) && activeSectorNames.length
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
      const tilt = asNumber(state?.attributes?.current_tilt_position, null);
      const locked = cover.lock && this._state(cover.lock)?.state === "on";
      const unsafe = cover.window && this._state(cover.window)?.state !== (cover.window_safe_state || "on");
      const target = targetByEntity.get(cover.entity) || {};
      const localPause = coverPauseByEntity.get(cover.entity) || {};
      const locallyPaused = Boolean(localPause.active);
      const roomPaused = attrs.pause_mode && attrs.pause_mode !== "auto";
      const manualMaster = attrs.manual_master_active;
      const rowClass = locked || unsafe || roomPaused || locallyPaused || manualMaster ? "warning" : "";
      const leadingIcon = manualMaster ? "mdi:hand-back-right" : (roomPaused || locallyPaused) ? "mdi:pause-circle" : locked ? "mdi:lock" : unsafe ? "mdi:window-open-variant" : "mdi:autorenew";
      return `<div class="cover-row ${rowClass}">
        <button class="cover-head" data-more="${htmlEscape(cover.entity)}" title="${htmlEscape(locallyPaused ? `${L.pauseUntil} ${this._formatDate(localPause.until)}` : name)}">
          <span class="cover-name">${iconBox(leadingIcon, "cover-icon")}<strong>${htmlEscape(name)}</strong></span>
          <span class="values">${manualMaster ? `${L.master} · ` : (roomPaused || locallyPaused) ? `${L.paused} · ` : locked ? `${L.manual} · ` : ""}${position == null ? "–" : `${Math.round(position)}%`}${tilt == null ? "" : ` · ${L.tilt} ${Math.round(tilt)}%`}</span>
        </button>
        <div class="bar ${position == null ? "unknown" : ""}">${position == null ? "" : `<i style="width:${position}%"></i>`}</div>
        ${tilt == null ? "" : `<div class="bar tilt"><i style="width:${clamp(tilt, 0, 100)}%"></i></div>`}
        ${advancedMode && target.position != null ? `<div class="target-line">${L.position} ${Math.round(Number(target.position))}%${target.tilt == null ? "" : ` · ${L.tilt} ${Math.round(Number(target.tilt))}%`}</div>` : ""}
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
        : state?.state === "closed"
          ? "mdi:blinds"
          : "mdi:blinds-open";
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
    const temperatureGate = attrs.easy_temperature_gate && typeof attrs.easy_temperature_gate === "object"
      ? attrs.easy_temperature_gate
      : {};
    const temperatureBlocked = temperatureGate.enabled === true && temperatureGate.passed === false;
    const easySunActive = sunAvailable && sunAboveHorizon && effectiveSunActive && !temperatureBlocked;
    const easySunLabel = !sunAvailable
      ? L.sunUnavailable
      : temperatureBlocked
      ? L.temperatureBlocked
      : this._confirmationText(confirmationState, easySunActive, sunAboveHorizon, L);
    const easySunIcon = !sunAvailable ? "mdi:help-circle-outline" : !sunAboveHorizon ? "mdi:weather-night" : easySunActive ? "mdi:white-balance-sunny" : "mdi:weather-sunset";

    const pauseButton = this._control(controls, "pause_default");
    const resumeButton = this._control(controls, "resume");
    const evaluateButton = this._control(controls, "evaluate");
    const masterButton = this._control(controls, "manual_master");
    const paused = attrs.pause_mode && attrs.pause_mode !== "auto";
    const cardClass = htmlEscape(`${modeClass} ${temperatureClass} ${(advancedMode ? manualIntervention : attrs.manual_master_active) ? "manual" : ""} ${attrs.manual_master_active ? "master" : ""}`);

    this.shadowRoot.innerHTML = `
      <style>
        :host{display:block;width:100%;max-width:100%;min-width:0;overflow:visible;font-family:var(--paper-font-body1_-_font-family,system-ui,sans-serif);container-type:inline-size;container-name:shading-card}
        *{box-sizing:border-box;min-width:0}
        ha-card{display:block;width:100%;max-width:100%;min-width:0;overflow:hidden;border-radius:22px;border:1px solid rgba(255,255,255,.09);box-shadow:none;background:var(--ha-card-background,var(--card-background-color,#202020));color:var(--primary-text-color,#fff)}
        ha-card.danger{background:linear-gradient(135deg,rgba(255,67,57,.27),rgba(30,27,27,.96))} ha-card.heat{background:linear-gradient(135deg,rgba(255,94,65,.23),rgba(29,27,27,.96))}
        ha-card.solar{background:linear-gradient(135deg,rgba(255,154,65,.18),rgba(30,29,27,.97))} ha-card.comfort{background:linear-gradient(135deg,rgba(80,200,115,.16),rgba(24,34,28,.97))}
        ha-card.temp-ok.open,ha-card.temp-ok.idle{background:linear-gradient(135deg,rgba(55,190,105,.13),rgba(25,32,28,.97))} ha-card.temp-warm.open,ha-card.temp-warm.idle{background:linear-gradient(135deg,rgba(255,164,65,.14),rgba(33,29,25,.97))} ha-card.temp-hot{background:linear-gradient(135deg,rgba(255,74,56,.24),rgba(35,25,25,.97))}
        ha-card.paused,ha-card.muted{background:linear-gradient(135deg,rgba(80,120,190,.18),rgba(24,28,36,.97))} ha-card.disabled,ha-card.master:not(.danger):not(.heat){background:linear-gradient(135deg,rgba(185,55,55,.28),rgba(38,22,22,.98))} ha-card.manual:not(.paused):not(.disabled):not(.danger):not(.heat){background:linear-gradient(135deg,rgba(190,62,54,.20),rgba(37,24,24,.97))}
        .icon-box{--icon-box-size:18px;--icon-size:16px;width:var(--icon-box-size);height:var(--icon-box-size);min-width:var(--icon-box-size);flex:0 0 var(--icon-box-size);display:grid;place-items:center;align-content:center;justify-content:center;align-self:center;justify-self:center;vertical-align:middle;line-height:0;margin:0;padding:0;overflow:visible;transform-origin:center}.icon-box>ha-icon{display:grid;place-items:center;width:var(--icon-size);height:var(--icon-size);min-width:var(--icon-size);max-width:var(--icon-size);--mdc-icon-size:var(--icon-size);line-height:0;margin:0;padding:0;transform:none;position:static}.mode-icon{--icon-box-size:16px;--icon-size:14px}.chip-icon{--icon-box-size:14px;--icon-size:12px}.sector-icon{--icon-box-size:18px;--icon-size:14px;opacity:.7}.cover-icon{--icon-box-size:14px;--icon-size:12px}.action-icon{--icon-box-size:18px;--icon-size:16px}.advanced-icon{--icon-box-size:17px;--icon-size:15px}.easy-status-icon{--icon-box-size:18px;--icon-size:16px}.easy-sun-icon{--icon-box-size:30px;--icon-size:23px}.easy-cover-icon{--icon-box-size:24px;--icon-size:18px}
        .wrap{width:100%;padding:16px;display:grid;gap:11px;overflow:hidden}
        .header{display:flex;justify-content:space-between;align-items:flex-start;gap:12px}.heading{flex:1;overflow:hidden}.title{font-size:18px;font-weight:850;line-height:1.08}.room-name{font-size:11px;opacity:.56;margin-top:4px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.important{font-size:11px;opacity:.72;margin-top:4px;line-height:1.3;overflow-wrap:anywhere}
        .mode{display:inline-flex;align-items:center;justify-content:center;gap:6px;padding:6px 10px;border-radius:999px;background:rgba(255,255,255,.10);font-size:10px;font-weight:900;text-transform:uppercase;white-space:nowrap;line-height:1}.danger .mode .mode-icon,.heat .mode .mode-icon,.paused .mode .mode-icon,.disabled .mode .mode-icon,.manual .mode .mode-icon,.active-master .icon-box,.sector-card.active .sector-icon,.cover-row.warning .cover-icon,.easy-cover-row.manual .easy-cover-icon,.calm-pulse{--pulse-transform:translateZ(0);animation:calmPulse 4.2s ease-in-out infinite;transform-origin:center}.sun-dot.calm-pulse{--pulse-transform:translate(-50%,-50%)}@keyframes calmPulse{0%,100%{opacity:.76;transform:var(--pulse-transform) scale(.98)}50%{opacity:1;transform:var(--pulse-transform) scale(1.045)}}
        .chips{display:flex;flex-wrap:wrap;gap:6px}.chip{height:26px;display:inline-flex;align-items:center;justify-content:center;gap:5px;padding:3px 7px;border:0;border-radius:999px;background:rgba(255,255,255,.065);color:inherit;font-size:10px;line-height:1;cursor:pointer}.chip.icon-only{width:26px;padding:0}.parts{display:inline-flex;align-items:center;gap:2px}.mini-part{min-width:19px;height:18px;border:0;padding:0 4px;border-radius:999px;color:inherit;font-size:9px;font-weight:900;line-height:1;cursor:pointer}.mini-part.good{background:rgba(130,220,150,.20)}.mini-part.bad{background:rgba(255,85,70,.38)}.mini-part.sunny{background:rgba(255,196,78,.28)}.mini-part.neutral{background:rgba(255,255,255,.07);opacity:.56}.chip.alert{background:rgba(255,80,66,.19)}
        .sunbox{padding:10px 12px;border-radius:16px;background:rgba(255,255,255,.047);overflow:hidden}.sun-title{display:flex;justify-content:space-between;gap:10px;font-size:11px;font-weight:750}.sun-title span:last-child{font-weight:500;opacity:.55;white-space:nowrap}.track{position:relative;height:31px;margin:6px 0}.track:before{content:"";position:absolute;left:0;right:0;top:50%;height:4px;transform:translateY(-50%);border-radius:99px;background:rgba(255,255,255,.11)}.sector-bar{position:absolute;top:50%;height:7px;transform:translateY(-50%);border-radius:99px;background:rgba(255,183,76,.24)}.sector-bar.ready{height:9px;background:rgba(255,185,72,.55)}.sun-dot{position:absolute;left:${clamp(azimuth / 360 * 100,0,100)}%;top:50%;width:14px;height:14px;transform:translate(-50%,-50%);border-radius:50%;background:#ffe08c;box-shadow:0 0 14px rgba(255,200,75,.35)}.track-labels{display:flex;justify-content:space-between;font-size:9px;opacity:.38}
        .sectors{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(118px,100%),1fr));gap:7px}.sector-card{border:0;border-radius:14px;background:rgba(255,255,255,.047);color:inherit;padding:9px 10px;display:flex;justify-content:space-between;align-items:center;gap:7px;text-align:left;cursor:pointer}.sector-card.active{background:rgba(255,188,72,.12)}.sector-card strong{display:block;font-size:11px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.sector-card small{display:block;font-size:9px;opacity:.57;margin-top:2px}
        .covers{display:grid;gap:7px}.cover-row{padding:7px;border-radius:12px;background:rgba(255,255,255,.018)}.cover-row.warning{background:rgba(255,78,65,.09)}.cover-head{width:100%;border:0;background:none;color:inherit;padding:0;display:flex;align-items:center;justify-content:space-between;gap:9px;cursor:pointer;text-align:left}.cover-name{display:flex;align-items:center;gap:5px;overflow:hidden}.cover-name strong{font-size:11px;font-weight:700;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.values{font-size:10px;opacity:.70;white-space:nowrap;flex:none}.bar{height:5px;border-radius:99px;background:rgba(255,255,255,.10);overflow:hidden;margin-top:5px}.bar.unknown:after{content:"";display:block;width:100%;height:100%;background:rgba(255,255,255,.04)}.bar i{display:block;height:100%;border-radius:inherit;background:rgba(255,255,255,.62)}.bar.tilt{height:3px;margin-top:3px}.bar.tilt i{background:rgba(255,204,102,.58)}.warning .bar i{background:rgba(255,102,87,.78)}.target-line{font-size:9px;opacity:.48;margin-top:4px;overflow-wrap:anywhere}
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
          ${this._config.show_actions !== false ? `<div class="footer"><div class="actions">
            ${paused
              ? (resumeButton?.entity_id ? `<button class="round" data-press="${htmlEscape(resumeButton.entity_id)}" title="${htmlEscape(L.resume)}">${iconBox("mdi:play", "action-icon")}</button>` : "")
              : (pauseButton?.entity_id ? `<button class="round" data-press="${htmlEscape(pauseButton.entity_id)}" title="${htmlEscape(L.pause)}">${iconBox("mdi:pause", "action-icon")}</button>` : "")}
            ${evaluateButton?.entity_id ? `<button class="round" data-press="${htmlEscape(evaluateButton.entity_id)}" title="${htmlEscape(L.evaluate)}">${iconBox("mdi:refresh", "action-icon")}</button>` : ""}
            ${masterButton ? `<button class="round ${attrs.manual_master_active ? "active-master" : ""}" data-press="${htmlEscape(masterButton.entity_id || "")}" title="${htmlEscape(attrs.manual_master_active ? `${L.master}: ON` : `${L.master}: OFF`)}">${iconBox("mdi:hand-back-right", "action-icon")}</button>` : ""}
            ${attrs.night_enabled && attrs.night_source === "entity" && attrs.night_entity && this._state(attrs.night_entity) ? `<button class="round" data-night-source="${htmlEscape(attrs.night_entity)}" title="${htmlEscape(L.nightSchedule)}">${iconBox("mdi:calendar-clock", "action-icon")}</button>` : ""}
            <button class="round advanced-button" data-advanced title="${htmlEscape(L.advanced)}">${iconBox("mdi:tune-variant", "advanced-icon")}<span>${htmlEscape(L.advanced)}</span></button>
          </div></div>` : ""}
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

    this.shadowRoot.querySelectorAll?.("[data-more]").forEach((element) => element.addEventListener("click", (event) => { event.stopPropagation(); this._more(element.dataset.more); }));
    this.shadowRoot.querySelectorAll?.("[data-night-source]").forEach((element) => element.addEventListener("click", (event) => { event.stopPropagation(); this._openNightSource(element.dataset.nightSource); }));
    this.shadowRoot.querySelectorAll?.("[data-press]").forEach((element) => element.addEventListener("click", () => this._callEntity(element.dataset.press)));
    this.shadowRoot.querySelector?.("[data-advanced]")?.addEventListener("click", (event) => this._openAdvanced(roomState, controls, event.currentTarget));
  }

  _messageCard(message) {
    return `<style>:host{display:block;width:100%;max-width:100%}ha-card{padding:18px;border-radius:20px}.message{font-size:13px;opacity:.72}</style><ha-card><div class="message">${htmlEscape(message)}</div></ha-card>`;
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

window.customCards = window.customCards || [];
if (!window.customCards.some((card) => card.type === "smart-shading-card")) {
  window.customCards.push({ type: "smart-shading-card", name: "Smart Shading", description: "Compact Smart Shading room card with optional advanced dialog", preview: true });
}
console.info("%c SMART-SHADING %c loaded ", "color:white;background:#0aa4d6;font-weight:700", "color:#0aa4d6;background:#111");
