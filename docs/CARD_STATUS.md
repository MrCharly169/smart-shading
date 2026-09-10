# Compact room status

The Advanced Card's top-right status is the single compact surface for active
safety observations. Configured wind/frost/rain inputs and window contacts update
from the same HA state references used by the render signature. Unknown or
unavailable contacts are not reported as open. Multiple alert types are combined;
the tooltip and Details retain all source-specific observations.

The status opens Details. The permanent Safety marker, safety/window shortcuts
and operating-profile selector do not occupy the main toolbar. Details retains
the general safety explanation, every source's current state and native entity
interaction, schedule active/inactive information, and the existing operating-
profile selector (including the inherited global-house scope).

This is presentation only: it does not activate a protection feature, change
profile selection, re-evaluate a room or issue a device command. Existing stable
DOM reconciliation, delegated actions and external-scroll isolation remain.
English and German are maintained together using the active HA app language.

Regression owner: `tests/test_card_runtime.js`; real browser/scroll ownership
remains in `e2e/ui/card.spec.js`. Physical phone acceptance remains a user check.
