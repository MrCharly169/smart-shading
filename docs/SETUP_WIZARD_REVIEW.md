# Binding setup-wizard review decisions

This document records the product behavior agreed during the slide-by-slide
setup review. It is not a second user guide. It is a regression contract for
the wizard, runtime, entities, and dashboard Card.

## 1. Entry point and product philosophy

- Easy and Advanced control the same Smart Shading automation, but expose only
  the functions appropriate to the chosen setup type.
- The entry page briefly explains facade-based sun control, profile defaults,
  and the priority of safety and manual control.
- Easy shows only essential fields. Advanced adds schedules, temperature
  stages, Night, Pause, Safety, and individual targets.
- Unsuitable options are hidden instead of merely being disabled.

## 2. Cover type as the central profile

- Every cover group has exactly one physical profile. All assigned covers share
  its strategy.
- The profile defines movement semantics, defaults, visible fields, per-cover
  options, runtime commands, entities, and Card presentation.
- Supported profiles are exterior venetian blind, roller shutter, exterior or
  zip screen, interior curtain, vertical blind, awning, and simple open/close
  cover.
- Changing the profile refreshes the form, resets profile values, removes
  incompatible options, and preserves assigned covers.
- Slat fields exist only for exterior venetian and vertical blinds. Numeric
  position limits do not exist for simple open/close covers.
- Wind and frost safety sources are offered only for exterior profiles where
  that protection is physically meaningful.

## 3. One sun source per sector

- Every sun sector uses exactly one source: sun geometry only, a local Lux
  sensor, or an external on/off sensor.
- Local Lux is recommended. Smart Shading turns it into its own Sun Presence
  entity with hysteresis and delays.
- For an external sensor, `on` means direct sun.
- Sources are never combined. A selected but unavailable source blocks normal
  shading; there is no hidden fallback to Lux, weather, or geometry.
- Easy offers only predefined facade and Lux profiles. Custom angles,
  thresholds, and delays remain exclusive to Advanced.
- Internal keys such as `sun_presence_entity` must never appear in a form.

## 4. Outdoor temperature

- There is no separate temperature-gate switch.
- Without an outdoor-temperature sensor, outdoor temperature is ignored.
- Selecting a sensor automatically enables its minimum condition: normal
  shading starts only after the sensor reaches that value.
- Only the selected room sensor is used. A weather entity is not a fallback.
- The minimum appears only after a sensor is selected.
- If the selected sensor is unavailable, the minimum is not satisfied and
  normal shading waits.

## 5. Easy room and sensor settings

- The page contains the room name and an optional outdoor-temperature sensor;
  after selection, it also contains the minimum.
- Indoor temperature, wind/frost/rain Safety, and other Advanced conditions
  must not appear in Easy.

## 6. End-to-end interaction

- The same contracts apply in initial setup and later Options flows.
- Source-dependent thresholds appear only after their source is selected.
- Night targets appear only with Night, Heat targets only with room
  temperature, and custom Lux values only in Advanced.
- Runtime, diagnostics, and the Card report the same active source and profile
  as the wizard.
- Migrations remove legacy duplicate sources, the former gate switch, and
  profile-incompatible settings.
