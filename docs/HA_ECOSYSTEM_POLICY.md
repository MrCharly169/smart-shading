# Home Assistant Ecosystem Policy

Policy-ID: meyershaff-ha-ecosystem
Policy-Version: 1.25.0
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

Technical source artifacts remain English, regardless of the conversation language.
Customer-visible presentation follows a separately verified language contract.

- The active Home Assistant app/frontend user language is the customer-visible
  language source, independently on each phone, tablet and browser. The
  installation/system language must never override that selection. English and
  regional English tags select English; German and unsupported or absent app
  languages select German. Explicit card overrides remain opt-in only.
- Shared stored dashboard text cannot represent concurrent user languages.
  Do not rewrite shared dashboards or notification sources periodically according
  to one global language. Stored text and per-recipient notifications require
  separate localized rendering/delivery before claiming complete app parity.
- Owned shared dashboards retain the native visual dashboard editor. Store
  canonical views without a dashboard-level strategy, with authenticated
  `meyershaff_localization` metadata for reviewed English/German presentation.
  A strategy is not an acceptable localization mechanism when it disables the
  native editor. Maintenance rebuilds must preserve this editor contract.
- Home Assistant has no supported hook for translating arbitrary native labels
  while retaining its full editor. The owned-dashboard presentation adapter is
  a narrow compatibility exception: it may adapt only the Lovelace panel's
  configuration presentation for explicitly marked storage dashboards. Keep
  rawConfig, native save/undo, actions, visibility, user profiles and global DOM
  untouched. In visual and YAML editing, use the canonical original text;
  translate only the normal display according to each client's app language.
  New user labels remain intact and untranslated until their copy is reviewed.
- Test the adapter against the exact installed native frontend, including
  visual edit entry, save/rejection, both language directions, concurrent apps,
  untouched dashboards and stable config identity during state refreshes.
  Unknown HA versions fail safely to original labels with a usable editor;
  update maintenance must revalidate compatibility before accepting a release.
  Missing resources must never prevent native editing or dashboard use.
- Multiple windows in one room use evidence-backed physical labels consistently
  across room cards, security and disclosure lists. Use left/middle/right only
  with a known reference or named areas such as Vincenzo, MaxPoint and Kitchen.
  Never infer physical position from a numeric entity suffix. Unknown mappings
  require a documented finding; entity IDs and control semantics remain stable.
- Keep complete English source text and stable translation keys. Never translate
  entity IDs, action IDs, service names, state values, routes or template logic.
  Proper names and established physical area names may remain unchanged.
- Use native Home Assistant translations for integration setup, entities and
  services. Native frontend controls retain Home Assistant's user-language
  behavior. Only the scoped presentation exception above is allowed; never
  intercept native controls or silently change user profiles.
- Config and options flows must not compose customer-visible labels from the
  installation/system language. Static choices use Home Assistant translation
  keys; dynamic choices contain only unchanged user-provided proper names or
  language-neutral values. If a flow needs translated prose, redesign it as a
  native translated step instead of hard-coding one backend language.
  A pre-existing legacy flow that cannot be migrated in the current bounded
  change must carry an explicit, exact and non-increasing registry migration
  budget; the audit rejects every additional system-language reference.
- Dynamic flow summaries must use exactly the same placeholder names in every
  language, matching Home Assistant's `string.Formatter` validation. Different
  `name__en` / `name__de` placeholders are NOT supported: HA rejects the localized
  resource. Keep prose in native catalogs and placeholders language-neutral
  (names, counts, measurements, identifiers or symbols with a localized legend).
  Verify actual served EN/DE resources and translation-helper errors before
  claiming completion; a synthetic renderer alone is insufficient.
  Dynamic object navigation uses unchanged user names; actions use native
  translated selector options. Test the real submitted selector and all routes.
- Native entity names are shared registry metadata: Home Assistant generates
  them in the backend language, not separately for each app. Use native name
  translation keys without `_attr_name` overrides, preserve user overrides and
  existing entity IDs, and do not claim that registry names switch per user.
  Entity states, selectors, flow descriptions and custom-card copy must still
  follow the viewing app. Legacy translated select values remain accepted and
  gain native state translations; never break their existing automations.
