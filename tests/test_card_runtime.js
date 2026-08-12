const fs = require("fs");
const vm = require("vm");
const path = require("path");

class FakeNode {
  constructor() { this.isConnected = false; this.dataset = {}; this.dispatchedEvents = []; this.listeners = new Map(); this.focused = false; }
  addEventListener(type, handler) { this.listeners.set(type, handler); }
  setAttribute() {}
  getAttribute() { return ""; }
  focus() { this.focused = true; }
  remove() { this.isConnected = false; this.disconnectedCallback?.(); }
}
class FakeElement extends FakeNode {
  constructor(html = "") { super(); this._innerHTML = ""; this._queryCache = new Map(); this.innerHTML = html; this.scrollTop = 0; }
  set innerHTML(value) { this._innerHTML = String(value || ""); this._queryCache.clear(); }
  get innerHTML() { return this._innerHTML; }
  querySelector(selector) { return this.querySelectorAll(selector)[0] || null; }
  closest(selector) {
    for (const candidate of String(selector).split(",")) {
      const attribute = candidate.trim().match(/^\[data-([a-z-]+)\]$/)?.[1];
      if (!attribute) continue;
      const key = attribute.replace(/-([a-z])/g, (_, letter) => letter.toUpperCase());
      if (Object.hasOwn(this.dataset, key)) return this;
    }
    return null;
  }
  hasAttribute(name) {
    const attribute = String(name).match(/^data-([a-z-]+)$/)?.[1];
    if (!attribute) return false;
    const key = attribute.replace(/-([a-z])/g, (_, letter) => letter.toUpperCase());
    return Object.hasOwn(this.dataset, key);
  }
  querySelectorAll(selector) {
    if (this._queryCache.has(selector)) return this._queryCache.get(selector);
    const attribute = selector.match(/^\[data-([a-z-]+)\]$/)?.[1];
    if (!attribute) return [];
    const key = attribute.replace(/-([a-z])/g, (_, letter) => letter.toUpperCase());
    const pattern = new RegExp(`\\bdata-${attribute}(?:="([^"]*)")?`, "g");
    const nodes = [...this._innerHTML.matchAll(pattern)].map((match) => {
      const node = new FakeElement();
      const tagStart = this._innerHTML.lastIndexOf("<", match.index);
      const tagEnd = this._innerHTML.indexOf(">", match.index);
      const tag = this._innerHTML.slice(tagStart, tagEnd + 1);
      for (const dataMatch of tag.matchAll(/\bdata-([a-z0-9-]+)(?:="([^"]*)")?/g)) {
        const dataKey = dataMatch[1].replace(/-([a-z])/g, (_, letter) => letter.toUpperCase());
        node.dataset[dataKey] = dataMatch[2] || "";
      }
      node.dataset[key] = match[1] || "";
      node.value = tag.match(/\bvalue="([^"]*)"/)?.[1] || "";
      return node;
    });
    this._queryCache.set(selector, nodes);
    return nodes;
  }
}
class FakeShadowRoot extends FakeNode {
  constructor() { super(); this._innerHTML = ""; this._dialog = null; this._main = null; this._badge = null; this._queryCache = new Map(); this.activeElement = null; this.writeCount = 0; }
  set innerHTML(value) {
    this._innerHTML = String(value || "");
    this._queryCache.clear();
    this.writeCount += 1;
    if (this._innerHTML.includes('class="dialog"')) {
      this._dialog = new FakeElement();
      const match = this._innerHTML.match(/<main>([\s\S]*)<\/main>/);
      this._main = new FakeElement(match?.[1] || "");
    } else {
      this._dialog = null;
      this._main = null;
    }
    this._badge = this._innerHTML.includes("<ha-badge") ? new FakeElement() : null;
  }
  get innerHTML() { return this._innerHTML; }
  querySelector(selector) {
    if (selector === ".dialog") return this._dialog;
    if (selector === "main") return this._main;
    if (selector === "ha-badge") return this._badge;
    return null;
  }
  querySelectorAll(selector) {
    if (selector === "[data-close]" && this._dialog) return [new FakeElement(), new FakeElement()];
    if (this._queryCache.has(selector)) return this._queryCache.get(selector);
    if (/^\[data-[a-z-]+\]$/.test(selector)) {
      const nodes = new FakeElement(this._innerHTML).querySelectorAll(selector);
      this._queryCache.set(selector, nodes);
      return nodes;
    }
    return [];
  }
}
class FakeHTMLElement extends FakeNode {
  attachShadow() { this.shadowRoot = new FakeShadowRoot(); return this.shadowRoot; }
  dispatchEvent(event) { this.dispatchedEvents.push(event); return true; }
}
class FakeEvent { constructor(type, options = {}) { this.type = type; Object.assign(this, options); } stopPropagation() {} }
class FakeCustomEvent extends FakeEvent { constructor(type, options = {}) { super(type, options); this.detail = options.detail; } }
const registry = new Map();
const body = {
  children: [],
  appendChild(node) { node.isConnected = true; this.children.push(node); return node; },
};
const documentListeners = new Map();
let dashboardScrollTop = 0;
let dashboardScrollLeft = 0;
let dashboardScrollWrites = 0;
const scrollingElement = { scrollHeight: 2400, clientHeight: 800, scrollWidth: 1200, clientWidth: 1200 };
Object.defineProperties(scrollingElement, {
  scrollTop: {
    get() { return dashboardScrollTop; },
    set(value) { dashboardScrollWrites += 1; dashboardScrollTop = Number(value); },
  },
  scrollLeft: {
    get() { return dashboardScrollLeft; },
    set(value) { dashboardScrollWrites += 1; dashboardScrollLeft = Number(value); },
  },
});
const outsideFocus = { id: "dashboard-search" };
global.HTMLElement = FakeHTMLElement;
global.Event = FakeEvent;
global.CustomEvent = FakeCustomEvent;
global.customElements = {
  define(name, klass) { registry.set(name, klass); },
  get(name) { return registry.get(name); },
};
global.document = {
  body,
  scrollingElement,
  activeElement: outsideFocus,
  createElement(name) {
    const Klass = registry.get(name);
    return Klass ? new Klass() : new FakeHTMLElement();
  },
  addEventListener(type, handler) { documentListeners.set(type, handler); },
  removeEventListener(type, handler) { if (documentListeners.get(type) === handler) documentListeners.delete(type); },
};
global.window = {
  routes: [],
  events: [],
  history: { pushState(_state, _title, route) { global.window.routes.push(route); } },
  dispatchEvent(event) { this.events.push(event); return true; },
};
global.navigator = { clipboard: { writeText: async () => {} } };

