# Smart Shading

Smart Shading is a custom Home Assistant integration for sector-based shading using sun geometry, illuminance, temperature, safety inputs, window contacts, and manual overrides.

> **Current baseline:** `4.6.0-beta.1`  
> **Home Assistant:** 2026.6 or newer  
> **Integration domain:** `smart_shading`

The repository contains the complete integration source, frontend card, tests, documentation, and release validation workflow. It is no longer a bootstrap placeholder.

## Installation

### HACS custom repository

1. Add this repository to HACS as an **Integration**.
2. Install **Smart Shading**.
3. Restart Home Assistant.
4. Add the integration under **Settings → Devices & services → Add integration**.
5. Register the dashboard resource if it was not added automatically:

```text
/smart_shading/smart-shading-card.js?v=4.6.0-beta.1
```

### Manual installation

Copy this directory into Home Assistant:

```text
custom_components/smart_shading
```

Then restart Home Assistant.

## Dashboard card

```yaml
type: custom:smart-shading-card
entity: sensor.YOUR_ROOM_STATUS
advanced_mode: true
```

## Repository layout

```text
custom_components/smart_shading/   Integration and frontend card
tests/                             Regression and runtime tests
docs/                              Architecture and development notes
scripts/build_release.py           Release package builder/checker
.github/workflows/validate.yml     Continuous validation
```

## Development status

The `main` branch is the preserved 4.6.0-beta.1 baseline. Larger changes such as a separated Easy/Advanced configuration experience belong on feature branches and must pass the regression suite before being merged.

German documentation is available in [README_DE.md](README_DE.md). See [docs/REPOSITORY_STATUS.md](docs/REPOSITORY_STATUS.md) for the exact repository state.