- Owned custom cards must document their language source and explicit overrides.
  Existing cards using the system language are migration findings until adapted
  and tested; translation files alone do not prove app-language parity.
- Backend states, reasons and action values remain stable machine identifiers.
  Cards and badges map every supported identifier to the active presentation
  language. An unknown identifier uses a same-language generic message and may
  expose its raw value only inside explicitly technical diagnostics; it must not
  leak English or an internal token into normal German presentation.
- Automatic reconciliation must retain stable source bindings, preserve concurrent
  edits, and verify language changes in both directions without guessing a source
  from ambiguous translated text. New text must have reviewed English and German
  catalog entries before installation; unknown text is an audit failure.
- Static dashboard copy and notification text require a reviewed shared catalog
  or native translation mechanism. Audit missing keys, placeholders, fallback,
  navigation and actions. A repair or rebuild must preserve reviewed translations.
- New or changed customer-visible features include English and German together.
  Audit all three public integrations and local sources before claiming complete
  coverage. Migrate existing surfaces in measured, explicitly named batches;
  distinguish generated previews, installed changes and device-tested behavior.
- Every registered HACS or local integration ships `translations/en.json` and
  `translations/de.json` with identical leaf keys and placeholder sets. The
  placeholder names must match exactly; language-suffixed copy is rejected.
  The ecosystem audit blocks missing files, missing or extra keys, empty German
  values and placeholder drift before release or installation.
- The living customer documentation retains its separate five-language and
  explicit/browser/profile language selection contract. Do not regress it while
  changing the installation-language presentation of Home Assistant.

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
- Custom Cards, Badges, and their editors preserve the user's active interaction
  state across Home Assistant refreshes. Open selectors and disclosure dialogs,
  keyboard focus, long-list scroll offsets, and the surrounding Dashboard scroll
  position must not reset on relevant or unrelated state updates. Editors keep
  their native form element stable; disclosure lists either keep stable DOM or
  explicitly restore their keyed focus and exact scroll offsets after a rebuild.
  Runtime tests cover repeated refreshes while these controls are open.
- Future scheduled or announced occurrences remain planning context, never an
  active waiting presentation. Compact schedule labels use the local time only
  for today, then tomorrow, a weekday or a date; when that label occupies the
  Badge, secondary state markers must be hidden or positioned without overlap.
- A custom card or badge is allowed only for presentation or behavior that
  cannot be expressed natively. The documented native limitation and
  compatibility fallback must be explicit.
- Ecosystem migrations must update live dashboards, onboarding snippets,
  examples, E2E fixtures, tests, and release documentation together.

## Native-first maintenance and upstream compatibility

Operator refinement, 2026-09-28: Smart Solutions is an additive Home Assistant
product, not a core/frontend fork or a replacement administration platform.

- Prefer native configuration and options dialogs, entities, devices, areas,
  services/actions, dashboards, selectors, authentication and supported Assist
  extension points. A consistent product entry can launch a native workflow;
  branding alone does not justify rebuilding that workflow.
- Documented extension points first. Reusing an internal HA web component or
  frontend endpoint does not make it a stable public extension API. Record such
  dependencies explicitly; no core patches, monkey-patching, private storage
  writes or global DOM interception as a new product foundation. Existing narrow
  policy exceptions are not permission to spread them to the product shell.
- Keep custom code bounded to demonstrated product gaps. Each exception records
  the native option evaluated, concrete missing capability, smallest extension,
  affected consumers, owner, fallback, tested HA Core/frontend versions and a
  review/removal condition. Prefer replacing it when upstream fills the gap.
- Review current official HA documentation, release notes, deprecations and
  breaking changes before implementation and each affected upgrade. Current
  supported APIs are the target; neither automatic latest-version deployment nor
  indefinite version pinning substitutes for compatibility maintenance.
