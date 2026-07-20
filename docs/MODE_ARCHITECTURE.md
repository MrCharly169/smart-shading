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

## Configuration views

Both views write to the same canonical configuration model but expose different
runtime contracts:

- **Easy:** sun geometry, curated cover targets and one indefinite room Manual
  Override. Optional facade lux or direct-sun confirmation, coarse weather
  fallback and an explicit outdoor-temperature gate may refine the result.
- **Advanced:** exact thresholds, delays, geometry, targets, schedules, Safety,
  Pause, Heat Protection, Night Mode, per-cover manual entities and diagnostics.

Switching the view must never silently reset advanced values.
