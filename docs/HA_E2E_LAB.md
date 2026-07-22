# Home Assistant E2E laboratory

The E2E laboratory is the second validation layer described in issue #73. It boots a disposable real Home Assistant Core container and complements, but does not replace, the fast `validate.yml` suite.

## What the laboratory validates

The current laboratory:

1. builds the installable Smart Shading release ZIP;
2. installs that packaged integration into a clean Home Assistant configuration;
3. loads repository-owned virtual venetian and roller-shutter covers, Lux sensors, temperature sensors, binary sensors, and deterministic sun geometry;
4. completes independent Easy and Advanced setups through Home Assistant's config-flow HTTP API, including source-specific and profile-specific pages;
5. changes an external sun-confirmation entity and records the cover service issued by Smart Shading;
6. checks authoritative unavailable external/Lux sources and the Safety priority path;
7. reloads config entries and proves Easy/Advanced state does not leak between them;
8. restarts the Home Assistant container without replacing its configuration and verifies stable entity IDs;
9. deletes and reinstalls the Advanced entry and checks registry/runtime cleanup;
10. exports sanitized JSON and JUnit results plus diagnostic evidence.

No production Home Assistant instance, KNX installation, MQTT broker, or external hardware is contacted.

## Run locally

Prerequisites are Docker, Python 3.13 or newer, and an unused local TCP port 8123.

```bash
scripts/ha_e2e/run_lab.sh
```

The result is written to `artifacts/ha-e2e/`. Override defaults when needed:

```bash
HA_E2E_PORT=18123 \
HA_E2E_IMAGE=ghcr.io/home-assistant/home-assistant:stable \
HA_E2E_ARTIFACT_DIR=/tmp/smart-shading-e2e \
scripts/ha_e2e/run_lab.sh
```

The laboratory uses an explicit container name, a dedicated Docker network, a temporary configuration directory, loopback-only port publishing, and a trap that removes only that laboratory container, network, and directory.

## Fixture and scenarios

The test-only integration lives under `e2e/ha/fixture/`. It provides stable entity IDs and the services:

- `smart_shading_test_fixture.set_state` controls values, availability, cover feedback, and `sun.sun` geometry;
- `smart_shading_test_fixture.reset_calls` clears the recorded cover-service history;
- `sensor.fixture_service_calls` exposes every command with service name and service data.

Scenarios are version-controlled JSON data under `e2e/ha/scenarios/`. `easy_lifecycle.json` drives the real HA lifecycle. `interaction_matrix.json` is the traceable Issue #73 coverage contract and identifies whether each behavior runs in the HA lab, fast engine suite, migration suite, or Playwright.

## CI behavior and evidence

`.github/workflows/ha-e2e.yml` runs for relevant pull-request paths, pushes to `develop`, and manual dispatches. Documentation-only changes do not start the container laboratory.

The `ha-e2e-<sha>` artifact contains:

- `home-assistant.log`, the scenario-runner log, and complete container output;
- container image/inspect metadata;
- the generated Home Assistant configuration and scenario definition;
- sanitized config-entry and entity snapshots;
- recorded cover service calls;
- phase result JSON and JUnit XML.

The disposable access token stays only in the temporary laboratory directory and is removed during cleanup. It is never copied to artifacts.

## Additional workflows

- `ha-ui-e2e.yml` runs the real card code in Chromium at desktop and mobile widths, validates variant binding, and retains traces/screenshots/videos on failure.
- `ha-nightly.yml` runs the lifecycle against stable Home Assistant and, as an experimental signal, the beta image.
- `ha-persistent-lab.yml` targets only a protected self-hosted runner labelled `smart-shading-lab`. Deployment and restart are fixed runner-local adapters under `/opt/smart-shading-lab/bin`; the workflow contains no public SSH path and refuses an instance whose protected name/scope does not match.

The ephemeral HA and browser workflows are required by `release.yml` before GitHub release publication. The persistent lab remains an explicitly dispatched, protected-environment qualification because its infrastructure and credentials are external to this repository.
