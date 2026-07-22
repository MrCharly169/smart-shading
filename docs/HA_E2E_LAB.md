# Home Assistant E2E laboratory

The E2E laboratory is the second validation layer described in issue #73. It boots a disposable real Home Assistant Core container and complements, but does not replace, the fast `validate.yml` suite.

## What the laboratory validates

The current laboratory:

1. builds the installable Smart Shading release ZIP;
2. installs that packaged integration into a clean Home Assistant configuration;
3. loads repository-owned virtual covers for every supported physical profile, Lux/temperature sensors, binary sensors, helpers and deterministic sun geometry;
4. completes independent Easy and Advanced setups through Home Assistant's real config-flow HTTP API;
5. creates additional rooms, sectors, groups and covers through the real Options flow;
6. submits every direction, sun source, cover profile, schedule profile, Night source, Pause mode and Safety behavior in disposable HA flows;
7. deliberately submits contradictory Easy geometry, Lux hysteresis and duplicate-cover data and requires the wizard's validation errors;
8. changes fixture states and records every cover service issued by Smart Shading;
9. checks authoritative unavailable external/Lux sources and the Safety priority path;
10. reloads and unloads config entries and proves Easy/Advanced state does not leak;
11. restarts HA without replacing its configuration and verifies stable entity IDs;
12. deletes and reinstalls the Advanced entry and rejects stale entity/device registry records;
13. exports JSON, JUnit, HA logs, registry summaries and browser evidence.

No production Home Assistant instance, KNX installation, MQTT broker or external hardware is contacted.

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

Set `HA_E2E_UPGRADE_FROM_REF=v4.6.2-beta.9` to install that tag first, create entries, replace it with the working candidate and repeat restart/registry checks. Set `HA_E2E_RUN_UI=1` after installing the Playwright dependencies to run the real HA browser suite inside the same laboratory lifetime.

The laboratory uses an explicit container name, a dedicated Docker network, a temporary configuration directory, loopback-only port publishing and a cleanup trap scoped to that laboratory.

## Fixture and scenarios

The test-only integration under `e2e/ha/fixture/` provides stable entity IDs and the services:

- `smart_shading_test_fixture.set_state` controls values, availability, cover feedback and `sun.sun` geometry;
- `smart_shading_test_fixture.reset_calls` clears recorded cover-service history;
- `sensor.fixture_service_calls` exposes every command with service name and data.

`easy_lifecycle.json` drives the real HA lifecycle. `interaction_matrix.json` maps Issue #73 behavior to its executable owner.

## Wizard coverage contract

`wizard_coverage.json` owns every customer-facing form/menu and the important choice sets. `check_wizard_coverage.py` fails when a developer adds or removes a flow surface without updating that contract. The real HA runner writes `wizard-coverage-live.json` and fails when a mandatory surface was not actually observed.

This avoids an unbounded Cartesian product while preserving the intended guarantee: every individual option, every conditional branch, every physical cover profile and every safety-critical combination has an executable owner.

## CI behavior and evidence

- `ha-e2e.yml` runs the clean real-HA lifecycle for relevant pull requests and pushes to `develop`.
- `ha-ui-e2e.yml` starts the same HA lab, signs into the disposable frontend, opens the actual Smart Shading dialog and mounts the real Card against real config-entry entities at desktop and mobile widths.
- `ha-upgrade-e2e.yml` runs for relevant pull requests, installs the newest published tag first and upgrades it to the candidate.
- `ha-nightly.yml` runs relevant pull requests on stable HA and the experimental HA beta image. The schedule checks the latest `develop` candidate, while a manual run may select another branch or tag.
- `ha-persistent-lab.yml` targets only a protected self-hosted runner labelled `smart-shading-lab`.
- `ha-hacs-e2e.yml` is called by the publishing workflow after every release and installs that exact tag through HACS in the isolated persistent lab. Keeping it in the same workflow avoids GitHub's suppression of workflows recursively triggered by the normal Actions token.

The release workflow requires clean HA, real browser and previous-release upgrade gates before publishing. HACS qualification necessarily runs after publication because HACS can only install a published GitHub tag.

Artifacts retain HA/container logs, generated configuration, sanitized config entries, entity/device registries, recorded calls, snapshots, scenario/coverage results, JUnit, screenshots, traces and videos. The disposable access token stays only in the temporary lab directory.

## Persistent runner prerequisites

The dedicated runner must provide these root-owned adapters:

- `/opt/smart-shading-lab/bin/deploy-candidate`
- `/opt/smart-shading-lab/bin/restart-home-assistant`
- `/opt/smart-shading-lab/bin/hacs-install-release`

The protected `ha-persistent-lab` environment supplies `HA_URL`, `HA_TOKEN`, `HA_INSTANCE_NAME` and `HA_HACS_UPDATE_ENTITY`. The target must be disposable and must never point to production Home Assistant or KNX.