- Before accepting an HA upgrade, test the candidate Core/frontend combination
  locally: fresh setup, existing configuration migration, editing/save, actions,
  reload/restart, languages, refresh stability and relevant Assist behavior.
  Record exact versions and results. Keep native management usable when optional
  presentation fails; define and verify recovery without assuming config downgrade
  is safe. One passing version cannot guarantee compatibility with future updates.
- Future assistants reuse native Assist/conversation/intents/exposure where
  suitable, plus explicitly documented missing capabilities. Do not build a
  parallel user, permission, device registry or AI-only command engine.
- Existing prototypes are assessed honestly: native-backed custom setup wrappers
  remain compatibility work until justified or replaced by native dialogs.
  Policy adoption does not itself establish runtime compliance.

## Optional Smart Solutions product contract

The Smart Solutions product layer is additive. Standalone integrations retain
native setup, entity identities, actions and their existing independent use.
Adoption is explicit and versioned; an unadapted module is not falsely reported
as standardized. The first presentation adapters cover Smart Shading and Clock.

- Installed, configured, disabled, running and failed are separate catalog facts.
  A stored state, version string or visible card alone does not prove a running
  integration or accepted device behavior. Mixed instance failures remain visible.
- Shared compact presentation has one implementation. Disclosure never actuates
  equipment. Keep current faults, active operation and manual overrides readable
  when collapsed. Future schedules remain planning context. Unknown state values
  use localized fallback; technical exception text belongs in diagnostics.
- Discovery uses stable versioned capabilities and native metadata, not entity
  naming conventions or customer-specific IDs. Unsupported contracts fail visibly.
  Native configuration, Interactions and Visibility remain authoritative.
- Details are loaded on demand, preserve stable keyed DOM, focus and scroll, and
  retain a native management route when a module card cannot load. Domain behavior
  remains in its owning integration; presentation reuse does not merge lifecycles.
- Product bundles contain reviewed executable source and exact per-file hashes,
  never household configuration, sessions, credentials or customer identities.
  Installation, activation and updates are separate, reviewable operations.
  Source version parity is not customer installation or live admission.
- Test common behavior against every adopted adapter. A source snapshot lab is
  regression evidence; a fresh installation, migration, rollback and appropriate
  physical tests are separate customer release gates. No universal compatibility
  claim from a single Home Assistant version or a successful screenshot run.

## Smart Solutions identity, experience levels and drift prevention

Adopted product direction, 2026-09-28. Applies to new or changed Smart Solutions
product surfaces; it does not claim legacy integrations have already migrated.
Smart Shading is the interaction reference. Exact layout, colors and screen
compositions remain reviewable prototypes until visually accepted.

- One recognizable Smart Solutions identity and interaction vocabulary spans
  adopted modules: consistent navigation, control placement, save/cancel,
  setup/reconfiguration, manual intervention and error recovery. Reusing a shell
  around incompatible menus does not establish product conformity.
- Simple mode is the default: automation-led daily use with concise outcomes,
  meaningful normal controls and actionable problems, without raw telemetry.
  Advanced mode is opt-in: additional reasons, measurements, history and expert
  preferences inside the same product structure. These are presentation levels,
  not separate product forks, duplicated domain engines or permission grants.
- Changing presentation level preserves automation configuration and behavior.
  Advanced mode is not installer authorization. Privileged settings/actions need
  effective backend permission checks; hidden UI is not a security boundary.
  Neither mode hides safety-critical faults, manual overrides or required action.
- Badges are optional and user-selected. Their availability, semantic states,
  navigation and editing follow the existing native badge contract. Disabling
  badges affects presentation only and never disables a function or its safety
  indications in the main overview. Badge display is distinct from batch execution.
- Users add functions through a consistent setup entry, assign equipment and
  choose their presentation. Enabled functions populate the configured aggregate
  overview; do not silently append individual cards or rewrite user dashboards.
  Standalone cards remain optional and preserve native dashboard editing.
