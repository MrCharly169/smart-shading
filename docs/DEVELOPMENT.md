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

1. Move completed entries from `Unreleased` into a section matching the release version.
2. Update `manifest.json` once.
3. Validate locally.
4. Merge through the normal review flow.
5. Tag the release commit with `v<manifest-version>`.

The release workflow rejects mismatched tags, reruns validation, builds the ZIP, and publishes the GitHub release automatically.
