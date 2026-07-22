# Development

## Local validation

Run from the repository root:

```bash
python -m unittest discover -s tests -v
python -m compileall custom_components/smart_shading
node --check custom_components/smart_shading/frontend/shading.js
node --check custom_components/smart_shading/frontend/smart-shading-card.js
node tests/test_card_runtime.js
python scripts/build_release.py --check
python scripts/ha_e2e/check_wizard_coverage.py
```

With Docker available, run `scripts/ha_e2e/run_lab.sh` before changing setup,
runtime, registry or migration behavior. Setup/Card changes must also pass the
real HA Playwright job described in `docs/HA_E2E_LAB.md`. Every new customer
flow surface or choice must update `wizard_coverage.json` and its executable
scenario owner.

## Branches

- `main`: reviewed releases
- `develop`: integration branch
- `fix/<topic>`: focused bug fixes
- `feature/<topic>`: new behavior

## Sources of truth

- Version: `custom_components/smart_shading/manifest.json`
- Current development changes: `CHANGELOG.md → Unreleased`
- Canonical frontend: `custom_components/smart_shading/frontend/shading.js`
- Canonical resource URL: `/smart_shading/shading.js`

Do not copy the current version into resource URLs or general documentation. The old `smart-shading-card.js` file is only a compatibility loader and must not contain card implementation logic.

## Pull requests

A pull request must describe:

1. the observed behavior;
2. the intended behavior;
3. affected regression cases;
4. validation performed;
5. migration impact.

Any production or release behavior change must update the `Unreleased` section of `CHANGELOG.md`. CI checks this requirement. Update README or detailed documentation whenever installation, configuration, entities, Card behavior, Advanced Mode, or user workflows change.

Do not remove a regression test merely to make a change pass.

## Releases

Release preparation and publication are separate maintainer gates. Do not edit
the manifest version, move changelog sections, create tags, or publish releases
manually.

### Prepare a release

1. Merge each reviewed feature or fix into `develop` and keep
   `CHANGELOG.md → Unreleased` current.
2. Run **Actions → Prepare Release → Run workflow** from the default branch.
3. Choose `beta` with an `X.Y.Z-beta.N` version or `stable` with an `X.Y.Z`
   version. Do not include a leading `v`.
4. Review the generated draft pull request, including its version, changelog,
   documentation, migration impact, and validation checks.
5. Mark the pull request ready and merge it only after review.

For beta releases, preparation branches from `develop` and targets `develop`.
For stable releases, preparation starts from `main`, integrates the tested
`develop` state, and targets `main`. Unexpected promotion conflicts abort the
workflow before it pushes a release branch.

The preparation workflow validates the version and channel, rejects existing
tags or release branches, and runs the full test and package suite. Its release
metadata commit changes only the manifest and changelog; a stable pull request
also contains the tested `develop` promotion described above. It then opens a
reviewable draft pull request and never merges or publishes.

### Publish a reviewed release

After the preparation pull request is merged, run
**Actions → Release → Run workflow** on the merged target branch:

- Beta: branch `develop`, channel `beta`, exact beta manifest version.
- Stable: branch `main`, channel `stable`, exact stable manifest version.

The publication workflow repeats validation, creates the immutable tag, builds
the recovery ZIP, and publishes either a GitHub prerelease or the latest stable
release. The release body comes directly from the matching changelog section.
After a stable publication, synchronize `main` back into `develop` before the
next development cycle.

HACS uses only published releases because `hide_default_branch` is enabled. Beta testers opt into prereleases; production installations stay on stable releases. The repository must remain publicly readable even while it is used only as a custom, non-catalogued HACS repository.
