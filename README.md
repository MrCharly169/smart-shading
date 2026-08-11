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
```

The card automatically follows the setup variant chosen when the integration is
created. It has no separate Easy/Advanced switch.

## Dashboard badges

The same frontend resource provides a graphical badge editor. In the dashboard
editor choose **Add badge → Smart Shading status**, then select either the house
status or a room status. Smart Shading uses Home Assistant's official small,
round icon badge. Its main glyph always represents the configured cover type;
a small state marker and the native theme color show Auto, Night, Safety, heat,
glare, solar or comfort shading, manual control and pauses. Select the badge to
open the complete status, including the pause end when available.

During initial setup, select **Set up house and room dashboard badges** from the
optional feature page. This choice is available in both Easy and Advanced Mode.
After saving, Home Assistant creates an onboarding notification with the exact
house and room choices. Existing dashboards are never changed automatically;
the customer confirms placement in the native dashboard editor.

```yaml
type: custom:smart-shading-badge
entity: sensor.YOUR_ROOM_OR_HOUSE_STATUS
```

## Easy and Advanced Mode

- **Easy Mode** always works from `sun.sun`, the configured facade sector, the
  cover profile, and one room-level **Manual Override**. Each sector uses
  exactly one source: sun geometry, a local Lux sensor, or an external on/off
  sensor. An optional outdoor-temperature sensor automatically adds its
  configured minimum condition. The override remains active until a user or
  an explicit automation turns it off.
- **Advanced Mode** starts with the same base shading, then lets each room
  select only the optional capabilities it needs: schedules, temperatures,
  Night, Safety, weather or occupancy conditions, glare protection, maximum
  opening limits, test tools, and expert command settings. Unselected
  features do not run in the background and do not add controls to the
  dashboard.

Home Assistant's `sun.sun` entity is selected automatically and is no longer a
customer-facing house setting. If it is missing or unavailable, Smart Shading
stops sector-based setup and reports how to restore the Sun integration.
Advanced profile choices show their concrete thresholds, delays or curve
values directly in the profile name; Easy keeps those technical values hidden.

The setup variant is fixed for the config entry. To use the other variant,
create a new Smart Shading entry and configure it from the beginning. New
Advanced rooms keep external-movement pause detection off until it is
explicitly enabled.

Each Easy sector uses one source: sun geometry, a Lux sensor, or an external
on/off sun confirmation. Local Lux is recommended and creates Smart Shading's
Sun Presence binary sensor with hysteresis and delays. An external entity is a
separate alternative where `on` means direct sun. Sources are never combined
and there is no hidden weather fallback. If an explicitly selected source is
unavailable, normal shading waits instead of guessing. Without an outdoor
temperature sensor, outdoor temperature is ignored entirely.

### Advanced decision, execution, and glare protection

Advanced evaluates source changes event-by-event and combines related updates
into one short debounced decision. The configured evaluation interval is only a
recovery watchdog; it does not repeatedly resend an unchanged target.

The room-status Card and diagnostic export show the selected rule, rejected
rules, input quality, resulting cover targets, protected-zone calculation and
command lifecycle. Active glare protection is shown as its own Card state with
the normal target, calculated zone target and final cover target. A target
can be verified once after its expected movement time and retried only within
the configured bound. Venetian and vertical-blind height movement is always
completed before a delayed slat correction. A newer higher-priority target,
especially Safety, cancels obsolete delayed work.

In **Sun sector → Glare protection**, Advanced users select one physical cover,
measure its clear window opening, and measure the table or object area that
must stay out of direct Sun. Before saving, the wizard validates the geometry
and shows whether the current Sun position produces a usable calculation and
target. Roller shades, screens, symmetrically closing curtains, binary covers,
and vertical slats are supported; vertical-slat results are approximate.
Exterior Venetian blinds with horizontal slats and awnings are not offered by
the object calculator.

Inside the general shading schedule, a valid protected-zone intersection can
request glare protection even when the room is too cool for normal
temperature-based shading. It may close a cover more than Comfort or Solar,
but never opens farther than their target. Multiple zones choose the most
protective target. Safety, manual control or pause, Night and Heat Protection
remain higher priority. Missing source data holds the current position, and
invalid geometry is shown in the Card and diagnostics instead of issuing a
movement. Easy Mode has neither the configuration nor the runtime controls for
this feature.

Maximum opening is a separate Advanced room feature for position-controlled
covers. It does not replace a group's normal Open target: a normal target may
remain `100%`, while the effective target is the lower of that target and the
cover's configured hard limit. External KNX or wall-switch feedback is checked
immediately and a lightweight 30-second heartbeat provides recovery. A tight
tolerance and command cooldown prevent oscillation. The hard limit remains
active during schedules, manual pauses and room overrides; only a Safety
movement may temporarily exceed it. The Card and diagnostics show the normal
target, opening limit and effective target independently.

The general shading schedule permits every automatic daytime function:
ordinary shading, Comfort, Solar, glare protection and Heat Protection. Night
uses its own source or Sun-relative period and remains independent. Heat
Protection can start at most once per calendar day and ends at the earliest of
the schedule end, sunset plus offset, or the configured latest evening time.
For horizontal slats, the temperature page presents adaptive normal shading
and stronger Heat Protection. Other position-controlled profiles can present
separate Comfort, Solar and Heat stages; mixed rooms explain both behaviours
directly in the form.

Simulation and day preview reuse the production decision path but never call a
cover service. They are an explicit per-room Test & Preview option, and return
a completed result rather than changing the room's automation state.

The cover type is a functional profile, not only a label. Exterior venetian
blinds and vertical blinds receive position plus slat guidance; roller
shutters, screens, curtains, and awnings receive their own direction and target
defaults; simple open/close covers use only open/close services. Changing the
type updates the wizard, runtime, available entities, and card together and
removes incompatible options.

Every position target belongs to its physical cover group. In particular, the
Night feature defines the room's independent active period, while each group
keeps its own Night height and, for slatted profiles, Night slat target. This
allows mixed curtains, shutters and blinds in one room to close differently.

## Updating

1. Update Smart Shading through HACS or replace `custom_components/smart_shading`.
2. Restart Home Assistant.
3. Reload the browser or Home Assistant companion app if the previous card code is still in memory.

Do not change the resource URL and do not append a version query.

## Cover and slat semantics

Cover height keeps the Home Assistant convention: `0%` is closed and `100%`
is open. Slat position uses the KNX convention confirmed for exterior venetian
blinds: `0%` is fully open and lets light through; `100%` is fully closed and
blocks sunlight.

Accordingly, Open and Safety use a `0%` slat target, Heat Protection uses
`100%`, and normal shading follows the adaptive KNX-scale slat curve. The
per-cover **Invert slats** option remains available only for covers that expose
the opposite direction.

## Version and change management

The repository uses the following sources of truth:

- `custom_components/smart_shading/manifest.json`: integration/release version
- `CHANGELOG.md → Unreleased`: user-visible changes currently under development
- versioned sections in `CHANGELOG.md`: published release history
- pull request description: implementation details and validation

A pull request that changes production or release behavior must update `CHANGELOG.md`. CI enforces this rule. Documentation changes are selected deliberately because GitHub cannot infer the meaning of a logic or UI change automatically.

## Beta and stable release channels

Smart Shading uses two release channels:

- **Beta:** built only from `develop`, with Home Assistant-style versions such
  as `2026.8.0b0`, and published as a GitHub prerelease.
- **Stable:** built only from `main`, with versions such as `2026.7.0`, and
  published as the latest stable GitHub release. The initial release of a month
  ends in `.0`; later fixes use `.1`, `.2`, and so on.

Releases use two deliberate maintainer gates:

1. Open **GitHub → Actions → Prepare Release → Run workflow** on the default branch. Select the channel and enter the requested version without a leading `v`. The workflow validates and tests the tested `develop` state, updates the manifest, moves `Unreleased` into a dated version section, creates a dedicated draft pull request, and dispatches the normal validation workflow for its release commit. It never merges or publishes.
2. Review and merge that pull request deliberately. Beta preparation targets `develop`. Stable preparation starts from the current `main`, integrates the tested `develop` state locally, and then opens the promotion pull request to `main`. Unexpected merge conflicts abort before any release branch is pushed. Stable preparation can assemble the beta sections since the previous stable release into an editable release draft.
3. Merging the reviewed manifest-version change starts **Release**
   automatically. A version change on `develop` selects Beta; the same change
   on `main` selects Stable. The manual **Release → Run workflow** entry is only
   a guarded retry and requires the exact manifest version as confirmation.
   Only this separate workflow creates the immutable tag, installation ZIP,
   and GitHub release.

The GitHub release body is extracted exactly from the matching dated `CHANGELOG.md` section. It is never generated independently. Before a beta or stable tag can be published, the release workflow requires the repository-wide syntax and fast suites, real lifecycles on both Stable and Beta Home Assistant, the real HA browser/Card suite, and an upgrade from the newest published stable Smart Shading tag. Afterwards, a hosted job uses the official HACS backend to resolve the published tag, downloads the same public source archive HACS sees, and runs that artifact in a fresh Home Assistant instance. The HACS job is the final post-publication acceptance gate; a parent delivery issue is closed only after it succeeds. See [docs/HA_E2E_LAB.md](docs/HA_E2E_LAB.md) and [the Issue #79 major-release acceptance record](docs/ISSUE_79_RELEASE_ACCEPTANCE.md).

For automatic draft pull-request creation, repository administrators must enable **Settings → Actions → General → Workflow permissions → Allow GitHub Actions to create and approve pull requests**. Only pull-request creation is automated; approval and merging remain manual.

The repository remains outside the official HACS catalog during private testing. It must nevertheless be publicly readable because HACS cannot download private GitHub repositories. Add it once as a HACS custom integration repository. Test installations may opt into GitHub prereleases; stable installations use normal releases. `hide_default_branch` prevents accidental installation of an unversioned development snapshot.

HACS downloads the source belonging to the selected GitHub release tag. The attached ZIP is retained for manual recovery and inspection.

## Repository layout

```text
custom_components/smart_shading/   Integration and frontend
tests/                             Regression and runtime tests
e2e/                               Real HA fixture, scenarios and Playwright suite
docs/                              Development and repository notes
scripts/build_release.py           Package and metadata validation
scripts/check_pr_changelog.py      PR documentation policy
scripts/release_changelog.py       Release preparation and note extraction
scripts/ha_e2e/                    HA lifecycle, coverage and registry runners
.github/workflows/validate.yml     Continuous validation
.github/workflows/prepare-release.yml  Reviewable release preparation
.github/workflows/release.yml      Manual beta/stable release automation
```

Development rules are documented in [CONTRIBUTING.md](CONTRIBUTING.md). Home Assistant presents the integration in English or German according to the user's selected language.

Troubleshooting, including false KNX cover movement caused by readable command objects, is documented in the [FAQ](docs/FAQ.md).
