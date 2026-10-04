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


## Seasonal schedule feedback

An inactive shading schedule replaces the passive Open/Ready/Done headline with
Outside schedule (Außerhalb des Zeitplans). The secondary message explains that
configured protection remains active. Safety, room pause, disabled, Night and
actively running shading modes retain their existing priority. This presentation
does not claim that every room has Glare configured or that protection is
currently actuating equipment. The summer preset becomes May–October in both
house and room flows; existing saved schedules are not silently migrated.

Card runtime tests cover English/German, inactive/active transitions and
active-mode priority.

A physical-movement race was reproduced on the unmodified production source:
with an inactive schedule and open behavior, a cover movement starts the normal
confirmation window. An intervening sun update sends an Open target. Its own
command session then hides the candidate and prevents pause activation. The fix
adds a temporary per-cover planner constraint and cancels that cover's pending
non-safety work through the existing durable cancellation path. It does not
lower movement thresholds, disable command-feedback ownership, publish an
unconfirmed pause, or block safety commands. The hold expires with the existing
candidate window. Regression tests cover the original failing sequence, expiry,
return to baseline, safety priority, and another cover's queued work.

Physical wall-switch acceptance requires a separate installation-specific test.
