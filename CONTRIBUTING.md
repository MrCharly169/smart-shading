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

Release preparation and publication are separate maintainer actions.

### Prepare a release

Run **Actions → Prepare Release → Run workflow** from the default branch.

- Beta versions must match `YYYY.M.PATCHbN`, for example `2026.8.0b0`.
  The workflow branches from `develop` and opens a draft pull request back to
  `develop`.
- Stable versions must match `YYYY.M.PATCH`, for example `2026.7.0`. The
  initial monthly release uses `.0`; fixes increment the patch. The workflow
  creates the release branch from the current `main`, integrates the tested
  `develop` state locally, and opens a draft promotion pull request back to
  `main`. Unexpected merge conflicts abort before the branch is pushed. The one
  historical add/add conflict for `.github/workflows/release.yml` is resolved
  explicitly in favor of the tested `develop` version; every other conflict
  requires manual reconciliation.

The workflow validates the requested version, checks for an existing tag, runs the complete test and package suite, updates the manifest, and moves `CHANGELOG.md → Unreleased` into a dated release section. Stable preparation can aggregate beta sections since the previous stable release when `Unreleased` is empty. It then pushes only a dedicated release branch and opens a draft pull request. It cannot merge or publish a release.

Review the generated pull request for version, channel, changelog quality, documentation completeness, migration impact, and release readiness. Repository settings must allow GitHub Actions to create pull requests; approval and merging must remain manual.

### Publish a reviewed release

Merging the release pull request starts publication automatically:

- a manifest-version change on `develop` publishes a Beta;
- a manifest-version change on `main` publishes a Stable.

The manual **Actions → Release → Run workflow** entry remains available only
to retry the same branch after an infrastructure failure; it requires the exact
manifest version as confirmation. The release workflow repeats all validation,
creates the immutable `v<manifest-version>` tag and installation ZIP, and
publishes the GitHub release. Its release body is the exact content of the
matching changelog section. Do not create release tags or GitHub releases
manually.

After publishing a stable release, synchronize `main` back into `develop` before starting the next release cycle. This preserves the stable changelog boundary used by later stable aggregation.
