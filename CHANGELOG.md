# Changelog

## Unreleased


## 99.0.1 - 2026-07-17

### Release Process

- added a manually triggered Prepare Release workflow that creates a dedicated, reviewable draft pull request instead of publishing directly
- beta preparation branches from and targets `develop`; stable preparation starts from current `main` and integrates the tested `develop` state before opening its promotion pull request
- unexpected stable-promotion merge conflicts now abort before any release branch is pushed; only the known historical release-workflow add/add conflict is resolved from tested `develop`
- release preparation validates the channel, version, source and target branches, existing tags, releases, and release branches
- the manifest version and a dated changelog section are prepared together while preserving an empty `Unreleased` section
- stable preparation can assemble beta history since the previous stable version into an editable draft
- the separate publication workflow now uses the exact prepared changelog section as its GitHub release body
- added regression coverage for preparation, stable aggregation, dated headings, and changelog note extraction

### Included beta release history

#### 4.6.0-beta.2

##### Heat Protection

- Heat Protection with the sun requirement enabled uses the combined Sun Presence of all enabled sectors in a room
- one sector with confirmed Sun Presence is sufficient for the entire room
- Sun Presence is only a start condition; after activation, Heat Protection remains active independently of later OFF states
- falling indoor temperatures do not end active Heat Protection early
- the schedule, weather release, and configured minimum outdoor temperature are checked at startup
- only the configured Evening Release reopens the covers and blocks another heat cycle until the next daily reset
- disabled sectors and invalid or unavailable illuminance values do not count as confirmed sun at startup
- when the sun requirement is disabled, the previous temperature-only behavior remains unchanged

##### Repository, Frontend, and Releases

- added a manual release trigger with an explicit choice between beta (`develop`) and stable (`main`)
- beta versions are published as GitHub prereleases and stable versions as the latest release
- branch, SemVer, changelog, confirmation, and duplicate tags are validated before publication
- HACS offers published versions only and no unversioned branch snapshots
- updated English and German documentation with the beta, stable, and HACS test process
- changed the canonical dashboard resource to the permanent URL `/smart_shading/shading.js`
- removed version parameters from the resource URL so Home Assistant does not need dashboard changes after upgrades
- retained `smart-shading-card.js` as a compatibility loader
- kept the technical version exclusively in the integration manifest
- required production pull requests to update the changelog at the same time
- added a validated tag workflow that creates the installation ZIP and GitHub release
- aligned the README files, development documentation, and CI with the release process

#### 4.6.0-beta.1

##### Core Stability

- completed a full review of the engine, persistence, triggers, wizard, card, and diagnostics
- the numeric parser accepts real Home Assistant states such as `26398.72`, `26,398.72`, and `26.398,72`
- invalid sensor values are no longer silently converted to `0`
- indoor temperature, outdoor temperature, and illuminance use the same robust numeric parsing
- missing or `unavailable` states remain `None`

##### Sun Presence

- `26398.72 lx` switches the Balanced profile ON after three minutes
- presets take precedence over obsolete beta thresholds
- only the Custom profile uses individual thresholds
- added an exact timer for ON and OFF delays
- illuminance transitions update Sun Presence while the full room movement remains on the normal 20-minute interval
- exposed the raw value, unit, effective thresholds, and pending time in the entity, card, and diagnostics

##### Manual Operation

- external cover movement starts a local pause only for that cover
- the configured lock is switched ON; switch and input boolean entities are supported
- switching the lock OFF ends the pause immediately and triggers reevaluation
- pause expiry switches the lock OFF and evaluates exactly once
- repeated movement telegrams do not extend an already active pause
- internal cover feedback is identified through target, direction, tolerance, and time window
- the initial `unavailable → open` state is not treated as manual operation
- immediate user unlock is no longer confused with internal lock feedback
- Safety overrides a local pause and reacts immediately to manual movement

##### Room Pause and Master

- added a dedicated expiry timer for room pauses
- Master ON disables automation without counter-movement or automatic reset
- Master OFF triggers immediate reevaluation
- Safety retains higher priority

##### Triggers and Load

- full normal evaluation runs every 20 minutes by default
- temperature, normal sun-position, and illuminance state changes are batched
- immediate evaluation is limited to critical releases, Safety, windows, and override expiry

##### Card

