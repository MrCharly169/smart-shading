# Mode architecture

Smart Shading separates runtime decisions from configuration presentation.

## Runtime modes

- Open
- Solar shading
- Heat protection
- Safety
- Paused
- Manual master override
- Finished for the day
- Disabled

Safety has higher priority than ordinary shading, room pauses, and local cover pauses.

Advanced resolves normal decisions through the fixed order Safety → Manual /
Pause → Night → Heat Protection → input-quality hold → Solar → Comfort → Open.
Every candidate, including rejected candidates, is retained with normalized
input quality and a stable reason code. Physical command planning is a separate
stage: it persists ownership per cover, sequences height before slats where
required, and may perform one bounded feedback verification without introducing
a polling loop.

Advanced execution controls remain deliberately small and grouped with their
physical behavior: normal automatic reversal after an external takeover is
opt-in, stagger queues can be room-local or house-wide (with an explicit Safety
bypass), and slatted profiles can opt into a safe slats-before-height opening
order. Easy stores none of these controls.

Protected zones are not another mode. They are Advanced-only Solar target
adjustments scoped to a sector and optionally to cover groups. Each zone keeps
its geometry result in the trace; simultaneous valid intersections choose the
most protective valid target.

## Setup variants

The customer chooses one variant when creating the config entry. Both variants
use the same internal configuration model but expose separate setup and runtime
contracts:

- **Easy:** sun geometry, profile-specific cover targets and one indefinite
  room Manual Override. Every sector selects exactly one geometry, local Lux,
  or external on/off source. Selecting an outdoor-temperature sensor
  automatically adds its minimum condition; no separate switch or fallback
  source exists.
- **Advanced:** exact thresholds, delays, geometry, Lux or external sun
  confirmation, targets, schedules, Safety, Pause, Heat Protection, Night Mode,
  per-cover manual entities and diagnostics.

The choice is immutable. Using the other variant requires a new config entry;
the options flow never exposes a mode switch or settings from the other
variant.

The physical cover profile is the capability source for both variants. It
defines movement semantics, defaults, editable targets, per-cover settings,
entities and card presentation. A profile change resets incompatible values
while retaining the assigned covers.

## Simulation and preview

Advanced simulation evaluates the same normalized input snapshot and decision
resolver as normal automation, but never passes a result to the command
executor. The Details dialog can request a day preview for a selected local
date; the narrow `smart_shading.preview_day` service accepts only a room ID,
optional configuration-entry ID, and date. It cannot issue physical cover
commands or override rule priorities.

## Wizard navigation

The house overview contains house settings, one item per room, Add room, and
Review. A room opens one task menu. Sun sectors, cover groups, and individual
covers each have their own list with independent Add and Back actions; other
tasks open their form directly. No object is copied into the house overview.

Initial Advanced setup offers every applicable task in a fixed order. Night is
configured before Pause, and a pause until the next Night end is offered only
when Night has a complete release source. The final review blocks saving an
incomplete sector, group, cover, source, or dependent option. Easy follows the
same navigation model with only its own applicable tasks.
