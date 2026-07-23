# Issue #79 release acceptance

This document is the release acceptance record for Issue #79, “Next major
version: strengthen the decision engine, movement execution, diagnostics, and
simulation.” It applies to the first public stable release, expected to be
`2026.7.0`. The legacy `5.0.0-beta.0` candidate remains part of its evidence;
future candidates use the calendar-version format.

No item may be silently deferred. A deferral needs a documented maintainer
decision, an issue link, an explicit compatibility impact, and a revised
acceptance owner. A failed gate means the candidate is not accepted.

## Release intent and version discipline

- Work is integrated and qualified on `develop` first.
- Beta candidates use `YYYY.M.PATCHbN` and are prepared and published only
  from `develop`.
- The stable candidate uses `2026.7.0` and is prepared and published only from
  `main`, after the release workflow integrates the tested `develop` state.
- Versions are entered into GitHub Actions without the leading `v`; published
  tags use it, for example `v2026.7.0`.
- Tags and releases are immutable. Do not repair a failed publication by
  changing a tag; publish a new version after the root cause is fixed.
- `manifest.json` and the dated matching `CHANGELOG.md` section are the only
  release metadata sources. Do not update either manually as a shortcut around
  the Prepare Release workflow.

The generated release-preparation pull request deliberately does not close
Issue #79. It may refer to the issue for traceability, but Issue #79 is closed
only after the published tag has passed the post-publication HACS gate below.

## Functional acceptance

The release reviewer must have evidence for all of the following. Each fixed
regression receives a focused automated test and a row in
`docs/REGRESSION_MATRIX.md`.

| Area | Required acceptance evidence |
|---|---|
| Decision pipeline | Pure, deterministic candidates and one centrally resolved winner; Safety, manual/pause, Night, Heat, schedule, Solar, profile mapping, and window constraints have tested precedence. |
| Decision trace | Stable, localized reason codes show the winner, every rejected candidate with its resolution reason, relevant normalized input quality, final cover targets, and command outcome. The Card summary and diagnostics details agree. |
| Event-driven operation | State changes and exact timers evaluate once; related bursts are debounced; restart reconstructs required timer state; the watchdog does not resend an unchanged target. |
| Command ownership | Persisted per-cover ownership survives restart; own feedback is not treated as manual control; true external movement follows the configured pause policy; state-only KNX updates do not create a false override. |
| Execution | Profile-aware target mapping, finite verification/retry, sequence replacement/cancellation, configurable safe Venetian height/tilt opening order, tilt-only correction, and restart-safe room/House stagger queues are covered. Safety can pre-empt queued work. |
| Heat lifecycle | Internal phases persist, activate at most once per day, retain the documented hold behavior after sun loss, and always yield to Safety. |
| Input quality | `unavailable`, `pending`, `stale`, invalid, and valid values are distinguishable. Invalid normal inputs do not start new shading and Easy never combines its selected source with a hidden fallback. |
| Simulation and preview | Customer simulation and developer scenarios use the production decision path, project virtual per-cover window/lock/pause constraints, emit no cover services, export reproducible results, and include selected-date day-preview transitions. |
| Glare protection | Advanced-only protected zones stay inside Solar logic; valid intersections adjust only affected groups, multiple zones select the most protective valid target, and missing geometry falls back safely. |
| UI and language | Easy exposes no Advanced controls; Advanced remains reachable even when operational actions are hidden; selected date, trace/diagnostics, and keyboard focus are usable on desktop and mobile; and changed Home Assistant strings exist in both English and German. |

## Migration acceptance

The migration is accepted only when an upgrade from the latest stable
release, currently `v4.6.2`, succeeds. The automatic upgrade workflow selects
the highest normal-release tag and excludes both legacy `-beta.N` and current
`bN` prerelease tags; this prevents `v4.6.2-beta.9` from accidentally becoming
the release baseline.

The migration evidence must show that it preserves or explicitly and safely
migrates:

- House → Room → Sun sector → Cover group → Cover structure and assignments;
- the immutable Easy or Advanced setup variant, with no Advanced fields leaking
  into Easy;
- cover profile capability and slat-inversion semantics;
- entity unique IDs wherever technically possible, as well as the stable card
  resource `/smart_shading/shading.js`;
- Manual entities, pauses, targets, Night/Safety/Heat settings, and runtime
  ownership/ledger state;
- runtime storage schema/version data, including restart reconstruction.

Run an additional upgrade check from the newest beta when it contains a
different on-disk schema. That supplemental beta check never replaces the
required `v4.6.2` stable-baseline check.

## Required local evidence

Run the fast suite on the exact candidate commit. The release workflow uses
Python 3.13 and Node 22, so use those versions for final local evidence.

```bash
python -m unittest discover -s tests -v
python scripts/ha_e2e/check_wizard_coverage.py
python scripts/check_source_syntax.py
node tests/test_card_runtime.js
node tests/test_browser_error_attribution.js
python scripts/build_release.py --check
```