const cardPath = path.join(__dirname, "..", "custom_components", "smart_shading", "frontend", "shading.js");
vm.runInThisContext(fs.readFileSync(cardPath, "utf8"), { filename: cardPath });

const Card = registry.get("smart-shading-card");
const Editor = registry.get("smart-shading-card-editor");
const Dialog = registry.get("smart-shading-dialog");
const Badge = registry.get("smart-shading-badge");
const BadgeEditor = registry.get("smart-shading-badge-editor");
if (!Card || !Editor || !Dialog || !Badge || !BadgeEditor) throw new Error("Smart Shading card, badge, editor, or dialog was not registered");
if (!window.customBadges?.some((badge) => badge.type === "smart-shading-badge")) throw new Error("Smart Shading badge was not registered in the dashboard picker");

const editor = new Editor();
editor.setConfig({ entity: "sensor.room_status", advanced_mode: true });
editor.hass = { language: "de", states: {} };
if (editor.shadowRoot.innerHTML.includes("undefined")) throw new Error("Editor rendered undefined");

const roomStatus = {
  entity_id: "sensor.room_status",
  state: "solar",
  attributes: {
    name: "Raum A",
    smart_shading_layout: "detailed",
    smart_shading_entry_id: "entry",
    smart_shading_room_id: "room",
    active_sectors: ["Süd links"],
    reason: "Normal adaptive solar shading",
    targets: [{ entity_id: "cover.internal_identifier", mode: "solar", position: 0, tilt: 65, suppressed: [] }],
    // These are the production wrappers emitted by engine.py, not a
    // convenient flattened test shape. The Card must resolve each layer.
    decision_trace: {
      schema: 1,
      decision: {
        simulation: false,
        mode: "solar",
        target: { position: 0, tilt: 65 },
        trace: {
          winner: { rule: "solar", mode: "solar", reason_code: "protected_zone_target_adjusted", target: { position: 0, tilt: 65 } },
          rejected: [
            { rule: "comfort", mode: "comfort", reason_code: "comfort_inactive", target: { position: 35, tilt: 45 } },
            { rule: "open", mode: "open", reason_code: "open_inactive", target: { position: 100 } },
          ],
          entries: [
            { candidate: { rule: "solar", mode: "solar", reason_code: "protected_zone_target_adjusted", target: { position: 0, tilt: 65 } }, outcome: "winner", resolution_reason_code: "highest_matching_priority" },
            { candidate: { rule: "comfort", mode: "comfort", reason_code: "comfort_inactive", target: { position: 35, tilt: 45 } }, outcome: "rejected", resolution_reason_code: "rule_not_matched" },
            { candidate: { rule: "open", mode: "open", reason_code: "open_inactive", target: { position: 100 } }, outcome: "rejected", resolution_reason_code: "rule_not_matched" },
          ],
          command_result: { status: "sent", reason_code: "cover_command_sent", target: { position: 0, tilt: 65 } },
          protected_zones: [],
          input_snapshot: {
            evaluated_at: "2026-07-14T12:00:00+00:00",
            inputs: {
              sun_elevation: { value: 35, unit: "°", quality: "valid", reason_code: "input_valid" },
              lux: { value: 26398.72, unit: "lx", quality: "stale", reason_code: "input_stale" },
            },
          },
        },
      },
      target_decisions: [{
        sector_id: "south_left",
        layer_id: "layer",
        layer_name: "Behanggruppe",
        decision: {
          simulation: false,
          mode: "solar",
          target: { position: 0, tilt: 65 },
          trace: {
            winner: { rule: "solar", mode: "solar", reason_code: "protected_zone_target_adjusted", target: { position: 0, tilt: 65 } },
            rejected: [{ rule: "open", mode: "open", reason_code: "open_inactive", target: { position: 100 } }],
            command_result: { status: "sent", reason_code: "cover_command_sent", target: { position: 0, tilt: 65 } },
            protected_zones: [{ zone_id: "desk", name: "Schreibtisch", sector_id: "south_left", status: "hit", reason_code: "protected_zone_direct_sun_hit", target: { position: 0, tilt: 65 } }],
            input_snapshot: { inputs: {} },
          },
        },
      }],
      command_results: [{ cover_id: "cover_one", status: "sent", reason_code: "cover_command_sent", lifecycle_id: "lifecycle-1" }],
    },
    simulation_active: true,
    simulation_trace: {
      schema: 1,
      results: [{
        sector_id: "south_left",
        layer_id: "layer",
        cover_targets: [{
          cover_id: "cover_one",
          name: "Fenstergruppe",
          command_position: 0,
          command_tilt: 65,
          constraints: ["automation_lock"],
          command_result: "blocked",
          reason_code: "automation_lock",
        }],
        result: {
          simulation: true,
          mode: "solar",
          target: { position: 0, tilt: 65 },
          trace: {
            winner: { rule: "solar", mode: "solar", reason_code: "protected_zone_target_adjusted", target: { position: 0, tilt: 65 } },
            command_result: { status: "simulated", reason_code: "simulation_never_executes_services", target: { position: 0, tilt: 65 } },
          },
        },
      }, {
        sector_id: "west_window",
        layer_id: "blackout_layer",
        result: {
          simulation: true,
          mode: "comfort",
          target: { position: 42 },
          trace: {
            winner: { rule: "comfort", mode: "comfort", reason_code: "input_quality_hold", target: { position: 42 } },
            command_result: { status: "simulated", reason_code: "simulation_never_executes_services", target: { position: 42 } },
          },
        },
      }],
    },
    day_preview: {
      schema: 1,
      preview: {
        day: "2026-07-14",
        samples: [{ at: "2026-07-14T08:00:00+00:00" }, { at: "2026-07-14T12:00:00+00:00" }],
        transitions: [{ at: "2026-07-14T12:00:00+00:00", previous_mode: "open", mode: "solar", target: { position: 0, tilt: 65 }, reason_code: "decision_changed" }],
      },
    },
    schedule_active: true,
    pause_mode: "auto",
    manual_master_active: false,
    cover_pauses: [{ entity_id: "cover.internal_identifier", name: "Fenstergruppe", short: "B1", active: true, until: "2026-07-16T05:30:00+02:00", reason: "external_or_physical_control" }],
    sent_commands: 2,
    suppressed_commands: 1,
    night_enabled: true,
    night_active: false,
    night_source: "entity",
    night_entity: "schedule.room_night",
    night_source_state: "off",
    easy_confirmation_state: "confirmed",
    easy_source_summary: "Binary sensor",
    outdoor_temperature_condition: { enabled: true, source_entity: "sensor.outdoor", value: 24.5, minimum: 18, passed: true },
    diagnostic_events: [
      { timestamp: "2026-07-14T12:00:00+00:00", event: "room_mode_changed", room_id: "room", previous: "idle", mode: "solar" },
      { timestamp: "2026-07-14T12:01:00+00:00", event: "room_evaluated", room_id: "room", room: "Raum A", mode: "solar", reason: "solar_conditions_matched", active_sectors: ["Süd links"], targets: 1 },
    ],
    sector_statuses: [{ id: "south_left", name: "Süd links", short: "S1", status: "shading_active", reason: "Normal shading", geometry_active: true, sun_presence: true, confirmation_source: "binary", confirmation_entity: "binary_sensor.south_sun_presence", confirmation_state: true, effective_active: true, lux: 26398.72, lux_raw_state: "26398.72", lux_unit: "lx", sun_settings: { sun_on_lux: 18000, sun_off_lux: 9000, sun_on_delay: 3, sun_off_delay: 12 }, pending_target: null, pending_until: null, mode: "solar", sun_presence_entity_id: "binary_sensor.south_sun_presence" }],
    configuration: {
      indoor_temperature: "sensor.room_temperature",
      sun_entity: "sun.sun",
      safety_blockers: [],
      sectors: [{
        id: "south_left", name: "Süd links", short: "S1", azimuth_start: 120, azimuth_end: 240,
        layers: [{ name: "Behanggruppe", profile: "venetian", covers: [{ entity: "cover.internal_identifier", name: "Fenstergruppe", short: "B1", lock: "switch.cover_lock", window: "binary_sensor.window_contact", window_safe_state: "on" }] }],
      }],
    },
  },
};

