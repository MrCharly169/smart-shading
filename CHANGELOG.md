# Changelog

## Unreleased

### Initial setup hotfix

- restored the first-room form handler so both Easy and Advanced setup can
  continue after House settings instead of ending with an invalid flow


## 4.6.2-beta.5 - 2026-07-21

### Logical setup profiles

- made the selected physical cover type the shared capability contract for the
  setup wizard, runtime targets, configuration entities, per-cover options and
  dashboard presentation
- added interactive source-dependent forms that reveal thresholds only after a
  matching sensor is selected and hide unsupported profile settings
- removed the separate Easy outdoor-temperature gate; selecting a room sensor
  now activates its minimum automatically without a weather fallback
- made geometry, local Lux and external on/off confirmation strictly exclusive,
  with local Lux creating the integration's Sun Presence binary sensor in both
  setup variants
- added schema 15 migration cleanup for legacy gate values, competing sun
  sources, custom Easy thresholds and profile-incompatible settings
- expanded the German and English setup guidance and recorded the reviewed
  wizard contract for future regressions


## 4.6.2-beta.4 - 2026-07-21

### Setup wizard

- rebuilt initial setup and later editing around one consistent house, room, task, and object-list navigation
- added independent add loops for rooms, sun sectors, cover groups, and individual covers, with a blocking final review for incomplete objects
- made Advanced setup offer every applicable function in a fixed order, with Night before Pause and safe Night-end pause recovery
- kept external sun confirmation available in both setup variants while making geometry, Lux, and external sources explicit and mutually exclusive
- removed ineffective or source-less controls and replaced internal labels with concise, complete English and German guidance
- hardened the immutable setup choice, saved runtime overrides, temperature units, pause migration, and Easy/Advanced entity boundaries


## 4.6.2-beta.3 - 2026-07-21

### Setup product separation

- lock the setup product after the initial Easy or Advanced choice and remove the later mode switch from house settings
- migrate conflicting mode values out of legacy options and enforce the original choice again at runtime
- keep the same task-based navigation while exposing only the functions available to the selected installation
- remove repeated product terminology and internal-looking customer titles from the English and German setup text
- offer the clearly labelled External sun confirmation in both setup variants and make it authoritative over Lux when configured
- add regression coverage for immutable setup selection, customer-facing titles, product wording, and full-mode binary sun confirmation


## 4.6.2-beta.2 - 2026-07-21

### Customer setup

- replaced the room object tree with task-based Room details, Sun sectors, Cover groups, Individual covers, Automation, Night, Pause, and Safety pages
- added category counters and dedicated object lists so adding or editing one sector, group, or cover never expands the room overview
- changed initial setup from a one-page early finish into a complete review flow that offers per-cover Manual Entities, Night before Pause, temperatures, Heat Protection, safety, and open-ended add loops before startup
- offers the next-Night-end pause only when Night has a usable sun or entity source and safely falls back to the next morning when Night is later disabled
- renamed the optional binary source to External sun confirmation and explains that a Lux source creates Smart Shading's own Sun Presence status
- reduced repeated Simple/Complete terminology after the initial choice and added concise English and German help for every newly reachable page


## 4.6.2-beta.1 - 2026-07-21

### Setup navigation

- replaced the flattened options overview with one entry per room plus house-wide actions
- added one room-scoped submenu that keeps sectors, cover groups, covers, and add actions inside their owning room
- kept every object editor as a directly opened, sectioned form with contextual English and German titles and help text
- return to the selected room after saving a room object instead of jumping back to the house overview
- added navigation regressions proving that sectors, groups, and covers can never leak into the root menu again


## 4.6.2-beta.0 - 2026-07-20

### Final Easy and Advanced setup

- rebuilt the active setup contract around a sensorless Easy baseline with optional facade lux, binary direct-sun confirmation, coarse weather fallback, and an explicit outdoor-temperature gate
- kept schedules, Safety, Pause, Heat Protection, Night Mode, per-cover manual entities, and external-movement detection exclusive to Advanced Mode
- made every optional entity selector genuinely optional and protected existing sectors, cover groups, and cover settings while rooms are edited or reordered
- kept saved Options on Home Assistant's single reload path so mode, listeners, entities, and card behavior update without duplicate setup races
- removed Evaluate entities from Easy Mode; its only user control is the indefinite room Manual Override
- added config-entry migration version 13 without discarding dormant Advanced settings

