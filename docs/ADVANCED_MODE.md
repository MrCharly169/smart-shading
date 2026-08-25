# Advanced Mode behavior

This document preserves the detailed runtime contract behind the customer-facing overview in the [README](../README.md). It describes implemented behavior; it is not a promise of hardware-level safety.

## Decision and execution pipeline

Advanced evaluates relevant source changes event by event and combines related updates through a short debounce. The configured evaluation interval is a recovery watchdog, not a polling loop that repeatedly resends an unchanged target.

The immutable decision order is:

1. active Safety;
2. manual master override, room pause, or local cover pause;
3. Safety-source or Night-source quality hold;
4. Night;
5. Heat Protection;
6. schedule or normal-input-quality hold;
7. Glare Protection;
8. Solar;
9. Comfort;
10. Open or idle hold.

The resolver normalizes priorities centrally; a rule supplied by another module cannot promote itself above Safety. The trace retains the winner, rejected candidates, stable reason codes, and normalized input quality.

Command planning is a separate stage. It owns work per cover, sequences position and slat axes according to the selected profile, supports an optional room- or house-scoped stagger, and can perform one bounded feedback verification with a configured retry limit. A newer authoritative decision can replace an incomplete older command. Higher-priority work, especially Safety, cancels obsolete delayed axes, queued movement, and verification.

## Authoritative inputs and holds

Each sector uses exactly one source: sun geometry, local Lux, or an external on/off direct-sun entity. Local Lux creates Smart Shading's Sun Presence binary sensor with hysteresis and delays. For an external entity, `on` means direct sun.

Sources are never combined. A configured source that is unknown, unavailable, stale when freshness checking is enabled, or otherwise invalid produces an explicit hold for the relevant automation path. A selected outdoor-temperature sensor must satisfy its configured minimum; without a selected sensor, outdoor temperature is ignored.

Missing or invalid Safety and Night sources receive their own holds above the affected automatic modes. Manual control remains available during those holds.

## Schedules, Night, and Heat Protection

The general shading schedule is the master permission for every daytime mode: ordinary shading, Comfort, Solar, calculated glare, and Heat Protection. Night is independent and uses either its configured entity or a Sun-relative period.

Heat Protection can start at most once per local calendar day. It releases at the earliest of the shading-schedule end, sunset plus the configured offset, or the configured latest evening time. Night remains above Heat in the decision order.

Each physical cover group owns its own Night height and, for slatted profiles, Night slat target. A mixed room can therefore close curtains, shutters, and blinds differently while sharing one room-level Night period.

## Calculated glare protection

Glare protection is an explicit Advanced opt-in. The setup wizard asks for one physical cover, the clear window opening, and the table or object area that must remain outside direct sun. Before saving, the wizard validates the geometry and reports whether the current sun position produces a usable intersection and target.

The object calculator supports roller shutters/shades, screens, binary covers, vertical slats, and both symmetric and one-sided sideways curtains. A one-sided curtain is configured with its real left-to-right or right-to-left closing direction. Its moving edge follows the protected sun footprint after that footprint is clipped to the physical window aperture. As the sun sweeps across the object, normal event-driven and watchdog evaluations therefore produce progressive percentage targets instead of applying the old symmetric central-opening formula. The target is determined only by the current geometry, not by elapsed time or the cover's previous position. A condition that becomes true late therefore applies the target already required at that sun position instead of replaying intermediate 15-point steps. A stricter ordinary Solar or Safety target keeps its existing priority. Vertical-slat results are approximate. Exterior Venetian blinds with horizontal slats and awnings are not offered by this calculator.

Each protected zone may also contain native Home Assistant activation conditions. Multiple top-level conditions are ANDed, while compound condition groups can express AND, OR, or NOT. Typical examples are a binary presence zone that must be on or a numeric sensor that must be above or below a threshold. Empty conditions mean that sun and geometry alone control the zone. A false or unavailable condition disables only that zone; it does not block ordinary Solar, Comfort, Heat Protection, or another protected zone. Referenced condition entities trigger an event-driven reevaluation. A separate per-zone switch may disable the sector's Lux or external direct-sun confirmation for low-sun glare. The zone's own minimum sun elevation, facade azimuth, geometry, schedule and conditions still gate it; ordinary Solar and Comfort continue to use the sector source unchanged.

Within the general shading schedule, a valid protected-zone intersection may request glare protection even when the room is too cool for temperature-based shading. It starts from the active Solar or Comfort target, otherwise from Open, and may only make that target more protective. Multiple zones select the most protective axis values. Safety, manual control or pause, Night, and Heat Protection remain higher priority.

The Card shows the effective decision mode on every individual cover row and retains the ordinary target, calculated zone target, final target, geometry status, condition result, and failure reason in its details and diagnostics. Invalid geometry or missing required source data holds movement rather than issuing a guessed target.

## Maximum opening

Maximum opening is an Advanced per-cover execution constraint for position-controlled covers, not another decision mode. The effective target is the lower of the normal decision target and the configured hard limit.

Feedback is checked immediately on cover state changes and through a lightweight 30-second recovery heartbeat. A tight tolerance and command cooldown prevent oscillation. The limit remains active during schedules, room overrides, and manual pauses; only a Safety movement may temporarily exceed it. The Card and diagnostics show normal target, opening limit, and effective target independently.

## External movement and expert execution

New Advanced rooms keep automatic external-movement pause detection off until it is selected. Where numeric position or slat feedback is available, Smart Shading distinguishes its owned command sessions from externally observed changes and requires stable feedback before creating a pause. Covers without usable numeric feedback rely on their configured Manual Override entity.

Advanced expert execution settings include target verification, bounded retries, expected movement and settling time, source freshness, command staggering, stagger scope, optional Safety bypass of the stagger, controlled automatic reversal, and the opening order for compatible slatted profiles. These settings are not stored or exposed by Easy Mode.

Exterior Venetian and vertical-blind height movement normally completes before a delayed slat correction. Compatible profiles can deliberately choose the safe slats-before-height opening order. Closing and single-axis movements retain their profile-specific order.

## Simulation and day preview

Simulation and selected-day preview reuse the production input normalization and decision resolver but never pass a result to the cover command executor. They exist only when the room opts into Test & Preview. The `smart_shading.preview_day` service accepts a room ID, optional config-entry ID, and local calendar date; it cannot issue cover movements or change decision priority.

## Cover semantics

The physical cover type is a functional profile, not a label. It defines supported axes, movement direction, defaults, editable targets, per-cover settings, entities, Card presentation, and runtime services. Changing the profile removes incompatible settings while preserving assigned covers.

Home Assistant cover height uses `0%` closed and `100%` open. Slat position uses Smart Shading's KNX-oriented convention: `0%` fully open/light-through and `100%` fully closed/light-blocking. The per-cover **Invert slats** option is available for compatible covers that expose the opposite direction.
