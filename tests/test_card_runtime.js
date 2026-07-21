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
  querySelector() { return null; }
  querySelectorAll(selector) {
    if (this._queryCache.has(selector)) return this._queryCache.get(selector);
    const attribute = selector.match(/^\[data-([a-z-]+)\]$/)?.[1];
    if (!attribute) return [];
    const key = attribute.replace(/-([a-z])/g, (_, letter) => letter.toUpperCase());
    const pattern = new RegExp(`data-${attribute}="([^"]*)"`, "g");
    const nodes = [...this._innerHTML.matchAll(pattern)].map((match) => {
      const node = new FakeElement();
      node.dataset[key] = match[1];
      return node;
    });
    this._queryCache.set(selector, nodes);
    return nodes;
  }
}
class FakeShadowRoot {
  constructor() { this._innerHTML = ""; this._dialog = null; this._main = null; this.activeElement = null; this.writeCount = 0; }
  set innerHTML(value) {
    this._innerHTML = String(value || "");
    this.writeCount += 1;
    if (this._innerHTML.includes('class="dialog"')) {
      this._dialog = new FakeElement();
      const match = this._innerHTML.match(/<main>([\s\S]*)<\/main>/);
      this._main = new FakeElement(match?.[1] || "");
    } else {
      this._dialog = null;
      this._main = null;
    }
  }
  get innerHTML() { return this._innerHTML; }
  querySelector(selector) {
    if (selector === ".dialog") return this._dialog;
    if (selector === "main") return this._main;
    return null;
  }
  querySelectorAll(selector) {
    if (selector === "[data-close]" && this._dialog) return [new FakeElement(), new FakeElement()];
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
global.HTMLElement = FakeHTMLElement;
global.Event = FakeEvent;
global.CustomEvent = FakeCustomEvent;
global.customElements = {
  define(name, klass) { registry.set(name, klass); },
  get(name) { return registry.get(name); },
};
global.document = {
  body,
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
if (!Card || !Editor || !Dialog) throw new Error("Smart Shading card, editor, or dialog was not registered");

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
    easy_temperature_gate: { enabled: true, source_entity: "sensor.outdoor", value: 24.5, threshold: 18, passed: true },
    diagnostic_events: [{ timestamp: "2026-07-14T12:00:00+00:00", event: "room_mode_changed", room_id: "room", mode: "solar" }],
    sector_statuses: [{ id: "south_left", name: "Süd links", short: "S1", status: "shading_active", reason: "Normal shading", geometry_active: true, sun_presence: true, confirmation_source: "binary", confirmation_entity: "binary_sensor.south_sun_presence", confirmation_state: true, effective_active: true, lux: 26398.72, lux_raw_state: "26398.72", lux_unit: "lx", sun_settings: { sun_on_lux: 18000, sun_off_lux: 9000, sun_on_delay: 3, sun_off_delay: 12 }, pending_target: null, pending_until: null, mode: "solar", sun_presence_entity_id: "binary_sensor.south_sun_presence" }],
    configuration: {
      indoor_temperature: "sensor.room_temperature",
      sun_entity: "sun.sun",
      safety_blockers: [],
      sectors: [{
        id: "south_left", name: "Süd links", short: "S1", azimuth_start: 120, azimuth_end: 240,
        layers: [{ name: "Behanggruppe", covers: [{ entity: "cover.internal_identifier", name: "Fenstergruppe", short: "B1", lock: "switch.cover_lock", window: "binary_sensor.window_contact", window_safe_state: "on" }] }],
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
    "button.pause": { entity_id: "button.pause", state: "unknown", attributes: { smart_shading_entry_id: "entry", smart_shading_room_id: "room", smart_shading_control_key: "pause_default" } },
    "button.resume": { entity_id: "button.resume", state: "unknown", attributes: { smart_shading_entry_id: "entry", smart_shading_room_id: "room", smart_shading_control_key: "resume" } },
    "button.evaluate": { entity_id: "button.evaluate", state: "unknown", attributes: { smart_shading_entry_id: "entry", smart_shading_room_id: "room", smart_shading_control_key: "evaluate" } },
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

const card = new Card();
card.setConfig({ entity: "sensor.room_status", advanced_mode: true });
card.hass = hass;
const html = card.shadowRoot.innerHTML;
if (!html.includes("Raum A") || !html.includes("Fenstergruppe") || !html.includes("Süd links")) throw new Error("Card did not render configured display names");
const visibleHtml = html.replace(/data-(?:more|press|toggle|number|select)="[^"]*"/g, "");
if (visibleHtml.includes("cover.internal_identifier")) throw new Error("Card exposed a raw cover entity ID as visible content");
if (html.includes("undefined")) throw new Error("Card rendered undefined");
if (!html.includes('data-card-mode="advanced"') || !html.includes("data-advanced-layout") || !html.includes("data-advanced-sectors")) throw new Error("Advanced card did not use its dedicated layout");
if (!html.includes("sunbox") || !html.includes("sector-card") || !html.includes("cover-row")) throw new Error("Advanced reference structure missing");
if (!html.includes("Pausiert")) throw new Error("Local cover pause was not rendered");
if (!html.includes(".icon-box") || !html.includes("place-items:center;align-content:center;justify-content:center") || !html.includes("--icon-size:12px") || !html.includes("--icon-size:15px")) throw new Error("Shared mathematical icon centering is missing");
if (!html.includes('data-night-source="schedule.room_night"')) throw new Error("Advanced card did not expose the Night schedule shortcut");
if (!html.includes("@keyframes calmPulse") || html.includes("@keyframes cardGlow") || html.includes("@keyframes sunPulse") || html.includes("filter:brightness")) throw new Error("Card did not use the single calm opacity/transform pulse");
if (!html.includes("@media(prefers-reduced-motion:reduce)") || !html.includes("@container shading-card")) throw new Error("Reduced-motion or container-query fallback is missing");
if (!html.includes("Sonne · Sonnensensor")) throw new Error("Advanced sun feedback did not name its effective source");
const cardMarkup = html.slice(html.indexOf("</style>") + 8);
if (/<button[^>]*>\s*<ha-icon/i.test(cardMarkup)) throw new Error("A card button bypassed the shared icon box");
card._callEntity("switch.master");
card._callEntity("button.evaluate");
if (!hass.calls.some((call) => call.domain === "switch" && call.service === "toggle" && call.data.entity_id === "switch.master")) throw new Error("Master switch was not toggled");
if (!hass.calls.some((call) => call.domain === "button" && call.service === "press" && call.data.entity_id === "button.evaluate")) throw new Error("Evaluate button was not pressed");

async function runAsyncChecks() {
await card._openNightSource("schedule.room_night");
if (!hass.wsCalls.some((request) => request.type === "config/entity_registry/get" && request.entity_id === "schedule.room_night")) throw new Error("Schedule shortcut did not resolve the helper registry entry");
if (window.routes.at(-1) !== "/config/helpers/edit/schedule-entry" || window.events.at(-1)?.type !== "location-changed") throw new Error("Schedule shortcut did not navigate to the real schedule helper editor");
await card._openNightSource("binary_sensor.night_source");
const fallbackEvent = card.dispatchedEvents.at(-1);
if (fallbackEvent?.detail?.entityId !== "binary_sensor.night_source" || fallbackEvent.detail?.view) throw new Error("Non-schedule Night source did not retain the More Info fallback");

const easyRoomStatus = JSON.parse(JSON.stringify(roomStatus));
easyRoomStatus.entity_id = "sensor.easy_room_status";
easyRoomStatus.attributes.smart_shading_layout = "compact";
hass.states[easyRoomStatus.entity_id] = easyRoomStatus;
const easyCard = new Card();
easyCard.setConfig({ entity: easyRoomStatus.entity_id });
easyCard.hass = hass;
const easyHtml = easyCard.shadowRoot.innerHTML;
if (!easyHtml.includes('data-card-mode="easy"') || !easyHtml.includes("data-easy-layout") || !easyHtml.includes("data-easy-sun") || !easyHtml.includes("data-easy-covers")) throw new Error("Easy card did not use its dedicated minimal layout");
if (!easyHtml.includes("Sonne im Sektor") || !easyHtml.includes("Sonne · Sonnensensor") || easyHtml.includes("Az 180°")) throw new Error("Easy effective source/status feedback was not compact and simplified");
if (!easyHtml.includes("easy-cover-row") || !easyHtml.includes("Fenstergruppe") || !easyHtml.includes("100%")) throw new Error("Easy card did not render compact cover feedback");
if (easyHtml.includes("data-advanced-layout") || easyHtml.includes("data-advanced-sectors") || easyHtml.includes("data-night-source") || easyHtml.includes('data-press="button.pause"')) throw new Error("Easy card exposed Advanced-only controls or details");
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

card._openAdvanced(roomStatus, card._controls(roomStatus));
if (!body.children.length) throw new Error("Advanced dialog was not appended to document.body");
const dialog = body.children[0];
if (!dialog.shadowRoot.innerHTML.includes("Smart Shading · Details")) throw new Error("Details dialog did not render");
if (!dialog.shadowRoot.innerHTML.includes("26") || !dialog.shadowRoot.innerHTML.includes("18") || !dialog.shadowRoot.innerHTML.includes("Pausiert")) throw new Error("Advanced dialog missed lux or local pause details");
if (!dialog.shadowRoot.innerHTML.includes('data-night-source="schedule.room_night"')) throw new Error("Advanced dialog did not expose the Night schedule editor shortcut");
if (!dialog.shadowRoot.innerHTML.includes("100dvh") || !dialog.shadowRoot.innerHTML.includes("button[data-close]{display:grid;place-items:center")) throw new Error("Advanced dialog mobile viewport or close-icon centering hardening is missing");
if (dialog.shadowRoot.innerHTML.includes("automation_lock") || dialog.shadowRoot.innerHTML.includes("outside_sun_sector")) throw new Error("Advanced dialog exposed raw internal reason keys");
if (dialog.dataset.contentWriteCount !== "1") throw new Error("Advanced dialog did not record its initial content write");
dialog.shadowRoot.querySelector(".dialog").scrollTop = 123;
card.hass = hass;
if (!dialog.isConnected || !dialog.shadowRoot.innerHTML.includes("Smart Shading · Details")) throw new Error("Details dialog closed during state update");
if (dialog.shadowRoot.innerHTML.includes("undefined")) throw new Error("Dialog rendered undefined");
if (dialog.dataset.contentWriteCount !== "1") throw new Error("Unchanged Home Assistant state rewrote the Advanced dialog DOM");
if (dialog.shadowRoot.querySelector(".dialog").scrollTop !== 123) throw new Error("Advanced dialog lost its scroll position on an unchanged update");
const focusedAction = new FakeElement();
focusedAction.dataset.press = "button.evaluate";
dialog.shadowRoot.activeElement = focusedAction;
hass.states["cover.internal_identifier"] = { ...unknownCoverState, attributes: { ...unknownCoverState.attributes, current_position: 75 } };
card.hass = hass;
if (dialog.dataset.contentWriteCount !== "2" || !dialog._mainHtml.includes("75%")) throw new Error("Changed relevant cover feedback did not refresh the Advanced dialog");
if (dialog.shadowRoot.querySelector(".dialog").scrollTop !== 123) throw new Error("Advanced dialog lost its scroll position while refreshing content");
const replacementAction = dialog.shadowRoot.querySelector("main").querySelectorAll("[data-press]").find((element) => element.dataset.press === "button.evaluate");
if (!replacementAction?.focused) throw new Error("Advanced dialog did not restore focused control after a relevant update");
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
card.disconnectedCallback();
if (dialog.isConnected || documentListeners.has("keydown")) throw new Error("Detached card did not clean up its dialog and document listener");
}

runAsyncChecks()
  .then(() => console.log("Card and advanced dialog runtime smoke test passed"))
  .catch((error) => { console.error(error); process.exitCode = 1; });
