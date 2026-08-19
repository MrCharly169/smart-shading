# Home Assistant Ecosystem Policy

Policy-ID: meyershaff-ha-ecosystem
Policy-Version: 1.1.0
Adopted: 2026-08-19

## Scope and automatic classification

This policy applies automatically to:

- every repository containing `custom_components/*/manifest.json`;
- every HACS-distributed integration owned for this Home Assistant ecosystem;
- every local custom integration;
- every script or service that reads or changes Home Assistant through REST,
  WebSocket, SSH, storage dashboards, automations, helpers, or frontend assets.

A change is **ecosystem-wide** when it changes a convention, entity contract,
dashboard behavior, release rule, or frontend pattern that can apply to more
than one registered integration. Such a change must be recorded here and in
every affected project mirror before it is considered complete.

## Native-first Home Assistant contract

Use Home Assistant's native entities, cards, badges, actions, editors, and
Visibility conditions whenever they can express the required behavior.

- Status exposed to dashboards must be a native entity. Finite lifecycles use
  `SensorDeviceClass.ENUM` and publish the complete `options` list.
- State-dependent native fallback symbols belong to the backend entity `icon`
  property. A Custom Badge may combine an integration logo, state marker,
  animation, and semantic color when that presentation cannot be expressed by
  the Entity Badge.
- Dashboard visibility belongs exclusively to Home Assistant's native
  Visibility conditions. A custom frontend must not implement a parallel
  state selector, visibility list, state override, or hidden-display mode.
- Badge navigation and actions belong to Home Assistant's native Interactions
  configuration. A Custom Badge must preserve `tap_action`, `hold_action`,
  `double_tap_action`, and `visibility` values it does not edit, and delegate
  configured actions through Home Assistant's `hass-action` contract. It must
  not expose a separate navigation-path field.
- A Custom Badge editor may expose only its native entity selector and
  presentation-specific fields. Entity selection uses Home Assistant selectors;
  action and Visibility editing remain in Home Assistant's surrounding tabs.
- A custom card or badge is allowed only for presentation or behavior that
  cannot be expressed natively. The documented native limitation and
  compatibility fallback must be explicit.
- Ecosystem migrations must update live dashboards, onboarding snippets,
  examples, E2E fixtures, tests, and release documentation together.

## Beta release trains

Versions use `YYYY.M.PATCHbN` for beta and `YYYY.M.PATCH` for stable.

- `PATCH` identifies one coherent customer outcome or problem bundle.
- A new bundle increments `PATCH` and starts at `b0`.
- Only corrections to the same bundle increment `N`.
- Beta candidates are bounded to `b0` through `b9`; `b10` is invalid.
- A completed train is promoted to `YYYY.M.PATCH`, or the next distinct scope
  starts at the next patch with `b0`.
- A new calendar month starts at patch `.0b0`.

## System-wide change protocol

For every ecosystem-wide change:

1. Update this policy and increment `Policy-Version` when the contract changes.
2. Update `policies/ha-projects.json` when scope changes.
3. Synchronize the exact policy mirror and policy version into every affected
   project, including local integrations.
4. Add or update project tests so removal of the contract fails CI.
5. Update project changelogs and customer documentation where behavior changes.
6. For HACS projects, publish and install the appropriate reviewed release.
7. For live HA changes, create a backup, dry-run where possible, apply, restart
   when required, and verify state, icon, options, logs, and idempotence.
8. Run `node scripts/audit-ha-ecosystem-policy.mjs` before handoff.

## Persistence rule

Conversation memory, proposals, and one-off scripts are evidence, not policy.
The durable sources are this file, the project registry, project policy
mirrors, project tests, and enforced release workflows.