- Shared visual and interaction behavior has one canonical implementation with
  versioned compatibility. Adopted modules consume it rather than copying CSS,
  menus or badge state mapping. Functional differences stay in the owning module.
  Optional consumers retain documented behavior when a shared service is absent.
- Every new module or changed product surface includes a conformity record:
  reference design, shared component version, Simple/Advanced applicability,
  badges enabled/disabled, native editor/actions, setup/cancel/reconfigure,
  manual/error/offline states, language and small/large viewport evidence.
  Mark pending evidence explicitly; do not label untested legacy code conformant.
- A change to shared behavior must test every adopted consumer. Mechanical audits
  enforce policy parity and required contracts; rendered interaction tests and
  human design review establish UX conformity. Text-presence checks alone cannot
  prove a consistent experience or guarantee the absence of AI drift.
- Record intentional departures and rationale in the canonical product decision
  record before implementation. A temporary exception names its owner, affected
  modules, limits and review/removal condition. Do not invent a new per-module
  design or silently redefine the reference to make a failing check pass.

## Smart Solutions equipment strategy and replaceable adapters

Adopted architectural direction, 2026-09-28. This is a design requirement, not
proof of outage resilience or hardware compatibility in existing installations.

- KNX is the preferred building-automation foundation. Define per installation
  which basic functions remain available without Home Assistant, its host,
  internet or optional providers. Keep required basic operation and protective
  interlocks in the appropriate KNX/device/controller layer. Home Assistant adds
  comfort, optimization and cross-system orchestration; it must not silently
  become the only path for a required basic function. Test actual failure modes.
- Select supported equipment by exact model, firmware, transport and proven
  capability, not brand name alone. Maintain a reviewed equipment support matrix
  with preferred/validated, limited/compatible, experimental and retiring states,
  evidence dates, dependencies, known limits and maintenance ownership. Price
  alone neither qualifies nor disqualifies a component. Installed is not validated.
- Additional affordable or third-party equipment remains possible through native
  supported integrations and explicit capability mapping. Do not imply equal
  service guarantees for unvalidated combinations. Unknown heating brands or
  device models remain unselected until actually chosen and tested.
- Separate presentation, domain behavior and equipment adapters. Modules target
  capabilities such as cover position/stop, temperature/setpoint or confirmed
  on/off, not vendor-specific entities hard-coded into common cards or algorithms.
  Reuse native Home Assistant integrations/entities first. Add a small adapter only
  for a demonstrated semantic/protocol gap; do not invent a second device bus,
  registry or general driver framework when native facilities suffice.
- Version capability contracts and describe required/optional features, units,
  ranges, command semantics, feedback, availability and failure behavior. Missing
  capabilities remain explicit; never fabricate position, acknowledgement or
  success. Optional vendor features fit the common presentation and degrade
  clearly; they do not create a different menu architecture for each brand.
- Equipment replacement requires an explicit migration mapping: old/new device,
  supported capabilities, identifiers, units/direction, settings and affected
  automations. Preserve logical room/function identity and user preferences where
  compatible; do not promise unchanged HA device/entity identity without testing.
  Verify command ownership, no duplicate control, manual operation, feedback,
  interlocks, restart/offline behavior and rollback before retiring the old path.
- A new brand or protocol is evaluated through the same adapter acceptance and
  support matrix. Record incompatibilities and lifecycle changes; do not silently
  weaken the baseline, broaden credentials or rewrite the user experience. A
  changed capability contract requires impact review across all affected modules.
- The conformity record includes equipment support tier, tested versions,
  basic-operation fallback and replacement evidence when applicable. Simulated
  UI/adapters do not establish physical operation, protective behavior or actual
  KNX/controller independence. Existing gaps remain visible until tested.

## Smart Solutions local-only operation and extensible energy scope

Adopted product boundary, 2026-09-28. This supersedes earlier proposals allowing
cloud-dependent product providers. It does not authorize disabling or deleting
existing customer integrations, accounts or data.

