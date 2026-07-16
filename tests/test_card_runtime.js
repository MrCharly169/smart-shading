const fs = require("fs");
const vm = require("vm");
const path = require("path");

class FakeNode {
  constructor() { this.isConnected = false; this.dataset = {}; }
  addEventListener() {}
  setAttribute() {}
  getAttribute() { return ""; }
  remove() { this.isConnected = false; }
}
class FakeShadowRoot {
  constructor() { this.innerHTML = ""; }
  querySelector() { return null; }
  querySelectorAll() { return []; }
}
class FakeHTMLElement extends FakeNode {
  attachShadow() { this.shadowRoot = new FakeShadowRoot(); return this.shadowRoot; }
  dispatchEvent() { return true; }
}
class FakeEvent { constructor(type, options = {}) { this.type = type; Object.assign(this, options); } stopPropagation() {} }
class FakeCustomEvent extends FakeEvent { constructor(type, options = {}) { super(type, options); this.detail = options.detail; } }
const registry = new Map();
const body = {
  children: [],
  appendChild(node) { node.isConnected = true; this.children.push(node); return node; },
};
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
  addEventListener() {},
  removeEventListener() {},
};
global.window = {};
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
    diagnostic_events: [{ timestamp: "2026-07-14T12:00:00+00:00", event: "room_mode_changed", room_id: "room", mode: "solar" }],
    sector_statuses: [{ id: "south_left", name: "Süd links", short: "S1", status: "shading_active", reason: "Normal shading", geometry_active: true, sun_presence: true, lux: 26398.72, lux_raw_state: "26398.72", lux_unit: "lx", sun_settings: { sun_on_lux: 18000, sun_off_lux: 9000, sun_on_delay: 3, sun_off_delay: 12 }, pending_target: null, pending_until: null, mode: "solar", sun_presence_entity_id: "binary_sensor.south_sun_presence" }],
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
    "sensor.room_status": roomStatus,
    "button.pause": { entity_id: "button.pause", state: "unknown", attributes: { smart_shading_entry_id: "entry", smart_shading_room_id: "room", smart_shading_control_key: "pause_default" } },
    "button.resume": { entity_id: "button.resume", state: "unknown", attributes: { smart_shading_entry_id: "entry", smart_shading_room_id: "room", smart_shading_control_key: "resume" } },
    "button.evaluate": { entity_id: "button.evaluate", state: "unknown", attributes: { smart_shading_entry_id: "entry", smart_shading_room_id: "room", smart_shading_control_key: "evaluate" } },
    "switch.master": { entity_id: "switch.master", state: "off", attributes: { smart_shading_entry_id: "entry", smart_shading_room_id: "room", smart_shading_control_key: "manual_master" } },
  },
  calls: [],
  callService: async function(domain, service, data) { this.calls.push({ domain, service, data }); },
};

const card = new Card();
card.setConfig({ entity: "sensor.room_status", advanced_mode: true });
card.hass = hass;
const html = card.shadowRoot.innerHTML;
if (!html.includes("Raum A") || !html.includes("Fenstergruppe") || !html.includes("Süd links")) throw new Error("Card did not render configured display names");
const visibleHtml = html.replace(/data-(?:more|press|toggle|number|select)="[^"]*"/g, "");
if (visibleHtml.includes("cover.internal_identifier")) throw new Error("Card exposed a raw cover entity ID as visible content");
if (html.includes("undefined")) throw new Error("Card rendered undefined");
if (!html.includes("sunbox") || !html.includes("sector-card") || !html.includes("cover-row")) throw new Error("Compact reference structure missing");
if (!html.includes("Pausiert")) throw new Error("Local cover pause was not rendered");
if (!html.includes("--mdc-icon-size:12px") || !html.includes("--mdc-icon-size:15px")) throw new Error("Icon sizing variables missing");
card._callEntity("switch.master");
card._callEntity("button.evaluate");
if (!hass.calls.some((call) => call.domain === "switch" && call.service === "toggle" && call.data.entity_id === "switch.master")) throw new Error("Master switch was not toggled");
if (!hass.calls.some((call) => call.domain === "button" && call.service === "press" && call.data.entity_id === "button.evaluate")) throw new Error("Evaluate button was not pressed");

card._openAdvanced(roomStatus, card._controls(roomStatus));
if (!body.children.length) throw new Error("Advanced dialog was not appended to document.body");
const dialog = body.children[0];
if (!dialog.shadowRoot.innerHTML.includes("Erweiterte Ansicht")) throw new Error("Advanced dialog did not render");
if (!dialog.shadowRoot.innerHTML.includes("26") || !dialog.shadowRoot.innerHTML.includes("18") || !dialog.shadowRoot.innerHTML.includes("Pausiert")) throw new Error("Advanced dialog missed lux or local pause details");
if (dialog.shadowRoot.innerHTML.includes("automation_lock") || dialog.shadowRoot.innerHTML.includes("outside_sun_sector")) throw new Error("Advanced dialog exposed raw internal reason keys");
const before = dialog.shadowRoot.innerHTML;
card.hass = hass;
if (!dialog.isConnected || !dialog.shadowRoot.innerHTML.includes("Erweiterte Ansicht")) throw new Error("Advanced dialog closed during state update");
if (dialog.shadowRoot.innerHTML.includes("undefined")) throw new Error("Dialog rendered undefined");
console.log("Card and advanced dialog runtime smoke test passed");
