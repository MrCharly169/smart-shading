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

## Planned configuration views

A future Easy/Advanced split must not create two different engines. Both views must write to the same canonical configuration model:

- **Easy:** curated presets and essential choices
- **Advanced:** exact thresholds, delays, geometry, targets, and diagnostics

Switching the view must never silently reset advanced values.
