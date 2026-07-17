# Smart Shading

Smart Shading is a Home Assistant custom integration for sector-based shading using sun geometry, illuminance, temperature, safety inputs, window contacts, and manual overrides.

- **Home Assistant:** 2026.6 or newer
- **Integration domain:** `smart_shading`
- **Canonical dashboard resource:** `/smart_shading/shading.js`

The dashboard resource URL is stable and contains no version query. Future integration upgrades replace the JavaScript behind the same URL; the Home Assistant resource entry does not need to be edited again.

## Installation

### HACS custom repository

1. Add this repository to HACS as an **Integration**.
2. Install **Smart Shading**.
3. Restart Home Assistant.
4. Add the integration under **Settings → Devices & services → Add integration**.
5. Register this dashboard resource once if it is not already present:

```text
/smart_shading/shading.js
```

Resource type: **JavaScript module**.

Older installations using `/smart_shading/smart-shading-card.js?v=...` remain compatible through a small legacy loader. They should be migrated once to the canonical URL above.

### Manual installation

Copy this directory into Home Assistant:

```text
custom_components/smart_shading
```

Restart Home Assistant and register the same stable dashboard resource once.

## Dashboard card

```yaml
type: custom:smart-shading-card
entity: sensor.YOUR_ROOM_STATUS
advanced_mode: true
```

## Updating

1. Update Smart Shading through HACS or replace `custom_components/smart_shading`.
2. Restart Home Assistant.
3. Reload the browser or Home Assistant companion app if the previous card code is still in memory.

Do not change the resource URL and do not append a version query.

## Version and change management

The repository uses the following sources of truth:

- `custom_components/smart_shading/manifest.json`: integration/release version
- `CHANGELOG.md → Unreleased`: user-visible changes currently under development
- versioned sections in `CHANGELOG.md`: published release history
- pull request description: implementation details and validation

A pull request that changes production or release behavior must update `CHANGELOG.md`. CI enforces this rule. Documentation changes are selected deliberately because GitHub cannot infer the meaning of a logic or UI change automatically.

## Beta and stable release channels

Smart Shading uses two release channels:

- **Beta:** built only from `develop`, with versions such as `4.6.0-beta.2`, and published as a GitHub prerelease.
- **Stable:** built only from `main`, with versions such as `4.6.0` or the future `1.0.0`, and published as the latest stable GitHub release.

Releases use two deliberate maintainer gates:

1. Open **GitHub → Actions → Prepare Release → Run workflow** on the default branch. Select the channel and enter the requested version without a leading `v`. The workflow validates and tests the tested `develop` state, updates the manifest, moves `Unreleased` into a dated version section, creates a dedicated draft pull request, and dispatches the normal validation workflow for its release commit. It never merges or publishes.
2. Review and merge that pull request deliberately. Beta preparation targets `develop`. Stable preparation starts from the current `main`, integrates the tested `develop` state locally, and then opens the promotion pull request to `main`. Unexpected merge conflicts abort before any release branch is pushed. Stable preparation can assemble the beta sections since the previous stable release into an editable release draft.
3. Open **GitHub → Actions → Release → Run workflow** on the merged target branch. Select the same channel and type the exact manifest version as confirmation. Only this separate workflow creates the immutable tag, installation ZIP, and GitHub release.

The GitHub release body is extracted exactly from the matching dated `CHANGELOG.md` section. It is never generated independently. The workflows reject invalid channel or version combinations, duplicate tags, missing release sections, and failed tests.

For automatic draft pull-request creation, repository administrators must enable **Settings → Actions → General → Workflow permissions → Allow GitHub Actions to create and approve pull requests**. Only pull-request creation is automated; approval and merging remain manual.

The repository remains outside the official HACS catalog during private testing. It must nevertheless be publicly readable because HACS cannot download private GitHub repositories. Add it once as a HACS custom integration repository. Test installations may opt into GitHub prereleases; stable installations use normal releases. `hide_default_branch` prevents accidental installation of an unversioned development snapshot.

HACS downloads the source belonging to the selected GitHub release tag. The attached ZIP is retained for manual recovery and inspection.

## Repository layout

```text
custom_components/smart_shading/   Integration and frontend
tests/                             Regression and runtime tests
docs/                              Development and repository notes
scripts/build_release.py           Package and metadata validation
scripts/check_pr_changelog.py      PR documentation policy
scripts/release_changelog.py       Release preparation and note extraction
.github/workflows/validate.yml     Continuous validation
.github/workflows/prepare-release.yml  Reviewable release preparation
.github/workflows/release.yml      Manual beta/stable release automation
```

German documentation is available in [README_DE.md](README_DE.md). Development rules are documented in [CONTRIBUTING.md](CONTRIBUTING.md).