### Manual overrides and room lifecycle

- grouped identical per-cover Manual Override entities within a room so activation, release, expiry, and external movement operate on the complete group with one entity write
- room Pause and Resume now synchronize every unique Manual Override entity exactly once, including shared groups
- card setup notifications are now created only after a new room has a registered status entity and are not recreated by room edits, reloads, or restarts

### Dashboard cards

- refined the separate Easy and Advanced cards with source-aware status text, honest unavailable feedback, centered controls, and one calm reduced-motion-aware pulse language
- limited the Easy Card to its indefinite room Manual Override while Advanced retains Pause, Evaluate, Night, diagnostics, and detailed sector feedback
- stopped unrelated Home Assistant updates from rebuilding the main card or Advanced dialog, preserved dialog focus and scroll position, and added lifecycle cleanup for detached cards
- made the Advanced Night shortcut resolve a configured Schedule helper and open its graphical editor, with normal More Info as the safe fallback for other sources

### Quality

- expanded runtime, migration, shared-entity, notification, card lifecycle, translation, and release regression coverage while retaining the established KNX slat and feedback-based pause behavior
- removed obsolete bootstrap and duplicate-template files, aligned all repository documentation to English, and updated the release and pilot guides to the current two-stage workflow and Easy/Advanced contracts


## 4.6.1-beta.1 - 2026-07-20

### Dashboard Cards

- replaced the shared reduced layout with a dedicated Easy Card that keeps a simplified visual Sun-sector track, compact cover feedback, Evaluate, and the indefinite room Manual Override only
- retained the detailed Sun geometry, sector status, cover targets, Pause, Night, and diagnostic controls exclusively in the Advanced Card
- centered every card and Advanced View icon through one fixed square icon-box system instead of browser-dependent icon baselines or mobile offsets
- the Advanced Night shortcut now opens a configured Home Assistant Schedule helper directly in its graphical settings editor, while non-Schedule Night sources retain the normal More Info fallback
- added frontend regressions for the separate Easy and Advanced markup, approved Easy controls, icon containers, and Night Schedule editor routing


## 4.6.1-beta.0 - 2026-07-20

### Easy and Advanced Modes

- Easy Mode is now a separate runtime instead of a visual preference: only Home Assistant sun geometry, facade sectors, cover targets, and one room-level Manual Override are active
- Easy Mode no longer executes schedules, Sun Presence or lux checks, temperature and weather conditions, Safety inputs, Pause, Heat Protection, Night Mode, per-cover manual entities, or external movement detection
- the room Manual Override disables Easy Mode indefinitely and is released only by the user, the card, or an explicit external automation
- Advanced Mode retains the complete Smart Shading feature set; existing Advanced configuration remains stored when switching to Easy Mode
- new rooms opt in to feedback-based external movement detection, while migrated Advanced installations retain their previous behavior

### Setup and Entities

- replaced the multi-page initial room wizard with one mode-aware room page after the house/mode selection
- Easy setup asks only for the room, facade direction, cover type, and covers; Advanced setup adds its optional sensors, schedule, pause, Sun Presence, slat profile, diagnostics, and movement detection on the same page
- Easy Mode exposes only house and room status, the room Manual Override, and explicit evaluation controls; Advanced-only configuration, pause, sector, Sun Presence, and diagnostic entities are no longer created in Easy Mode
- added config-entry migration version 12 and English/German guidance describing the effective differences between both modes

### Dashboard Card

- the card now derives Easy or Advanced rendering from the integration instead of a separate card setting
- removed the room selector and removed Pause and Advanced View from the Easy card
- Advanced cards show sector azimuth ranges, a more detailed active-sector status, and a direct Night schedule shortcut
- centered action icons consistently across mobile and desktop and replaced rapid effects with calm, reduced-motion-aware animations
- throttled Advanced View updates and preserved its scroll position while live states refresh


## 4.6.0-beta.9 - 2026-07-20

### Night Mode

