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