const hass = {
  language: "de",
  states: {
    "sun.sun": { entity_id: "sun.sun", state: "above_horizon", attributes: { azimuth: 180, elevation: 35 } },
    "sensor.room_temperature": { entity_id: "sensor.room_temperature", state: "25.4", attributes: { unit_of_measurement: "°C" } },
    "cover.internal_identifier": { entity_id: "cover.internal_identifier", state: "open", attributes: { friendly_name: "Technischer Name (HAUS-LANG-ID)", current_position: 100, current_tilt_position: 100 } },
    "switch.cover_lock": { entity_id: "switch.cover_lock", state: "on", attributes: { friendly_name: "Automatiksperre" } },
    "binary_sensor.window_contact": { entity_id: "binary_sensor.window_contact", state: "on", attributes: { friendly_name: "Fensterkontakt" } },
    "binary_sensor.south_sun_presence": { entity_id: "binary_sensor.south_sun_presence", state: "on", attributes: { friendly_name: "Süd links Sonne erkannt" } },
    "schedule.room_night": { entity_id: "schedule.room_night", state: "off", attributes: { friendly_name: "Nachtzeitplan" } },
    "sensor.room_status": roomStatus,
    "sensor.house_status": { entity_id: "sensor.house_status", state: "solar", attributes: {
      name: "My house", smart_shading_entry_id: "entry", rooms: [
        { id: "room", name: "Living room", mode: "solar", enabled: true, pause_mode: "auto", pause_until: null, night_active: false },
        { id: "office", name: "Office", mode: "paused", enabled: true, pause_mode: "timed", pause_until: "2031-06-21T18:30:00+00:00", night_active: false },
      ],
    } },
    "button.pause": { entity_id: "button.pause", state: "unknown", attributes: { smart_shading_entry_id: "entry", smart_shading_room_id: "room", smart_shading_control_key: "pause_default" } },
    "button.resume": { entity_id: "button.resume", state: "unknown", attributes: { smart_shading_entry_id: "entry", smart_shading_room_id: "room", smart_shading_control_key: "resume" } },
    "button.evaluate": { entity_id: "button.evaluate", state: "unknown", attributes: { smart_shading_entry_id: "entry", smart_shading_room_id: "room", smart_shading_control_key: "evaluate" } },
    "button.simulate": { entity_id: "button.simulate", state: "unknown", attributes: { smart_shading_entry_id: "entry", smart_shading_room_id: "room", smart_shading_control_key: "simulate" } },
    "button.preview": { entity_id: "button.preview", state: "unknown", attributes: { smart_shading_entry_id: "entry", smart_shading_room_id: "room", smart_shading_control_key: "preview_day" } },
    "switch.master": { entity_id: "switch.master", state: "off", attributes: { smart_shading_entry_id: "entry", smart_shading_room_id: "room", smart_shading_control_key: "manual_master" } },
  },
  calls: [],
  wsCalls: [],
  callService: async function(domain, service, data) { this.calls.push({ domain, service, data }); },
  callWS: async function(request) {
    this.wsCalls.push(request);
    if (request.type === "config/entity_registry/get" && request.entity_id === "schedule.room_night") {
      return { config_entry_id: "schedule-entry" };
    }
    throw new Error("Entity registry entry unavailable");
  },
};

const roomBadge = new Badge();
roomBadge.setConfig({ entity: "sensor.room_status" });
roomBadge.hass = { ...hass, language: "en", states: {
  ...hass.states,
  "sensor.room_status": { ...roomStatus, state: "paused", attributes: {
    ...roomStatus.attributes, pause_mode: "timed", pause_until: "2031-06-21T18:30:00+00:00",
  } },
} };
if (!roomBadge.shadowRoot.innerHTML.includes('<ha-badge type="button" icon-only data-mode="paused"')
  || !roomBadge.shadowRoot.innerHTML.includes('class="cover-symbol" icon="mdi:blinds-horizontal"')
  || !roomBadge.shadowRoot.innerHTML.includes('class="state-marker"><ha-icon icon="mdi:pause"')
  || !roomBadge.shadowRoot.innerHTML.includes("Paused until")
  || !roomBadge.shadowRoot.innerHTML.includes("Raum A")) throw new Error("Room badge was not rendered as a native round timed-pause badge");
roomBadge.shadowRoot.querySelector("ha-badge")?.listeners.get("click")?.(new FakeEvent("click"));
if (roomBadge.dispatchedEvents.at(-1)?.detail?.entityId !== "sensor.room_status") throw new Error("Room badge did not open its status entity");

const houseBadge = new Badge();
houseBadge.setConfig({ entity: "sensor.house_status" });
houseBadge.hass = { ...hass, language: "en" };
if (!houseBadge.shadowRoot.innerHTML.includes('<ha-badge type="button" icon-only data-mode="paused"')
  || !houseBadge.shadowRoot.innerHTML.includes('class="cover-symbol" icon="mdi:blinds-horizontal"')
  || !houseBadge.shadowRoot.innerHTML.includes('class="state-marker"><ha-icon icon="mdi:pause"')
  || !houseBadge.shadowRoot.innerHTML.includes("Paused until")
  || !houseBadge.shadowRoot.innerHTML.includes("My house")) throw new Error("House badge did not prioritize and aggregate its paused room in the native badge");
