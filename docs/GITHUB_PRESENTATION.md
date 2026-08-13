# GitHub repository presentation

These values are proposed for the repository settings. Applying them is a manual maintainer action; documentation changes do not modify repository metadata.

## About

**Description**

> Context-aware sun and heat control for Home Assistant covers, with Easy and Advanced modes.

Keep the website field empty unless a maintained project page is added later. The repository README remains the canonical documentation.

## Topics

Recommended topics:

```text
home-assistant
home-assistant-custom-component
hacs
cover-automation
smart-home
sun-tracking
solar-shading
blinds
shutters
energy-comfort
```

## Social preview

Upload [`docs/images/social-preview.jpg`](images/social-preview.jpg) under **Settings → General → Social preview**. The raster is exactly 1280 × 640 pixels. [`docs/images/social-preview-source.svg`](images/social-preview-source.svg) is the editable source.

## Funding

No verified Buy Me a Coffee or GitHub Sponsors URL is stored in the repository. Do not add a funding badge or `.github/FUNDING.yml` until the maintainer supplies the exact destination. Funding is voluntary support for development, tests, documentation, and maintenance; it is not a license fee.

## Recommended manual settings

- Keep the repository public so HACS can resolve and download published tags.
- Set `develop` as the default branch only if that remains the intended beta-first contribution flow; otherwise update badge and workflow assumptions together.
- Enable **Issues** and retain the structured Bug Report and Feature Request forms.
- Enable **Private vulnerability reporting** so `SECURITY.md` can route sensitive reports safely.
- Under **Actions → General → Workflow permissions**, allow GitHub Actions to create and approve pull requests; the release preparation workflow needs this to open a draft PR. Maintainer review and merge remain manual.
- Protect `main` and `develop`: require pull requests and the relevant validation/E2E checks; do not allow release tags to be rewritten.
- Keep Releases enabled. Beta builds from `develop` are prereleases; stable builds from `main` are marked latest by the release workflow.
- Add the exact funding link to the repository sidebar and `.github/FUNDING.yml` only after it is verified.