After the candidate has the prepared `2026.7.0` manifest and dated changelog
section, also verify the exact release contract and generated release notes:

```bash
python scripts/validate_release_channel.py \
  --channel stable --branch main --confirm-version 2026.7.0
python scripts/build_release.py --check --tag v2026.7.0
python scripts/build_release.py \
  --tag v2026.7.0 --output /tmp/smart_shading-v2026.7.0.zip
python scripts/release_changelog.py notes \
  --version 2026.7.0 --output /tmp/smart_shading-v2026.7.0-notes.md
```

With Docker and unused loopback ports available, collect real Home Assistant
evidence from the candidate. Each run uses only disposable fixtures and writes
diagnostics to the selected artifact directory.

```bash
HA_E2E_PORT=18123 \
HA_E2E_IMAGE=ghcr.io/home-assistant/home-assistant:stable \
HA_E2E_ARTIFACT_DIR=/tmp/smart-shading-ha-stable \
scripts/ha_e2e/run_lab.sh

HA_E2E_PORT=18124 \
HA_E2E_IMAGE=ghcr.io/home-assistant/home-assistant:beta \
HA_E2E_ARTIFACT_DIR=/tmp/smart-shading-ha-beta \
scripts/ha_e2e/run_lab.sh

HA_E2E_PORT=18126 \
HA_E2E_UPGRADE_FROM_REF=v4.6.2 \
HA_E2E_ARTIFACT_DIR=/tmp/smart-shading-ha-upgrade-v4.6.2 \
scripts/ha_e2e/run_lab.sh
```

For the real Card/browser acceptance, install the pinned Playwright dependency
and run it within the same disposable HA laboratory:

```bash
npm --prefix e2e/ui install --ignore-scripts
npx --prefix e2e/ui playwright install --with-deps chromium
HA_E2E_RUN_UI=1 \
HA_E2E_PORT=18125 \
HA_E2E_ARTIFACT_DIR=/tmp/smart-shading-ha-ui \
scripts/ha_e2e/run_lab.sh
```

When a wizard surface, choice, Boolean control, or persisted transition changes,
update `e2e/ha/scenarios/wizard_coverage.json` and its real execution owner.
When an interaction changes, add deterministic fixture/scenario coverage and
retain the resulting JSON, JUnit, log, registry, screenshot, trace, and video
evidence. Do not rely on unit tests alone for config flow, storage migration,
or browser behavior.

## CI and maintainer gates

Before merging each implementation pull request, `validate.yml` must pass:

1. changelog policy for production changes;
2. all Python tests;
3. wizard-coverage ownership validation;
4. Python, JavaScript, JSON, shell, and workflow syntax validation;
5. Card and browser-error runtime tests; and
6. package validation and archive build.

For relevant changes, retain successful artifacts from the clean Home
Assistant lifecycle, browser/Card, upgrade, and Stable/Beta matrix workflows.
Review any artifact that contains a failure or warning attributable to Smart
Shading before approving the release-preparation pull request.

The release workflow repeats the fast suite and blocks publication on all of
these reusable jobs:

1. clean real Home Assistant lifecycle;
2. real Home Assistant browser/Card suite;
3. previous-release upgrade laboratory, whose default baseline is the newest
   stable tag; and
4. Stable and Beta Home Assistant matrix runs for the exact candidate SHA.

The reviewer must additionally confirm the generated manifest version,
publication-ready dated changelog text, EN/DE documentation and migration
notes, release ZIP contents, and the absence of unresolved review feedback.

## Publication and post-publication HACS acceptance

1. Run **Prepare Release** with `stable` and `2026.7.0` from the default branch.
   It creates `release/v2026.7.0`, merges the tested `develop` state into a
   reviewable promotion PR, generates the dated changelog section, and
   dispatches normal validation.
2. Review and deliberately merge that PR into `main`. Verify that the Actions
   setting allowing workflow-created pull requests remains enabled. The
   manifest-version change on `main` starts **Release** automatically.
3. Use the manual **Release** entry only to retry an infrastructure failure,
   selecting `main` and typing the exact `2026.7.0` confirmation. The workflow
   may create `v2026.7.0`, the attached recovery ZIP, and the latest GitHub
   release only after every pre-publication gate passes.
4. Treat `ha-hacs-qualification` as a mandatory final acceptance gate. It runs
   after publication because HACS can only resolve a published tag. It must
   show that the official HACS backend accepts the public repository, selects
   exactly `v2026.7.0`, downloads the public source archive whose manifest is
   `2026.7.0`, and completes a fresh real-Home-Assistant lifecycle from that
   artifact.
5. Inspect the retained HACS artifact and mark the release accepted only after
   that job succeeds. Then synchronize `main` back to `develop` and close
   Issue #79 with links to the release, successful workflow run, migration
   evidence, and HACS qualification artifact.

If HACS qualification fails, the GitHub release and tag already exist. Do not
claim Issue #79 is complete or retag the version. Triage the failure, preserve
the evidence, publish a corrective immutable version through the same gates,
and close the issue only after that corrective version passes HACS acceptance.
