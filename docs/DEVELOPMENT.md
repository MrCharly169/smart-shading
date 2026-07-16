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
```

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

### Beta channel

1. Merge tested feature and fix PRs into `develop`.
2. Move completed changelog entries into `## X.Y.Z-beta.N`.
3. Set the manifest to the same `X.Y.Z-beta.N` version.
4. Merge that release preparation into `develop`.
5. Run the Release workflow on `develop`, choose `beta`, and confirm the exact version.

### Stable channel

1. Promote the tested state from `develop` to `main` through a PR.
2. Prepare a stable `## X.Y.Z` changelog section and matching manifest version.
3. Run the Release workflow on `main`, choose `stable`, and confirm the exact version.

The workflow enforces channel-specific branches and SemVer formats, rejects existing tags, runs all validation, creates the tag, builds the recovery ZIP, and publishes either a GitHub prerelease or latest stable release. Release tags are immutable and must not be created manually.

HACS uses only published releases because `hide_default_branch` is enabled. Beta testers opt into prereleases; production installations stay on stable releases. The repository must remain publicly readable even while it is used only as a custom, non-catalogued HACS repository.