- Local-only is mandatory for the Smart Solutions package. Reject mandatory
  vendor-cloud accounts, activation, authentication, token renewal, licensing
  checks, remote computation, telemetry and cloud relay dependencies for setup,
  normal operation, restart, reconfiguration and recovery. A local UI over a cloud
  API is not local operation. Optional cloud features are excluded from the package,
  not offered as an equivalent supported mode. Price or brand does not override
  this boundary. Prefer documented, supported local protocols and controllers.
- Review the entire dependency chain, including gateways, bridges, speech/AI,
  notifications, remote access and device commissioning. Native HA compatibility
  or a local transport label does not establish cloud independence. Unknown
  dependencies remain unverified and block local-only acceptance. User data and
  diagnostics remain locally controlled; no automatic external reporting.
- Separate software acquisition from operational dependence. Reviewed artifacts
  may be acquired from an approved source and transferred for offline installation
  and update; never require continuous internet or automatic cloud fallback.
  Document a local recovery path including required executable dependencies.
  Existing publication approval boundaries remain unchanged.
- Prove the applicable workflows with WAN/vendor-cloud access absent: fresh setup,
  normal control, feedback, restart, reauthentication where relevant, recovery and
  loss of optional inputs. Observe actual dependencies and expiry behavior; a
  short successful offline test does not prove indefinite independence. No live
  network/security changes are implied by this test requirement.
- Reclassify existing cloud-dependent candidates as excluded or replacement-needed
  in the product portfolio; preserve current installations until a separately
  scoped migration. Previously observed or preferred equipment is not exempt.
  Third-party remote weather/tariff/notification services cannot become hidden
  prerequisites; specify local inputs or an explicit unavailable capability.
- Energy management and heating are first-class future product domains alongside
  building automation. Model metering, generation, storage, charging, controllable
  loads and heating/cooling capabilities independently of selected vendors or
  transports. KNX is a preferred foundation, not the exclusive device protocol.
- Separate energy observation from optimization and equipment control. Define
  authoritative controller, units, measurement freshness, limits, priorities,
  manual override and degraded operation. Native heating/electrical protection
  remains with its responsible controller; conflicting module command paths must
  not independently control the same output. Physical acceptance is mandatory.
- New energy/heating or other modules use the same versioned capability, local-only,
  UI and lifecycle contracts. Unknown future modules do not justify speculative
  drivers or a second generic automation engine. Select known systems only after
  model/protocol/source review and actual local acceptance; no unsupported brand
  recommendation or claim that current meters already form a complete EMS.

## Optional assistant interface and explicit AI provider exception

Operator refinement, 2026-09-28: a separately developed AI assistant may use local
or explicitly selected cloud inference. This narrow exception supersedes blanket
cloud exclusions above only for optional AI inference, not equipment control,
commissioning or the availability of building automation.

- Automation remains operational without an assistant, its provider or internet.
  Do not add a cloud AI provider or transfer data merely because this architecture
  permits one. Provider selection, data scope, retention and credentials require
  an explicit configured authorization. No automatic local-to-cloud fallback.
- Every adopted module has a versioned assistant-facing capability description:
  scoped native status sources, supported read queries, allowed native actions,
  preconditions, feedback and failure meanings. Reuse the same domain logic and
  authorization as direct operation; no separate AI-only control engine.
- Read access, action permission and installer privileges are distinct. Exposure
  is explicit per scope/entity/action, never all household entities by default.
  Preserve user context and enforce permissions at the backend. Untrusted device
  names, sensor text and model output do not become executable instructions.
- A model-proposed action is not execution or device success. Validate target,
  permissions, current interlocks, stale data and any required confirmation before
  invocation; read back results. Log a redacted attributable action outcome.
  Monitoring does not grant autonomous remediation or unlock privileges.
- The common product UI exposes assistant connection/exposure state and a
  consistent contextual entry point. A disconnected prototype says so; no fake
  conversation, microphone capture, monitoring or device-success claims.
- Assistant development remains separate. Prototype capability metadata and
  UI tests do not prove voice recognition, provider privacy, end-to-end backend
  authorization or physical control. Record these pending tests explicitly.

