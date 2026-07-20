# Supported baseline

This document records compatibility and behavior that every future change must
preserve. It deliberately does not duplicate the active release version. The
manifest and changelog remain the version sources of truth.

## Compatibility contract

- Home Assistant 2026.6 or newer
- Integration domain `smart_shading`
- Current config-entry schema as declared by `SmartShadingConfigFlow.VERSION`,
  including migration of older entries during setup
- Permanent dashboard resource `/smart_shading/shading.js`
- Legacy `smart-shading-card.js` loader retained only for existing dashboards

## Behavior contract

- Easy Mode always has a sensorless sun-geometry baseline, one indefinite room
  Manual Override, and only optional confirmation or temperature refinements.
- Advanced Mode retains schedules, Safety, Pause, Heat Protection, Night Mode,
  per-cover Manual Override entities, and optional movement detection.
- Cover height follows Home Assistant semantics. Venetian slat position follows
  the documented KNX scale: `0%` open and `100%` closed.
- Existing settings survive upgrades and mode switches unless a documented
  migration intentionally transforms them.

The executable baseline is maintained by the tests listed in
[REGRESSION_MATRIX.md](REGRESSION_MATRIX.md).
