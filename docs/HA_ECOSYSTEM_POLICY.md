# Home Assistant Ecosystem Policy

Policy-ID: meyershaff-ha-ecosystem
Policy-Version: 1.4.0
Adopted: 2026-08-20

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
- Future scheduled or announced occurrences remain planning context, never an
  active waiting presentation. Compact schedule labels use the local time only
  for today, then tomorrow, a weekday or a date; when that label occupies the
  Badge, secondary state markers must be hidden or positioned without overlap.
- A custom card or badge is allowed only for presentation or behavior that
  cannot be expressed natively. The documented native limitation and
  compatibility fallback must be explicit.
- Ecosystem migrations must update live dashboards, onboarding snippets,
  examples, E2E fixtures, tests, and release documentation together.

## Living customer documentation contract

Customer-facing Home Assistant documentation is one versioned capability
catalog, not copied prose per residence. Residence profiles contain only the
active/available mapping, dashboard destination, and verified local context.

- Every customer capability is documented in Luxembourgish, German, French,
  and English. A capability or customer-visible change is incomplete while one
  required language is missing.
- The customer baseline remains stable. New behavior extends the matching
  capability and adds a plain-language changelog entry instead of silently
  rewriting unrelated guidance.
- Active capabilities are derived from current dashboards, referenced entities,
  automations, scripts, and integration manifests. Ambiguous findings require
  review and must never be presented as verified behavior.
- Owned open-source integrations link to their manifest documentation URL,
  GitHub source, and detected installed version. Customer text remains
  non-technical; deeper technical material is optional.
- Scheduled maintenance is read-only toward Home Assistant except for the
  dedicated documentation presentation. It must not switch entities, execute
  customer automations, or change integration configuration.
- Generated HTML, Markdown, database, manifest, and changelog outputs are
  published together. Nextcloud is a synchronized publication target; the
  versioned workspace catalog remains the source of truth.
- Documentation outputs contain no Home Assistant tokens, Nextcloud
  credentials, internal secrets, personal notification targets, or raw private
  automation payloads.
- Customer-facing private, MeyersHaff and explicitly shared web services use a
  single multilingual service catalog alongside the capability catalog.
  Smart Solutions workloads, administration interfaces and infrastructure-only
  routes are excluded unless a later approved customer contract says otherwise.
- Every published service includes only its public reverse-proxy address,
  generic username pattern, safe password handling, mobile access and privacy
  boundary. Never publish an actual username, password, internal IP address,
  Proxmox guest name, token or management route.
- Service presence and availability are evidenced by a certificate-pinned,
  read-only Proxmox inventory and a public endpoint check. Official upstream
  repositories and releases are monitored; a customer-visible behavioral
  change requires a reviewed four-language changelog entry.
- An account must not be described as active without residence-specific
  evidence. Unverified account-based services remain available or explicitly
  approval-required until their customer mapping is confirmed.

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