const badgeStub = Badge.getStubConfig(hass);
if (badgeStub.entity !== "sensor.room_status") throw new Error("Badge picker did not preselect an available Smart Shading status entity");

const badgeEditor = new BadgeEditor();
badgeEditor.setConfig({ entity: "sensor.house_status" });
badgeEditor.hass = { ...hass, language: "en" };
if (!badgeEditor.shadowRoot.innerHTML.includes("My house (House)") || !badgeEditor.shadowRoot.innerHTML.includes("Raum A (Room)")) throw new Error("Badge editor did not offer house and room status entities");
if (!badgeEditor.shadowRoot.innerHTML.includes("main symbol always shows the cover type")) throw new Error("Badge editor did not explain the cover symbol and state marker behavior");

const curtainHeatBadge = new Badge();
curtainHeatBadge.setConfig({ entity: "sensor.curtain_status" });
curtainHeatBadge.hass = { ...hass, language: "en", states: {
  ...hass.states,
  "sensor.curtain_status": { ...roomStatus, entity_id: "sensor.curtain_status", state: "heat", attributes: {
    ...roomStatus.attributes,
    pause_mode: "auto",
    configuration: { sectors: [{ layers: [{ profile: "curtain", covers: [] }] }] },
  } },
} };
if (!curtainHeatBadge.shadowRoot.innerHTML.includes('class="cover-symbol" icon="mdi:curtains-closed"')
  || !curtainHeatBadge.shadowRoot.innerHTML.includes('class="state-marker"><ha-icon icon="mdi:thermometer-high"')) throw new Error("Badge did not combine the configured cover profile with its heat state marker");

const badgeModeCases = {
  idle: ["idle", "mdi:auto-mode"], open: ["open", "mdi:auto-mode"], comfort: ["comfort", "mdi:account-check-outline"],
  solar: ["solar", "mdi:weather-sunny"], glare: ["glare", "mdi:eye-outline"], heat: ["heat", "mdi:thermometer-high"],
  night: ["night", "mdi:weather-night"], paused: ["paused", "mdi:pause"], safety: ["safety", "mdi:shield-alert"],
  manual: ["disabled", "mdi:hand-back-right"], finished: ["finished", "mdi:check"], unavailable: ["unavailable", "mdi:alert-circle-outline"],
};
for (const [requestedMode, [renderedMode, marker]] of Object.entries(badgeModeCases)) {
  const modeBadge = new Badge();
  const entityId = `sensor.badge_${requestedMode}`;
  modeBadge.setConfig({ entity: entityId });
  modeBadge.hass = { ...hass, language: "en", states: { ...hass.states, [entityId]: {
    ...roomStatus, entity_id: entityId, state: requestedMode === "manual" ? "idle" : requestedMode, attributes: {
      ...roomStatus.attributes,
      manual_master_active: requestedMode === "manual",
      pause_mode: requestedMode === "paused" ? "timed" : "auto",
      pause_until: requestedMode === "paused" ? "2031-06-21T18:30:00+00:00" : null,
      configuration: { sectors: [{ layers: [{ profile: "roller_shutter", covers: [] }] }] },
    },
  } } };
  const expectedCoverIcon = ["comfort", "solar", "glare", "heat", "night", "safety"].includes(renderedMode)
    ? "mdi:window-shutter" : "mdi:window-shutter-open";
  if (!modeBadge.shadowRoot.innerHTML.includes(`data-mode="${renderedMode}"`)
    || !modeBadge.shadowRoot.innerHTML.includes(`class="cover-symbol" icon="${expectedCoverIcon}"`)
    || !modeBadge.shadowRoot.innerHTML.includes(`class="state-marker"><ha-icon icon="${marker}"`)) throw new Error(`Badge mode ${requestedMode} lost its cover identity or state marker`);
}

const card = new Card();
card.setConfig({ entity: "sensor.room_status", advanced_mode: true });
card.hass = hass;
const html = card.shadowRoot.innerHTML;
if (!html.includes("Raum A") || !html.includes("Fenstergruppe") || !html.includes("Süd links")) throw new Error("Card did not render configured display names");
const visibleHtml = html.replace(/data-(?:more|press|toggle|number|select)="[^"]*"/g, "");
if (visibleHtml.includes("cover.internal_identifier")) throw new Error("Card exposed a raw cover entity ID as visible content");
if (html.includes("undefined")) throw new Error("Card rendered undefined");
if (!html.includes('data-card-mode="advanced"') || !html.includes("data-advanced-layout") || !html.includes("data-advanced-sectors")) throw new Error("Advanced card did not use its dedicated layout");
if (html.includes("data-decision-trace") || html.includes('data-press="button.simulate"') || html.includes('data-press="button.preview"')) throw new Error("Advanced card exposed decision diagnostics or test controls outside the details view");
if (!html.includes("overflow-anchor:none")) throw new Error("Card did not opt out of dashboard scroll anchoring during live updates");
const focusedAdvancedEntrance = card.shadowRoot.querySelectorAll("[data-advanced]")[0];
card.shadowRoot.activeElement = focusedAdvancedEntrance;
const cardWritesBeforeNoopRender = card.shadowRoot.writeCount;
card._render();
if (card.shadowRoot.querySelectorAll("[data-advanced]")[0] !== focusedAdvancedEntrance) throw new Error("Unchanged card state replaced its focused control");
if (card.shadowRoot.writeCount !== cardWritesBeforeNoopRender) throw new Error("Visually unchanged card state rebuilt the dashboard DOM");
if (!html.includes("sunbox") || !html.includes("sector-card") || !html.includes("cover-row")) throw new Error("Advanced reference structure missing");
if (!html.includes("Pausiert")) throw new Error("Local cover pause was not rendered");
if (!html.includes(".icon-box") || !html.includes("place-items:center;align-content:center;justify-content:center") || !html.includes("--icon-size:12px") || !html.includes("--icon-size:15px")) throw new Error("Shared mathematical icon centering is missing");
if (!html.includes('data-night-source="schedule.room_night"')) throw new Error("Advanced card did not expose the Night schedule shortcut");
if (!html.includes("@keyframes calmPulse") || html.includes("@keyframes cardGlow") || html.includes("@keyframes sunPulse") || html.includes("filter:brightness")) throw new Error("Card did not use the single calm opacity/transform pulse");
if (!html.includes("@media(prefers-reduced-motion:reduce)") || !html.includes("@container shading-card")) throw new Error("Reduced-motion or container-query fallback is missing");
if (!html.includes("Sonne · Sonnensensor")) throw new Error("Advanced sun feedback did not name its effective source");
const cardMarkup = html.slice(html.indexOf("</style>") + 8);
if (/<button[^>]*>\s*<ha-icon/i.test(cardMarkup)) throw new Error("A card button bypassed the shared icon box");
const detailsOnlyCard = new Card();
detailsOnlyCard.setConfig({ entity: "sensor.room_status", advanced_mode: true, show_actions: false });
detailsOnlyCard.hass = hass;
const detailsOnlyHtml = detailsOnlyCard.shadowRoot.innerHTML;
const detailsOnlyEntrances = detailsOnlyHtml.match(/data-advanced(?=[\s>])/g) || [];
if (detailsOnlyEntrances.length !== 1 || !detailsOnlyHtml.includes("data-advanced-layout")) throw new Error("Advanced details were not reachable when ordinary action buttons were hidden");
if (detailsOnlyHtml.includes('data-press="button.pause"') || detailsOnlyHtml.includes('data-press="button.evaluate"') || detailsOnlyHtml.includes('data-press="button.simulate"') || detailsOnlyHtml.includes('data-press="button.preview"')) throw new Error("show_actions=false still rendered active automation controls");
card._callEntity("switch.master");
if (!hass.calls.some((call) => call.domain === "switch" && call.service === "toggle" && call.data.entity_id === "switch.master")) throw new Error("Master switch was not toggled");

