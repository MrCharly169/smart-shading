# Native Home Assistant language contract

The card, badge and editors read the active client's `hass.language`. The
server's `hass.config.language` must not override it. Explicit card language
overrides remain opt-in. English and regional English tags use English;
German and unsupported or absent custom-card language tags use German.

Config and options flows use native translation keys. Dynamic action lists
use a native select control with translated action values and unchanged user
names for objects. The chosen value dispatches to the existing stable route.
Dynamic summaries supply both `__en` and `__de` placeholders from the same
inputs; each native translation selects its own copy. This never changes the
user profile, server language, decision logic or stored integration settings.

Home Assistant entity names are shared registry metadata generated in the
backend language, not a per-user UI surface. Native translation keys supply
their defaults; user-provided names and existing entity IDs are preserved.
Entity states and select options use native presentation translations. Legacy
select values remain accepted so existing automations keep working.

Regression owners:

- `tests/test_flow_user_language.py`: conflicting server locale, bilingual
  summaries, native route selection, multiple Glare sectors and entity names.
- `tests/test_card_runtime.js`: English app/German server and the inverse,
  including existing stable-DOM and scroll-preservation coverage.
- `scripts/ha_e2e/run_scenarios.py`: actual native selector submissions, schema
  recording and traversal of the original semantic flow steps.
- Central ecosystem translation audit: all registered public/local integration
  catalogs, paired placeholders and zero backend-language flow references.

Native behavior references:

- https://developers.home-assistant.io/docs/core/entity/
- https://developers.home-assistant.io/docs/internationalization/core/
- https://github.com/home-assistant/frontend/blob/20260826.4/src/components/ha-selector/ha-selector-select.ts
