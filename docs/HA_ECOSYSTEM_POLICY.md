# Home Assistant Ecosystem Policy

Policy-ID: meyershaff-ha-ecosystem
Policy-Version: 1.8.0
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

## Home Assistant language contract

All technical Home Assistant artifacts are authored in English,
regardless of the conversation language used to request or discuss the work.

- This includes entity and helper names, automation and script aliases and
  descriptions, Dashboard titles and labels, notification copy and action
  labels, source comments, logs, diagnostics, service descriptions, errors,
  setup and options flows, and default status text.
- Stable identifiers, entity IDs, translation keys and code-facing values use
  English `snake_case` or the native convention required by Home Assistant.
- Proper names and established physical area names may remain unchanged.
- Home Assistant translation files may localize user-facing strings, but their
  source keys and complete English default remain authoritative.
- The living customer documentation remains multilingual where its own
  contract requires Luxembourgish, German, French and English.

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

## Notification navigation contract

Mobile notification navigation and Dashboard return navigation are separate
native Home Assistant concerns.

- A Mobile App notification uses one identical destination in `url`, Android
  `clickAction`, and every matching `URI` action. An internal Home Assistant
  destination is a relative Home Assistant path; an external web destination
  is the same explicit `https://` URL in all three fields. Internal persistent
  notifications use an equivalent Markdown link when navigation is useful.
  Notification clear calls never receive navigation fields.
- `navigation_path` belongs to a Badge or Card interaction. `back_path` belongs
  only to the destination Lovelace Subview. A Badge, custom Card, notification
  payload, or logical notification route must not invent a second Back-path
  field or override the native Subview contract.
- Every notification or Badge destination that is a Lovelace Subview must have
  an explicit, valid `back_path`. The return target must be a non-Subview or a
  deliberately selected parent view that the intended user can access.
- A reusable integration must not hard-code an installation-specific Dashboard.
  When it emits navigable notifications, its setup and options flow exposes the
  notification destination and, when different, the intended return path. One
  configured parent view may serve as both the notification destination and the
  native return target of a separate detail Subview. Onboarding and examples
  show that the return path is saved on the destination Subview. If the
  integration does not own that Dashboard, it must not claim to have changed it.
- Because native `back_path` is static per Subview, recipients that need
  different return destinations use distinct Subview paths. Per-recipient route
  metadata, query-string patches, browser-history assumptions, and global
  frontend interception are not substitutes for this native model.
- Notification audits cover UI-managed automations and scripts, Alarmo or
  comparable stores, integration-generated notifications, and known YAML-only
  sources. Inaccessible or dynamically templated sources remain explicit audit
  findings rather than being reported as verified.

## Notification presentation contract

Every presented MeyersHaff notification uses one stable semantic category so
the same event is recognizable before its text is read.

- The title starts with exactly one category-specific emoji. This is the
  cross-platform identifier and remains visible on Apple platforms where a
  standard notification cannot replace the Home Assistant application icon.
- Mobile App payloads set a category-specific Material Design Icon in Android
  `notification_icon` and a restrained semantic `color`. A source may override
  either value deliberately; an image attachment may replace Android's visible
  large icon according to the Companion App's native behavior.
- Reusable sources pass an explicit stable category to a compatible central
  router or apply the category style themselves. The central MeyersHaff router
  may infer a category from legacy content only as a compatibility fallback;
  unknown content receives the neutral bell style.
- Semantic categories describe the real source or event, for example chicken
  coop, vacuum, door station, security, access, plant light, activity, task,
  clock, shading, irrigation or system. Titles do not use arbitrary decorative
  emoji or a product logo unrelated to that category.
- `clear_notification`, Companion App command messages and other invisible
  background pushes are never given a display title, icon or color. Existing
  tags, actions, priority, sound, attachment and navigation fields are
  preserved when presentation styling is applied.
- The notification inventory reports both source-level styling and the
  effective style supplied by the central router. Tests cover the semantic
  mapping, Apple title fallback, Android icon/color, explicit overrides,
  command bypass and idempotence.

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

## Durable progress and release handoff

Approved work is complete only when it can be reproduced from durable sources.

- Live configuration, working-tree edits, chat notes and one-off artifacts are
  not substitutes for canonical project files and regression tests. Every
  approved product change must be present there before a release is prepared.
- Installation-specific live changes must also be represented in the owning
  Home Assistant workspace's apply, update or cleanup scripts and tests so a
  later integration release or Dashboard rebuild preserves them.
- Before any beta or stable preparation, push, publication or installation,
  audit the canonical working tree and the selected source commit. The release
  process must stop when an approved change would be absent from the selected
  source commit, fresh release workspace or generated artifact.
- Never discard, stash, overwrite or silently exclude pending user work to make
  a release gate pass. Incorporate it, record an explicitly approved deferral
  in a durable source, or stop and request direction.
- Authorization to edit or test does not by itself authorize a push,
  publication or installation. Where project instructions require it, obtain
  explicit user authorization before those external actions.
- After publication and installation, verify that the exact installed version
  contains the approved change and that its related live configuration remains
  present and idempotent.

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