async function runAsyncChecks() {
await card._openNightSource("schedule.room_night");
if (!hass.wsCalls.some((request) => request.type === "config/entity_registry/get" && request.entity_id === "schedule.room_night")) throw new Error("Schedule shortcut did not resolve the helper registry entry");
if (window.routes.at(-1) !== "/config/helpers/edit/schedule-entry" || window.events.at(-1)?.type !== "location-changed") throw new Error("Schedule shortcut did not navigate to the real schedule helper editor");
await card._openNightSource("binary_sensor.night_source");
const fallbackEvent = card.dispatchedEvents.at(-1);
if (fallbackEvent?.detail?.entityId !== "binary_sensor.night_source" || fallbackEvent.detail?.view) throw new Error("Non-schedule Night source did not retain the More Info fallback");

// Keep this intentionally minimal instead of cloning the Advanced status.
// It proves that Easy Mode consumes neither the Issue 79 trace payload nor
// Advanced-only buttons when those entities are absent in a real installation.
const easyRoomStatus = {
  entity_id: "sensor.easy_room_status",
  state: "solar",
  attributes: {
    name: "Einfacher Raum",
    smart_shading_layout: "compact",
    smart_shading_entry_id: "entry",
    smart_shading_room_id: "easy_room",
    active_sectors: ["Süd links"],
    reason: "Normal adaptive solar shading",
    targets: [{ entity_id: "cover.internal_identifier", mode: "solar", position: 0, tilt: 65, suppressed: [] }],
    schedule_active: true,
    manual_master_active: false,
    cover_pauses: [],
    easy_confirmation_state: "confirmed",
    easy_source_summary: "Binary sensor",
    outdoor_temperature_condition: { enabled: true, source_entity: "sensor.outdoor", value: 24.5, minimum: 18, passed: true },
    sector_statuses: [{ id: "south_left", name: "Süd links", short: "S1", status: "shading_active", geometry_active: true, sun_presence: true, confirmation_source: "binary", confirmation_entity: "binary_sensor.south_sun_presence", confirmation_state: true, effective_active: true }],
    configuration: roomStatus.attributes.configuration,
  },
};
hass.states[easyRoomStatus.entity_id] = easyRoomStatus;
hass.states["switch.easy_master"] = { entity_id: "switch.easy_master", state: "off", attributes: { smart_shading_entry_id: "entry", smart_shading_room_id: "easy_room", smart_shading_control_key: "manual_master" } };
const easyCard = new Card();
easyCard.setConfig({ entity: easyRoomStatus.entity_id });
easyCard.hass = hass;
const easyHtml = easyCard.shadowRoot.innerHTML;
const easyMarkup = easyHtml.slice(easyHtml.indexOf("</style>") + 8);
if (!easyHtml.includes('data-card-mode="easy"') || !easyHtml.includes("data-easy-layout") || !easyHtml.includes("data-easy-sun") || !easyHtml.includes("data-easy-covers")) throw new Error("Easy card did not use its dedicated minimal layout");
if (!easyHtml.includes("Sonne im Sektor") || !easyHtml.includes("Sonne · Sonnensensor") || easyHtml.includes("Az 180°")) throw new Error("Easy effective source/status feedback was not compact and simplified");
if (!easyHtml.includes("easy-cover-row") || !easyHtml.includes("Fenstergruppe") || !easyHtml.includes("100%")) throw new Error("Easy card did not render compact cover feedback");
if (easyHtml.includes("data-advanced-layout") || easyHtml.includes("data-advanced-sectors") || easyHtml.includes("data-night-source") || easyHtml.includes('data-press="button.pause"')) throw new Error("Easy card exposed Advanced-only controls or details");
if (easyMarkup.includes("data-decision-trace") || easyMarkup.includes("data-simulation-result") || easyMarkup.includes('data-press="button.simulate"') || easyMarkup.includes('data-press="button.preview"') || easyMarkup.includes("Schreibtisch")) throw new Error("Easy card exposed Issue 79 trace, protected-zone, or simulation data");
if (easyHtml.includes("Neu auswerten") || !easyHtml.includes("Manuelle Sperre")) throw new Error("Easy card did not limit actions to indefinite Manual Override");
if ((easyHtml.match(/class="easy-action/g) || []).length !== 2) throw new Error("Easy card rendered more than its single action (CSS selector excluded)");

const availableSunState = hass.states["sun.sun"];
hass.states["sun.sun"] = { entity_id: "sun.sun", state: "unavailable", attributes: {} };
const unavailableSunCard = new Card();
unavailableSunCard.setConfig({ entity: easyRoomStatus.entity_id });
unavailableSunCard.hass = hass;
const unavailableSunMarkup = unavailableSunCard.shadowRoot.innerHTML.slice(unavailableSunCard.shadowRoot.innerHTML.indexOf("</style>") + 8);
if (!unavailableSunMarkup.includes("Sonnenstatus nicht verfügbar") || !unavailableSunMarkup.includes("mdi:help-circle-outline")) throw new Error("Unavailable sun feedback was not explicit");
if (unavailableSunMarkup.includes('class="sun-dot')) throw new Error("Unavailable sun feedback rendered a misleading sun position dot");
hass.states["sun.sun"] = availableSunState;

const safetyStatus = JSON.parse(JSON.stringify(roomStatus));
safetyStatus.entity_id = "sensor.safety_room_status";
safetyStatus.state = "safety";
safetyStatus.attributes.active_sectors = ["stale sector"];
safetyStatus.attributes.sector_statuses[0].status = "safety";
safetyStatus.attributes.sector_statuses[0].effective_active = false;
hass.states[safetyStatus.entity_id] = safetyStatus;
const safetyCard = new Card();
safetyCard.setConfig({ entity: safetyStatus.entity_id });
safetyCard.hass = hass;
const safetyMarkup = safetyCard.shadowRoot.innerHTML.slice(safetyCard.shadowRoot.innerHTML.indexOf("</style>") + 8);
if (safetyMarkup.includes("sector-card active") || safetyMarkup.includes('class="sun-dot calm-pulse"')) throw new Error("Geometry, Safety, or Heat falsely activated confirmed-sun visuals");
if (!safetyMarkup.includes("Safety · Blockiert") || safetyMarkup.includes("Safety · stale sector")) throw new Error("Advanced mode label leaked stale active sectors");

const glareStatus = JSON.parse(JSON.stringify(roomStatus));
glareStatus.entity_id = "sensor.glare_room_status";
glareStatus.state = "glare";
glareStatus.attributes.reason = "Direct sun reaches a configured protected area";
glareStatus.attributes.targets[0] = {
  ...glareStatus.attributes.targets[0],
  decision_mode: "glare",
  ordinary_target: { position: 65 },
  final_target: { position: 28 },
  position: 28,
  protected_zone_applied_ids: ["desk"],
  protected_zone_calculations: [{
    zone_id: "desk",
    name: "Schreibtisch",
    status: "hit",
    reason_code: "protected_zone_direct_sun_hit",
    target: { position: 28 },
    details: {
      calculation: "top_down",
      relative_azimuth_degrees: 15,
      projected_height_range_m: [0.35, 0.92],
    },
  }],
};
hass.states[glareStatus.entity_id] = glareStatus;
const glareCard = new Card();
glareCard.setConfig({ entity: glareStatus.entity_id });
glareCard.hass = hass;
const glareMarkup = glareCard.shadowRoot.innerHTML.slice(glareCard.shadowRoot.innerHTML.indexOf("</style>") + 8);
if (!glareMarkup.includes("Blendschutz") || glareMarkup.includes("Schutzzone")) throw new Error("Advanced card did not keep glare visible while reserving protected-zone diagnostics for Details");
const glareDialog = new Dialog();
glareDialog._hass = hass;
glareDialog._roomState = glareStatus;
glareDialog._controls = card._controls(glareStatus);
glareDialog._render();
if (!glareDialog.shadowRoot.innerHTML.includes("Aktuelle Berechnung")
  || !glareDialog.shadowRoot.innerHTML.includes("Normales Ziel")
  || !glareDialog.shadowRoot.innerHTML.includes("Schutzziel")
  || !glareDialog.shadowRoot.innerHTML.includes("Endgültiges Ziel")
  || !glareDialog.shadowRoot.innerHTML.includes("Schreibtisch")
  || !glareDialog.shadowRoot.innerHTML.includes("28%")) throw new Error("Glare diagnostics did not show the calculation, ordinary target, zone target, and final target");

const unknownCoverState = hass.states["cover.internal_identifier"];
hass.states["cover.internal_identifier"] = { entity_id: "cover.internal_identifier", state: "unknown", attributes: { friendly_name: "Technischer Name" } };
const unknownCard = new Card();
unknownCard.setConfig({ entity: easyRoomStatus.entity_id });
unknownCard.hass = hass;
const unknownMarkup = unknownCard.shadowRoot.innerHTML.slice(unknownCard.shadowRoot.innerHTML.indexOf("</style>") + 8);
if (!unknownMarkup.includes('easy-cover-value">–</strong>') || unknownMarkup.includes('easy-cover-value">0%</strong>')) throw new Error("Unknown cover position was rendered as a real zero percent value");
hass.states["cover.internal_identifier"] = unknownCoverState;

const sunNightStatus = JSON.parse(JSON.stringify(roomStatus));
sunNightStatus.entity_id = "sensor.sun_night_status";
sunNightStatus.attributes.night_source = "sun";
sunNightStatus.attributes.night_entity = "schedule.stale_schedule";
hass.states[sunNightStatus.entity_id] = sunNightStatus;
const sunNightCard = new Card();
sunNightCard.setConfig({ entity: sunNightStatus.entity_id });
sunNightCard.hass = hass;
const sunNightMarkup = sunNightCard.shadowRoot.innerHTML.slice(sunNightCard.shadowRoot.innerHTML.indexOf("</style>") + 8);
if (sunNightMarkup.includes("data-night-source") || sunNightMarkup.includes("sun.sun\" title=\"Nachtzeitplan")) throw new Error("Sun-based Night Mode exposed a stale or synthetic schedule shortcut");

const noControlStatus = JSON.parse(JSON.stringify(roomStatus));
noControlStatus.entity_id = "sensor.no_control_status";
noControlStatus.attributes.smart_shading_room_id = "room_without_controls";
hass.states[noControlStatus.entity_id] = noControlStatus;
const noControlCard = new Card();
noControlCard.setConfig({ entity: noControlStatus.entity_id });
noControlCard.hass = hass;
const noControlMarkup = noControlCard.shadowRoot.innerHTML.slice(noControlCard.shadowRoot.innerHTML.indexOf("</style>") + 8);
if (noControlMarkup.includes('data-press=""')) throw new Error("Missing control entities produced clickable no-op buttons");
if (!noControlMarkup.includes("data-advanced")) throw new Error("Advanced view disappeared when optional controls were missing");

const advancedButton = new FakeElement();
advancedButton.dataset.advanced = "";
advancedButton.matches = (selector) => selector.includes("[data-advanced]");
const delegatedClick = card.shadowRoot.listeners.get("click");
if (!delegatedClick) throw new Error("Card did not register its stable delegated click handler");
delegatedClick({
  target: { closest() { return null; } },
  composedPath() { return [advancedButton, card.shadowRoot]; },
  stopPropagation() {},
});
if (!body.children.length) throw new Error("Advanced dialog was not appended to document.body");
const dialog = body.children[0];
if (!dialog.shadowRoot.innerHTML.includes("Smart Shading · Details")) throw new Error("Details dialog did not render");
if (!dialog.shadowRoot.innerHTML.includes("26") || !dialog.shadowRoot.innerHTML.includes("18") || !dialog.shadowRoot.innerHTML.includes("Pausiert")) throw new Error("Advanced dialog missed lux or local pause details");
if (!dialog.shadowRoot.innerHTML.includes("Was passiert gerade?") || !dialog.shadowRoot.innerHTML.includes("Warum?") || !dialog.shadowRoot.innerHTML.includes("data-test-tools") || !dialog.shadowRoot.innerHTML.includes("Technische Supportdaten") || !dialog.shadowRoot.innerHTML.includes("Schreibtisch") || !dialog.shadowRoot.innerHTML.includes("Tagvorschau")) throw new Error("Advanced dialog did not separate customer explanation, tools, and technical support data");
const simulationRows = dialog.shadowRoot.innerHTML.match(/data-simulation-result(?=[\s>])/g) || [];
if (simulationRows.length !== 2
  || !dialog.shadowRoot.innerHTML.includes("South Left · Layer")
  || !dialog.shadowRoot.innerHTML.includes("West Window · Blackout Layer")
  || !dialog.shadowRoot.innerHTML.includes("Gewinner: Sonnenschutz")
  || !dialog.shadowRoot.innerHTML.includes("Gewinner: Komfort")
  || !dialog.shadowRoot.innerHTML.includes("Position: 0%")
  || !dialog.shadowRoot.innerHTML.includes("Position: 42%")
  || !dialog.shadowRoot.innerHTML.includes("Ziel durch Schutzzone angepasst")
  || !dialog.shadowRoot.innerHTML.includes("Halten wegen Eingabequalität")
  || !dialog.shadowRoot.innerHTML.includes("Fenstergruppe")
  || !dialog.shadowRoot.innerHTML.includes("Manuell gesperrt")) throw new Error("Advanced simulation did not render every sector/layer outcome with winner, target, status, and constrained cover projection");
if (!dialog.shadowRoot.innerHTML.includes('data-tool-press="button.simulate"') || !dialog.shadowRoot.innerHTML.includes("data-preview-day") || dialog.shadowRoot.innerHTML.includes("data-preview-fallback")) throw new Error("Advanced dialog missed explicit simulation or selected-date preview controls");
if (!dialog.shadowRoot.innerHTML.includes("data-preview-date") || !dialog.shadowRoot.innerHTML.includes("data-simulation-cover-targets")) throw new Error("Advanced dialog missed selected-date preview or per-cover simulation details");
if (!dialog.shadowRoot.innerHTML.includes('data-night-source="schedule.room_night"')) throw new Error("Advanced dialog did not expose the Night schedule editor shortcut");
if (!dialog.shadowRoot.innerHTML.includes("100dvh") || !dialog.shadowRoot.innerHTML.includes("button[data-close]{display:grid;place-items:center")) throw new Error("Advanced dialog mobile viewport or close-icon centering hardening is missing");
if (!dialog.shadowRoot.innerHTML.includes("overflow:auto;overflow-anchor:none")) throw new Error("Advanced dialog did not disable native scroll anchoring during live content replacement");
if (!dialog.shadowRoot.innerHTML.includes("Raumstatus aktualisiert") || !dialog.shadowRoot.innerHTML.includes("Modus: Sonnenschutz") || !dialog.shadowRoot.innerHTML.includes("Behangziele: 1") || dialog.shadowRoot.innerHTML.includes("room_evaluated")) throw new Error("Diagnostic journal did not present room evaluation events in customer-friendly language");
if (!dialog.shadowRoot.innerHTML.includes("Höchste passende Priorität") || !dialog.shadowRoot.innerHTML.includes("Regel nicht zutreffend") || !dialog.shadowRoot.innerHTML.includes("Komfortbedingungen nicht aktiv") || !dialog.shadowRoot.innerHTML.includes("Öffnungsregel nicht aktiv") || !dialog.shadowRoot.innerHTML.includes("Eingabe gültig") || !dialog.shadowRoot.innerHTML.includes("Eingabe veraltet") || !dialog.shadowRoot.innerHTML.includes("Behangbefehl gesendet")) throw new Error("Advanced dialog did not localize the production candidate, input, command, and resolution trace codes");
if (dialog.shadowRoot.innerHTML.includes("automation_lock") || dialog.shadowRoot.innerHTML.includes("outside_sun_sector") || dialog.shadowRoot.innerHTML.includes("highest_matching_priority") || dialog.shadowRoot.innerHTML.includes("rule_not_matched")) throw new Error("Advanced dialog exposed raw internal reason keys");
const germanTraceLabels = {
  no_cover_target: "Kein Behangziel",
  room_or_cover_pause_active: "Raum- oder Behangpause aktiv",
  night_mode_active: "Nachtfunktion aktiv",
  solar_conditions_matched: "Sonnenschutzbedingungen erfüllt",
  comfort_conditions_matched: "Komfortbedingungen erfüllt",
  open_target_selected: "Öffnungsziel ausgewählt",
  conditions_waiting: "Wartet auf Bedingungen",
  decision_selected: "Entscheidung ausgewählt",
  room_automation_disabled: "Raumautomatik deaktiviert",
  target_confirmed_by_trusted_feedback: "Ziel durch verlässliche Rückmeldung bestätigt",
  cover_removed_before_execution: "Behang vor Ausführung entfernt",
  cover_entity_missing: "Behang-Entität fehlt",
  cover_service_failed: "Behang-Service fehlgeschlagen",
  position_control_unsupported: "Positionssteuerung nicht unterstützt",
  tilt_control_unsupported: "Lamellensteuerung nicht unterstützt",
  command_lifecycle_updated: "Befehlslebenszyklus aktualisiert",
  night_source_hold: "Nachtquelle hält",
  schedule_hold: "Zeitplan hält",
};
for (const [code, label] of Object.entries(germanTraceLabels)) {
  if (dialog._traceText(code) !== label) throw new Error(`Missing German trace translation for ${code}`);
}
const dialogHass = dialog._hass;
dialog._hass = { ...hass, language: "en" };
const englishTraceLabels = {
  no_cover_target: "No cover target",
  target_confirmed_by_trusted_feedback: "Target confirmed by trusted feedback",
  cover_service_failed: "Cover service failed",
  night_source_hold: "Night source hold",
  schedule_hold: "Schedule hold",
};
for (const [code, label] of Object.entries(englishTraceLabels)) {
  if (dialog._traceText(code) !== label) throw new Error(`Missing English trace translation for ${code}`);
}
dialog._hass = dialogHass;
const previewInput = dialog.shadowRoot.querySelector("main").querySelector("[data-preview-date]");
const previewAction = dialog.shadowRoot.querySelector("main").querySelector("[data-preview-day]");
if (!previewInput || !previewAction || previewAction.dataset.previewFallback) throw new Error("Preview controls were not queryable in the card runtime");
previewInput.value = "2031-06-21";
dialog.shadowRoot.listeners.get("change")?.({ target: previewInput });
dialog.shadowRoot.listeners.get("click")?.({ target: previewAction });
const previewServiceCall = hass.calls.at(-1);
if (previewServiceCall?.domain !== "smart_shading" || previewServiceCall.service !== "preview_day" || previewServiceCall.data?.room_id !== "room" || previewServiceCall.data?.entry_id !== "entry" || previewServiceCall.data?.date !== "2031-06-21") throw new Error("Selected preview date was not sent to the narrow Smart Shading preview service");
const originalCallService = hass.callService;
hass.callService = function(domain, service, data) {
  if (domain === "smart_shading" && service === "preview_day") {
    this.calls.push({ domain, service, data });
    return Promise.reject(new Error("service unavailable"));
  }
  return originalCallService.call(this, domain, service, data);
};
await dialog._previewDay("room", "entry", "2031-06-22");
if (!dialog._toolStatus.includes("vollständig neu starten")) throw new Error("Unavailable selected-date preview did not explain the required Home Assistant restart");
hass.callService = originalCallService;
const contentWritesAfterTools = Number(dialog.dataset.contentWriteCount || 0);
if (contentWritesAfterTools < 1) throw new Error("Advanced dialog did not record its initial content write");
dialog.shadowRoot.querySelector(".dialog").scrollTop = 123;
card.hass = hass;
if (!dialog.isConnected || !dialog.shadowRoot.innerHTML.includes("Smart Shading · Details")) throw new Error("Details dialog closed during state update");
if (dialog.shadowRoot.innerHTML.includes("undefined")) throw new Error("Dialog rendered undefined");
if (Number(dialog.dataset.contentWriteCount || 0) !== contentWritesAfterTools) throw new Error("Unchanged Home Assistant state rewrote the Advanced dialog DOM");
if (dialog.shadowRoot.querySelector(".dialog").scrollTop !== 123) throw new Error("Advanced dialog lost its scroll position on an unchanged update");
const focusedAction = new FakeElement();
focusedAction.dataset.toolPress = "button.simulate";
dialog.shadowRoot.activeElement = focusedAction;
hass.states["cover.internal_identifier"] = { ...unknownCoverState, attributes: { ...unknownCoverState.attributes, current_position: 75 } };
card.hass = hass;
if (Number(dialog.dataset.contentWriteCount || 0) !== contentWritesAfterTools + 1 || !dialog._mainHtml.includes("75%")) throw new Error("Changed relevant cover feedback did not refresh the Advanced dialog");
if (dialog.shadowRoot.querySelector(".dialog").scrollTop !== 123) throw new Error("Advanced dialog lost its scroll position while refreshing content");
await new Promise((resolve) => setTimeout(resolve, 1100));
if (dialog.shadowRoot.querySelector(".dialog").scrollTop !== 123) throw new Error("Advanced dialog scroll changed after delayed tasks settled");
if (document.activeElement !== outsideFocus) throw new Error("Dialog update changed focus outside Smart Shading");
const focusedPreviewDate = dialog.shadowRoot.querySelector("main").querySelector("[data-preview-date]");
dialog.shadowRoot.activeElement = focusedPreviewDate;
hass.states["cover.internal_identifier"] = { ...unknownCoverState, attributes: { ...unknownCoverState.attributes, current_position: 74 } };
card.hass = hass;
const replacementPreviewDate = dialog.shadowRoot.querySelector("main").querySelector("[data-preview-date]");
if (replacementPreviewDate.value !== "2031-06-21") throw new Error("Advanced dialog did not retain the selected preview date after a relevant update");
const renderCountBeforeDiagnosticOnly = Number(card.dataset.renderCount || 0);
const dialogWritesBeforeDiagnosticOnly = Number(dialog.dataset.contentWriteCount || 0);
card.hass = {
  ...hass,
  states: {
    ...hass.states,
    "sensor.room_status": {
      ...roomStatus,
      attributes: {
        ...roomStatus.attributes,
        diagnostic_events: [...roomStatus.attributes.diagnostic_events, {
          time: "2031-06-21T12:05:00+00:00", event: "room_evaluated", mode: "solar", targets: 1,
        }],
      },
    },
  },
};
if (Number(card.dataset.renderCount || 0) !== renderCountBeforeDiagnosticOnly) throw new Error("Diagnostics-only attributes rebuilt the visible card");
if (Number(dialog.dataset.contentWriteCount || 0) !== dialogWritesBeforeDiagnosticOnly + 1) throw new Error("Open dialog did not receive a diagnostics-only update");
const renderCountBeforeUnrelated = Number(card.dataset.renderCount || 0);
card.hass = { ...hass, states: { ...hass.states, "sensor.unrelated": { entity_id: "sensor.unrelated", state: "1", attributes: {} } } };
if (Number(card.dataset.renderCount || 0) !== renderCountBeforeUnrelated) throw new Error("An unrelated Home Assistant update rebuilt the whole card");
  card.hass = {
  ...hass,
  states: {
    ...hass.states,
    "sensor.room_status": { ...roomStatus, state: "comfort", attributes: { ...roomStatus.attributes, reason: "Relevant state changed" } },
  },
  };
  if (Number(card.dataset.renderCount || 0) !== renderCountBeforeUnrelated + 1) throw new Error("A relevant Home Assistant update did not refresh the card");
  document.scrollingElement.scrollTop = 615;
  dashboardScrollWrites = 0;
  const burstModes = ["heat", "safety", "solar", "comfort", "open"];
  for (const [index, mode] of burstModes.entries()) {
    card.hass = {
      ...hass,
      states: {
        ...hass.states,
        "sensor.room_status": { ...roomStatus, state: mode, attributes: { ...roomStatus.attributes, reason: `Burst ${index}` } },
        "cover.internal_identifier": { ...unknownCoverState, attributes: { ...unknownCoverState.attributes, current_position: 70 + index } },
      },
    };
  }
  await Promise.resolve();
  await new Promise((resolve) => setTimeout(resolve, 1100));
  if (document.scrollingElement.scrollTop !== 615) throw new Error("A burst of relevant updates changed the dashboard scroll position");
  if (dashboardScrollWrites !== 0) throw new Error("Smart Shading wrote document.scrollingElement during a state update");
  if (document.activeElement !== outsideFocus) throw new Error("Smart Shading changed focus outside the card during a state update");
  card.disconnectedCallback();
if (dialog.isConnected || documentListeners.has("keydown")) throw new Error("Detached card did not clean up its dialog and document listener");
}

runAsyncChecks()
  .then(() => console.log("Card and advanced dialog runtime smoke test passed"))
  .catch((error) => { console.error(error); process.exitCode = 1; });
