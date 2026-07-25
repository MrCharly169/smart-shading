# Mode architecture

Smart Shading separates runtime decisions from configuration presentation.

## Runtime modes

- Open
- Comfort shading
- Solar shading
- Glare protection
- Heat protection
- Safety
- Paused
- Manual master override
- Finished for the day
- Disabled

Safety has higher priority than ordinary shading, room pauses, and local cover pauses.

Advanced resolves normal decisions through the fixed order Safety → Manual /
Pause → Night → Heat Protection → input-quality hold → Glare Protection →
Solar → Comfort → Open.
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

Calculated protected zones produce an explicit Advanced glare mode for one
physical cover. A zone can trigger independently of the temperature stages
when direct Sun reaches the measured object, but only inside the general
shading schedule. It starts from the active Solar or Comfort target, otherwise
from Open, and may only make that target more protective. Simultaneous valid
intersections choose the most protective axis values. Every hit, miss, invalid
calculation, ordinary target and final target remains in the per-cover trace.

The general shading schedule is the master permission for every daytime mode:
Comfort, Solar, glare and Heat Protection. Night is the sole independent
automatic mode and uses its own entity or Sun-relative period. Heat Protection
is latched to one cycle per calendar day and releases at the earliest of the
schedule end, sunset plus offset, or the absolute latest configured time.

Maximum opening is an Advanced per-cover execution constraint, not another
decision mode. For opted-in position covers, the executor uses the lower of
the decision target and the configured limit. Cover feedback is checked on the
state event and by a 30-second recovery heartbeat. Manual pauses, room
overrides and the daytime schedule do not suspend this physical constraint;
Safety may temporarily exceed it. A tight tolerance plus the existing command
cooldown prevents feedback loops.

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

Target ownership remains group-local even when activation is room-wide. Night
Mode owns only its time source, offsets and handover; each cover group owns its
Night height and optional Night slat target alongside its other profile
positions. Newly selected Advanced features enter a focused setup queue that
contains only those new selections, then return to the room when complete.

## Simulation and preview

Advanced simulation evaluates the same normalized input snapshot and decision
resolver as normal automation, but never passes a result to the command
executor. The Details dialog can request a day preview for a selected local
date; the narrow `smart_shading.preview_day` service accepts only a room ID,
optional configuration-entry ID, and date. It cannot issue physical cover
commands or override rule priorities.

## Wizard navigation

The house overview contains one item per room, Add room, and
Review. A room opens one task menu. Sun sectors, cover groups, and individual
covers each have their own list with independent Add and Back actions; other
tasks open their form directly. No object is copied into the house overview.

Initial Advanced setup first keeps the customer in the room-structure hub
until every facade, group and cover has been added. Optional features are
selected only after the customer explicitly completes that structure. Night
is configured before Pause, and a pause until the next Night end is offered
only when Night has a complete release source. If a later cover profile
unlocks glare protection or maximum opening, the editing flow reports the new
feature once and links to the room feature selection. The final review blocks
saving an incomplete sector, group, cover, source, or dependent option. Easy
follows the same navigation model with only its own applicable tasks.

Every optional-feature form identifies the room, feature, progress and next
feature. Calculated glare setup is a guided measurement followed by a pre-save
validation and live calculation check; no zone is persisted until the customer
confirms that check.
