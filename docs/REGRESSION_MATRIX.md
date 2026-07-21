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
| Locks | Releasing one cover lock must not unlock unrelated covers | `tests/test_engine_runtime.py` |
| Safety | Safety remains higher priority than normal automation pauses | engine/package tests |
| Scheduling | Periodic room evaluation defaults to the documented interval | package tests |
| UI layout | Card remains responsive and does not clip side content | `tests/test_package.py` |
| Details dialog | Details is a document-level modal, not inline content | `tests/test_package.py` |
| Card runtime | Card registers and handles configuration in a browser-like runtime | `tests/test_card_runtime.js` |
| Setup variants | The setup choice is immutable; Easy remains geometry-first; Advanced retains its additional layers; options and customer status expose no cross-mode bridge | `tests/test_flow_contract.py`, `tests/test_engine_runtime.py`, and `tests/test_package.py` |
| Packaging | Manifest, permanent card resource, release workflow, and HACS structure are coherent | package and release tests |

Any bug fixed after this baseline should add a new row and an automated test whenever technically possible.
