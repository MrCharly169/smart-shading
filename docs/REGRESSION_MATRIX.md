# Regression matrix

The following behaviors must remain covered when Smart Shading is changed.

| Area | Required behavior | Existing coverage |
|---|---|---|
| Lux parsing | Decimal and localized lux values do not collapse to zero | `tests/test_logic.py` |
| Lux-derived sun confirmation | Independent ON/OFF thresholds, delays, and pending-state cancellation | `tests/test_logic.py` |
| Geometry | Sector azimuth and effective sun confirmation remain separate conditions | `tests/test_logic.py` |
| Manual feedback | Initial state synchronization does not create a manual override | `tests/test_logic.py` |
| Own movement | Feedback moving toward a recent Smart Shading target is not manual | `tests/test_logic.py` |
| Local override | Confirmed external movement pauses the affected cover or its room-local shared Manual group | `tests/test_manual_detection.py` and `tests/test_manual_service_detection.py` |
| External-move trace | A confirmed external cover movement triggers an immediate normal or Safety evaluation after its local ownership pause is active | `tests/test_manual_detection.py` and `tests/test_engine_runtime.py` |
| Locks | Releasing one cover lock must not unlock unrelated covers | `tests/test_engine_runtime.py` |
| Safety | Safety remains higher priority than normal automation pauses | engine/package tests |
| Scheduling | Periodic room evaluation defaults to the documented interval | package tests |
| UI layout | Card remains responsive and does not clip side content | `tests/test_package.py` |
| Details dialog | Details is a document-level modal, not inline content | `tests/test_package.py` |
| Card runtime | Card registers and handles configuration in a browser-like runtime | `tests/test_card_runtime.js` |
| Setup variants | The setup choice is immutable; Easy remains geometry-first; Advanced retains its additional layers; options and customer status expose no cross-mode bridge | `tests/test_flow_contract.py`, `tests/test_engine_runtime.py`, and `tests/test_package.py` |
| Schema-16 migration and freshness | The v4.6.2 schema-15 baseline is normalized on upgrade; Easy strips Issue #79 execution fields, and a freshness limit of `0` remains opt-in/disabled | `tests/test_engine_runtime.py`, `tests/test_package.py`, and `tests/test_flow_contract.py` |
| Decision priority and trace | One deterministic resolver retains the winner, every rejected candidate and its resolution reason, normalized input quality, and stable reason codes | `tests/test_decision.py` and `tests/test_card_runtime.js` |
| Protected zones | Advanced Solar geometry adjusts only applicable groups; invalid geometry is visible but safely falls back; overlapping zones select the most protective target | `tests/test_decision.py` and options-navigation coverage |
| Command lifecycle | Per-cover ownership, cancelable sequence steps, stagger queues, bounded verification and restart-safe serialized work remain finite | `tests/test_execution.py` and runtime integration coverage |
| Restarted house stagger | Persisted House-scope queue slots remain House-scoped after a restart and cannot be bypassed by another room | `tests/test_execution.py::CommandPlannerTests.test_restored_house_stagger_scope_stays_shared_across_rooms` |
| Venetian opening | A profile can tilt slats before raising height, while closing and single-axis moves retain their safe order | `tests/test_execution.py::CommandPlannerTests.test_venetian_can_open_slats_before_raising_when_profile_requires_it` |
| Heat lifecycle | Heat is armed/active/held/released at most once per day and remains subordinate to Safety and Night | runtime integration coverage |
| Simulation | Simulation projects virtual per-cover window, lock and pause constraints into final targets and never dispatches a cover service | `tests/test_engine_runtime.py` and `tests/test_card_runtime.js` |
| Selected-date preview | The Advanced dialog sends the chosen local calendar date through the narrow preview service, preserves date focus on refresh, and falls back safely on an older backend | `tests/test_card_runtime.js` and `e2e/ui/card.spec.js` |
| Read-only details entry | Advanced trace, simulation, and preview remain reachable when normal action buttons are intentionally hidden | `tests/test_card_runtime.js` and `e2e/ui/card.spec.js` |
| Event-driven evaluation | Input bursts debounce into one evaluation, exact boundaries wake the engine, and the watchdog does not duplicate an active target | runtime integration coverage |
| Disabled sectors | A disabled Advanced sector never falls through to an Open target or creates a physical command | `tests/test_engine_runtime.py::EngineRuntimeTests.test_disabled_sector_never_plans_open_fallback` |
| Packaging | Manifest, permanent card resource, release workflow, and HACS structure are coherent | package and release tests |

Any bug fixed after this baseline should add a new row and an automated test whenever technically possible.
