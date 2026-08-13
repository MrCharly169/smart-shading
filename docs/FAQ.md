# Frequently Asked Questions

## Why is normal shading waiting?

Read the reason shown by the room Card or status sensor first. Normal shading
waits when the sun is outside the configured sector, the daytime schedule is
inactive, a selected temperature condition is not satisfied, or the sector's
authoritative Lux/external source is unavailable or invalid. Smart Shading
does not silently substitute another source.

## Do I need a Lux or outdoor-temperature sensor?

No. A sector can use Home Assistant's `sun.sun` geometry as its one source.
Lux and external on/off confirmation are alternatives. Without a selected
outdoor-temperature sensor, outdoor temperature is ignored entirely.

## Can an existing entry switch between Easy and Advanced Mode?

No. The setup variant is fixed for the config entry so settings from one
contract cannot become hidden in the other. Create a separate Smart Shading
entry to use the other variant.

## Why does the Card say “Custom element doesn't exist”?

Confirm that `/smart_shading/shading.js` is registered under Home Assistant
dashboard resources as a JavaScript module. Restart Home Assistant after
installing or updating, then reload the browser or companion app. Do not add a
version query to the resource URL.

## Does Smart Shading send data to a cloud service?

The Smart Shading integration reads Home Assistant entities, calculates its
decisions, stores runtime data, and calls cover services inside Home Assistant.
It has no third-party runtime requirement, cloud client, or telemetry endpoint.
Home Assistant, HACS, and the integrations that provide the selected entities
may have their own network behavior.

## Why does Home Assistant show a KNX cover moving although the motor is idle?

### Symptoms

- Home Assistant periodically shows `opening` or `closing` although the motor does not move.
- The displayed position may run virtually to 0% or 100%.
- Automatic pause detection may otherwise mistake the update for external operation.
- The event often follows a KNX state-updater expiry interval, a reconnect, or a Home Assistant reload.

### Cause

Home Assistant's KNX state updater reads configured state addresses. If an UP/DOWN **command** group address is readable, some actuators answer the `GroupValueRead` with their last stored command value. That value means "the last command was up/down"; it is not proof that the motor is currently moving.

XKNX may interpret that response as a movement command and calculate a temporary position from the configured travel time. The Home Assistant cover can consequently appear to move even though the physical cover remains stationary.

### Diagnosis

1. Open the KNX Group Monitor.
2. Look for a Home Assistant `GroupValueRead` to the affected cover's UP/DOWN command group address.
3. Check whether the actuator immediately answers with a `GroupValueResponse` containing its last stored `up` or `down` value.
4. Verify that the cover uses separate group addresses for:
   - UP/DOWN command
   - Step/Stop command
   - absolute position command
   - tilt command
   - position feedback
   - tilt feedback
5. Compare the event with the Home Assistant entity history and Smart Shading diagnostics.

### Safe mitigation for a Theben JM 8 T

The global KNX state updater may remain enabled. Test the following change on one cover first:

1. In ETS, open the actuator's UP/DOWN command communication object.
2. Disable only its **Read (`R`)** flag.
3. Keep **Communication (`C`)** and **Write (`W`)** enabled.
4. Keep the Read and Transmit flags required by the real position and tilt feedback objects.
5. Download the updated application to the actuator.
6. Trigger a read with Home Assistant and inspect the Group Monitor.
7. Confirm that the UP/DOWN command address no longer answers the read request.
8. Confirm that KNX pushbuttons, Home Assistant commands, position feedback, and tilt feedback still work.

Repeat the change for other command objects only when the Group Monitor proves that they are also being read and return a misleading command value.

The Theben default Read flag is not inherently invalid. It exposes the last command-object value, but that value is not a physical movement status. Remove the flag only when no other controller intentionally depends on reading that command object.

Do not disable the global KNX state updater as the only workaround. Other KNX entities may require it to restore valid state after a restart or reconnect.

### How Smart Shading handles these events

- `opening`, `closing`, `open`, and `closed` are informational and never prove external movement.
- Automatic pause detection uses numeric `current_position` and `current_cover_tilt_position` feedback where available.
- One numeric change starts a candidate but never pauses the cover immediately.
- Smart Shading confirms the candidate when its numeric value remains unchanged for five seconds. This also supports actuators that publish only their final position or tilt value.
- External movement uses the actuator's one-percent numeric feedback resolution rather than the larger command tolerance configured for automatic target suppression. Short wall-switch movements can therefore still pause automation.
- Every additional numeric change restarts the stability timer.
- A value returning to the accepted baseline rejects the candidate.
- Smart Shading, window-policy, and safety-owned command sessions cannot create a manual pause.
- Covers without usable numeric feedback use the configured Manual Override entity only.

Home Assistant does not expose whether every numeric value came directly from a physical protocol feedback object. Smart Shading therefore reports the available evidence and its decision reason in the diagnostics without claiming protocol-level certainty.

## Can several covers share one Manual Override entity?

Yes. When every relevant cover in the same room uses the exact same switch or
input boolean, Smart Shading treats them as one manual group. Turning the entity
on pauses every member; turning it off releases every member and evaluates the
room once. A confirmed external movement of any member also activates the
complete group. Entities are never grouped across different entity IDs, and a
room-level pause writes each unique Manual Override entity only once.