## Responsive embedded view contract

- Every new or changed embedded app, iframe, full-screen card and Subview must
  fit the available visible viewport on small phones, tablets and desktops.
  Fixed device-specific minimum heights and width-based aspect ratios alone
  are not acceptable for full application navigation. Native content cards
  such as a map may retain their aspect ratio when their controls and the
  surrounding page remain reachable; document and test that distinction.
- Full-panel applications fill the visible webview from their actual top edge
  to the visualViewport bottom (innerHeight fallback), without wrapper padding,
  margins, minimum heights, secondary panel-height deductions or legacy height
  caps. The native app and embedded application own safe-area handling; do not
  reserve it again in the wrapper. Keep the native HA header and back action.
  Use a plain borderless container, no animated ha-card shell, no decorative
  transitions and no application-background sampling or DOM theme observer.
  Do not assume one phone model, orientation or constant browser toolbar height.
- Explicitly distinguish viewport-filling panels from cards in a scrolling
  dashboard. A flow card below other content must not collapse or change its
  height as the surrounding dashboard scrolls. The embedded application owns
  its content scrolling; surrounding headings and fallback links remain
  reachable with normal dashboard scrolling. Do not hide inaccessible controls
  behind overflow clipping or add nested Home Assistant dashboards.
- Recalculate on viewport, keyboard and container resize without reloading
  the iframe, losing input, focus, internal scroll or application session.
  Observe only the owned card and its composed ancestors; never modify global
  Home Assistant layout or third-party application DOM. Disconnect observers
  and event listeners when the card is removed.
- Prefer native cards where sufficient. The authenticated Ingress wrapper is
  a scoped exception because a native URL iframe cannot establish and renew
  the required Supervisor session. Preserve native back_path, editor,
  visibility, actions, app language and existing access boundaries.
- Before installation run browser regressions at small and large phone sizes,
  portrait and landscape, tablet/desktop, non-zero safe-area padding and a
  keyboard-sized visual viewport. Verify that the bottom menu can be clicked,
  a flow card remains usable after scrolling and the iframe/input survive
  resizing and HA refreshes. Test native embedded content and its fallback
  separately. Browser emulation is not physical iOS/Android acceptance;
  record any device acceptance still outstanding explicitly.
- Keep source, every owning installer/rebuilder, content-hashed resource URL,
  regression tests, documentation and existing maintenance prompts in sync.
  After installation verify exact served source and saved configuration, and
  run the read-only drift check. Updates must not restore fixed-height clipping.
  See architecture/embedded-mobile-views-2026-09-09.md in the HA workspace.

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

## Per-device notification language

- Dashboard language and delivered push language have separate sources. The
  operator can select Deutsch or English for each Mobile App target in the
  existing Notification Route Administration. Native input_select helpers named
  notify_language_<mobile_app_service> persist this choice without an initial
  value. Never reset an existing choice during installation or maintenance.
- Resolve a logical route before reading its target's language. Multiple routes
  to one device share one language; reassignment uses the new device's choice.
  Do not infer a device language from the system language, another device or
  an account-wide frontend preference. App language changes do not change this
  explicit delivery setting. Renamed/replaced notify services require a reviewed
  mapping; never transfer a choice to a guessed identity.
- Central delivery and direct notification-generating integrations preserve the
  same explicit helper choice. Clock Advanced builds both language versions and
  chooses per target, including reminders, feedback and action titles. When used
  elsewhere without these optional helpers, its existing default remains valid.
- The central compatibility renderer accepts only reviewed exact text and
  anchored template patterns, preserving variable values. Ambiguous or unknown
  text is delivered unchanged and remains a coverage finding. New source copy
  must extend the English/German catalog and its rendering tests before release.
- Translate only visible title/message/subtitle/action titles. Never change
  action identifiers, destinations, tags, attachments, critical flags or sounds.
  Invisible pushes bypass localization. Tests render without sending messages;
  distinguish these checks from physical-device push acceptance.

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