- fixed local pause state handling without a JavaScript ReferenceError
- reduced icon sizes using `--mdc-icon-size`
- added dedicated section grid rules to avoid excessively narrow rendering
- active Sun Presence pulses; Heat, Safety, and Master states are animated
- effective temperature thresholds control the colors
- the sector abbreviation opens the correct Sun Presence sensor
- the manual button calls the switch correctly through `switch.toggle`

##### Diagnostics and Migration

- misleading legacy blocking counters are reset once
- real blocks continue to be counted; `already_correct` and cooldowns are not
- expanded the official Home Assistant diagnostics export and added a separate JSON export
- Config Entry schema 9 and Runtime schema 2


## 4.6.0-beta.2

### Heat Protection

- Heat Protection with the sun requirement enabled uses the combined Sun Presence of all enabled sectors in a room
- one sector with confirmed Sun Presence is sufficient for the entire room
- Sun Presence is only a start condition; after activation, Heat Protection remains active independently of later OFF states
- falling indoor temperatures do not end active Heat Protection early
- the schedule, weather release, and configured minimum outdoor temperature are checked at startup
- only the configured Evening Release reopens the covers and blocks another heat cycle until the next daily reset
- disabled sectors and invalid or unavailable illuminance values do not count as confirmed sun at startup
- when the sun requirement is disabled, the previous temperature-only behavior remains unchanged

### Repository, Frontend, and Releases

- added a manual release trigger with an explicit choice between beta (`develop`) and stable (`main`)
- beta versions are published as GitHub prereleases and stable versions as the latest release
- branch, SemVer, changelog, confirmation, and duplicate tags are validated before publication
- HACS offers published versions only and no unversioned branch snapshots
- updated English and German documentation with the beta, stable, and HACS test process
- changed the canonical dashboard resource to the permanent URL `/smart_shading/shading.js`
- removed version parameters from the resource URL so Home Assistant does not need dashboard changes after upgrades
- retained `smart-shading-card.js` as a compatibility loader
- kept the technical version exclusively in the integration manifest
- required production pull requests to update the changelog at the same time
- added a validated tag workflow that creates the installation ZIP and GitHub release
- aligned the README files, development documentation, and CI with the release process


## 4.6.0-beta.1

### Core Stability

- completed a full review of the engine, persistence, triggers, wizard, card, and diagnostics
- the numeric parser accepts real Home Assistant states such as `26398.72`, `26,398.72`, and `26.398,72`
- invalid sensor values are no longer silently converted to `0`
- indoor temperature, outdoor temperature, and illuminance use the same robust numeric parsing
- missing or `unavailable` states remain `None`

### Sun Presence

- `26398.72 lx` switches the Balanced profile ON after three minutes
- presets take precedence over obsolete beta thresholds
- only the Custom profile uses individual thresholds
- added an exact timer for ON and OFF delays
- illuminance transitions update Sun Presence while the full room movement remains on the normal 20-minute interval
- exposed the raw value, unit, effective thresholds, and pending time in the entity, card, and diagnostics

### Manual Operation

- external cover movement starts a local pause only for that cover
- the configured lock is switched ON; switch and input boolean entities are supported
- switching the lock OFF ends the pause immediately and triggers reevaluation
- pause expiry switches the lock OFF and evaluates exactly once
- repeated movement telegrams do not extend an already active pause
- internal cover feedback is identified through target, direction, tolerance, and time window
- the initial `unavailable → open` state is not treated as manual operation
- immediate user unlock is no longer confused with internal lock feedback
- Safety overrides a local pause and reacts immediately to manual movement

### Room Pause and Master

- added a dedicated expiry timer for room pauses
- Master ON disables automation without counter-movement or automatic reset
- Master OFF triggers immediate reevaluation
- Safety retains higher priority

### Triggers and Load

- full normal evaluation runs every 20 minutes by default
- temperature, normal sun-position, and illuminance state changes are batched
- immediate evaluation is limited to critical releases, Safety, windows, and override expiry

### Card

- fixed local pause state handling without a JavaScript ReferenceError
- reduced icon sizes using `--mdc-icon-size`
- added dedicated section grid rules to avoid excessively narrow rendering
- active Sun Presence pulses; Heat, Safety, and Master states are animated
- effective temperature thresholds control the colors
- the sector abbreviation opens the correct Sun Presence sensor
- the manual button calls the switch correctly through `switch.toggle`

### Diagnostics and Migration

- misleading legacy blocking counters are reset once
- real blocks continue to be counted; `already_correct` and cooldowns are not
- expanded the official Home Assistant diagnostics export and added a separate JSON export
- Config Entry schema 9 and Runtime schema 2
