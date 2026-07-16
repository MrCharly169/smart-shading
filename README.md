# Smart Shading

Smart Shading is a Home Assistant custom integration for sector-based shading using sun geometry, illuminance, temperature, safety inputs, window contacts, and manual overrides.

- **Home Assistant:** 2026.6 or newer
- **Integration domain:** `smart_shading`
- **Canonical dashboard resource:** `/smart_shading/shading.js`

The dashboard resource URL is stable and contains no version query. Future integration upgrades replace the JavaScript behind the same URL; the Home Assistant resource entry does not need to be edited again.

## Installation

### HACS custom repository

1. Add this repository to HACS as an **Integration**.
2. Install **Smart Shading**.
3. Restart Home Assistant.
4. Add the integration under **Settings → Devices & services → Add integration**.
5. Register this dashboard resource once if it is not already present:

```text
/smart_shading/shading.js
```

Resource type: **JavaScript module**.

Older installations using `/smart_shading/smart-shading-card.js?v=...` remain compatible through a small legacy loader. They should be migrated once to the canonical URL above.

### Manual installation

Copy this directory into Home Assistant:

```text
custom_components/smart_shading
```

Restart Home Assistant and register the same stable dashboard resource once.

## Dashboard card

```yaml
type: custom:smart-shading-card
entity: sensor.YOUR_ROOM_STATUS
advanced_mode: true
```

## Updating

1. Update Smart Shading through HACS or replace `custom_components/smart_shading`.
2. Restart Home Assistant.
3. Reload the browser or Home Assistant companion app if the previous card code is still in memory.

Do not change the resource URL and do not append a version query.

## Version and change management

The repository uses the following sources of truth:

- `custom_components/smart_shading/manifest.json`: integration/release version
- `CHANGELOG.md → Unreleased`: user-visible changes currently under development
- versioned sections in `CHANGELOG.md`: published release history
- pull request description: implementation details and validation

A pull request that changes production or release behavior must update `CHANGELOG.md`. CI enforces this rule. Documentation changes are selected deliberately because GitHub cannot infer the meaning of a logic or UI change automatically.

A release is created by:

1. moving the relevant `Unreleased` entries into a section matching the manifest version;
2. updating the version in `manifest.json`;
3. pushing a tag such as `v4.6.0`.

The release workflow verifies that tag and manifest version match, runs all tests, builds the installable ZIP, and publishes the GitHub release.

## Repository layout

```text
custom_components/smart_shading/   Integration and frontend
tests/                             Regression and runtime tests
docs/                              Development and repository notes
scripts/build_release.py           Package and metadata validation
scripts/check_pr_changelog.py      PR documentation policy
.github/workflows/validate.yml     Continuous validation
.github/workflows/release.yml      Tagged release automation
```

German documentation is available in [README_DE.md](README_DE.md). Development rules are documented in [CONTRIBUTING.md](CONTRIBUTING.md).
