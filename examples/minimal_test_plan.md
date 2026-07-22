# Minimal pilot test

## Preparation

1. Confirm that `sun.sun` is available and the Home Assistant location and time
   zone are correct.
2. Back up Home Assistant and disable competing automations for the pilot
   covers.
3. Start with one room and one or two covers.

## Easy Mode

1. Create an Easy Mode entry with a room, facade direction, cover type, and
   covers. Leave all optional refinements empty for the first test.
2. Add the generated room card from the room-creation notification.
3. Confirm that the card shows the compact Easy layout without Pause, Night, or
   detailed controls.
4. During valid sun geometry, run an evaluation and verify the configured solar
   target. Outside the sector, verify the open target.
5. Enable the room Manual Override. Confirm that automation remains disabled
   until the override is explicitly turned off.
6. For each sector, select exactly one source: geometry, a lux sensor, or an
   external binary sun confirmation. Add further sectors through the sector
   list. Confirm that selecting Lux creates a Sun Presence binary sensor and
   that an external source never falls back to Lux. Add an outdoor-temperature
   sensor only after the geometry-only baseline works; its minimum condition
   must then appear without a separate enable switch.

## Advanced Mode

1. Use a separate pilot config entry for Advanced. The setup variant is fixed
   and cannot be switched later. Optional entity fields must remain empty when
   the installation does not use them.
2. Enable and test one Advanced feature at a time: schedule, Safety, Pause, Heat
   Protection, Night Mode, or external-movement detection.
3. When testing external movement detection, verify both directions: Smart
   Shading's own command must not pause the cover, while confirmed external
   numeric feedback must pause the configured cover or shared Manual group.
4. Verify that Safety remains authoritative over ordinary pauses and that Night
   ends directly in solar shading when its sector is already active.
5. Export room diagnostics after the pilot movements, then add further rooms
   only when the result is stable.
