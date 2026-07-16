# Contributing to Smart Shading

## Change discipline

Keep each pull request focused. Logic fixes, frontend delivery, documentation restructuring, and unrelated features should use separate pull requests.

For every user-visible change:

1. add or update regression tests;
2. add a concise entry under `CHANGELOG.md → Unreleased`;
3. update README or detailed documentation when installation, configuration, entities, Card behavior, Advanced Mode, or workflows change;
4. describe migration impact in the pull request.

## Version discipline

`custom_components/smart_shading/manifest.json` is the only technical version source. Do not put versions in the dashboard resource URL, README headings, repository status files, or frontend source.

The canonical frontend is:

```text
custom_components/smart_shading/frontend/shading.js
```

The canonical Home Assistant resource is:

```text
/smart_shading/shading.js
```

## Required validation

```bash
python -m unittest discover -s tests -v
python -m compileall custom_components/smart_shading
node --check custom_components/smart_shading/frontend/shading.js
node --check custom_components/smart_shading/frontend/smart-shading-card.js
node tests/test_card_runtime.js
python scripts/build_release.py --check
```

## Release process

Releases are started only through **Actions → Release → Run workflow**.

- Beta: select `develop`, channel `beta`, and a manifest version matching `X.Y.Z-beta.N`.
- Stable: select `main`, channel `stable`, and a manifest version matching `X.Y.Z`.

Before running the workflow, create the matching version section in `CHANGELOG.md` and update the manifest. Type that exact version in the workflow confirmation input. The workflow creates the immutable `v<manifest-version>` tag and GitHub release only after all checks pass. Do not create release tags manually.