- added an Advanced Mode-only Night Mode that can be configured per room from a schedule, helper, binary entity, or sunset/sunrise with offsets
- Night Mode uses dedicated per-layer targets, including KNX slat semantics where `0%` is open and `100%` is closed, while Safety and explicit pauses retain higher priority
- evening and morning transition windows prevent unnecessary open-close movement and hand directly from Night Mode to active solar shading when possible
- unknown or unavailable Night sources hold the current positions instead of issuing unsafe fallback movements
- added an optional pause duration until the end of the next Night; only pauses created with that duration are released at the Night transition
- exposed Night configuration and runtime details in the English and German setup flow, room card, entities, and diagnostics


## 4.6.0-beta.8 - 2026-07-20

### Slat Position

- Smart Shading now uses the KNX slat scale throughout: `0%` is fully open and `100%` is fully closed, while cover-height semantics remain unchanged
- Open and Safety use fully open slats, Heat Protection uses fully closed slats, and all adaptive presets and custom curve values follow the same scale
- existing config-entry targets and persisted layer-number overrides migrate once from the former opening percentage to the new KNX slat position
- the per-cover slat inversion remains available for covers that expose the opposite direction, with clearer English and German setup guidance


## 4.6.0-beta.7 - 2026-07-20

### Manual Operation

- external cover movement can now be confirmed when an actuator publishes only one final numeric position or tilt value; Smart Shading verifies that the value remains stable for five seconds before pausing the cover
- additional numeric progress restarts the stability timer, while feedback returning to the accepted baseline, active Smart Shading ownership, window automation, and safety contexts remain harmless
- downloadable room diagnostics now include per-cover movement candidates, pending stability timers, decision reasons, and active window-automation contexts


## 4.6.0-beta.6 - 2026-07-20

### Manual Operation

- cover state strings are now informational only and can no longer confirm an external movement or manual service intent
- automatic pause detection requires directionally consistent numeric height or tilt feedback followed by a stable value; isolated updates and candidates returning to their baseline are rejected
- Smart Shading diagnostics expose the numeric feedback availability, accepted baseline, candidate evidence, and confirmation or rejection reason for each cover
- covers without usable numeric position or tilt feedback continue to use their explicit Manual Override entity only
- added a KNX/Theben troubleshooting guide for false movement caused by readable UP/DOWN command objects while keeping the global KNX state updater enabled


## 4.6.0-beta.5 - 2026-07-18

### Window Contacts

- cover movement linked to a configured unsafe window state and its return movement after the window closes no longer create a false manual pause
- each cover exposes a setup option, enabled by default, to return cleanly to the current automation target after the window closes
- explicit Home Assistant user commands, manual entities, room pauses, and safety behavior remain authoritative during the window automation context


## 4.6.0-beta.4 - 2026-07-18

### Manual Operation

- Smart Shading now claims cover feedback before dispatching its own service call, closing the race with immediate Home Assistant or KNX state updates
- delayed, non-monotonic, and coupled KNX position or tilt feedback remains owned by the active Smart Shading command session and cannot create a manual pause
- command ownership ends after the commanded target settles or after a hard timeout; explicit external Home Assistant commands retain their intent across delayed KNX feedback and manual entities remain authoritative


## 4.6.0-beta.3 - 2026-07-18

### Manual Operation

- external and physical cover movement detection is enabled by default
- KNX feedback may confirm an external movement within 60 seconds
- Smart Shading's own movement feedback and isolated status refreshes do not create a pause
- confirmed external movement pauses only the affected cover and synchronizes its configured manual entity

### Release Process

- added a manually triggered Prepare Release workflow that creates a dedicated, reviewable draft pull request instead of publishing directly
- beta preparation branches from and targets `develop`; stable preparation starts from current `main` and integrates the tested `develop` state before opening its promotion pull request
- unexpected stable-promotion merge conflicts now abort before any release branch is pushed; only the known historical release-workflow add/add conflict is resolved from tested `develop`
- release preparation validates the channel, version, source and target branches, existing tags, releases, and release branches
- the manifest version and a dated changelog section are prepared together while preserving an empty `Unreleased` section
- stable preparation can assemble beta history since the previous stable version into an editable draft
- the separate publication workflow now uses the exact prepared changelog section as its GitHub release body
- added regression coverage for preparation, stable aggregation, dated headings, and changelog note extraction


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
