# Staging verification and release gate

> Current VM preparation (2026-10-08): Plan a future approved cutover of `lesliec.ccaurora.edu/` from the archived older assistant to Launchpad; preserve `itsupport` unless separately retired. The candidate uses verified LDAPS with explicit GUID enrollment, pending directory/lookup-account and lifecycle approval. No live directory access, retirement, deployment or routing change has occurred. Use [VM deployment](vm_deployment.md), [AD authentication](ad_authentication.md), [sysadmin decisions](vm_sysadmin_handoff.md) and [current validation](vm_verification.md). Historical OIDC test results below do not establish AD or hosted acceptance.

Updated 2026-10-08. Run only after CCA approves AD/lookup-account policy and explicitly authorizes the VM deployment and cutover. This checklist is not a record of hosted success. Use new acceptance learner/throttle stores, designated CCA accounts and invented training responses; keep feature scope frozen.

## Evidence record and prerequisites

Record the candidate revision/source fingerprint, non-secret configuration version, host/runtime version, date, verifier role, browser/version and pass/fail/blocker for each check. Keep detailed evidence in an approved restricted location. Do not save raw tokens, cookies, authorization-code URLs, populated secret files, real answers or identity rosters in screenshots, HAR files, logs or this repository. Use neutral account labels A/B/M in the report.

- [ ] Owners authorize the complete restricted old-app archive/restore check and `lesliec.ccaurora.edu/` cutover/window. Preserve `itsupport` unless separately retired; record the failed old-backend baseline and prohibit automatic restart fallback. Follow [VM deployment](vm_deployment.md), not synthetic `render.yaml`.
- [ ] [AD requirements](ad_authentication.md) approved: actual host/CA/UPN/search/namespace, use of the ADUC-verified group for Launchpad with an explicit direct/nested policy, restricted lookup account, proposed configurable interval/outage policy and maximum end-to-end removal delay. Group existence, exact DN and the user's own membership are observed; this approval/live-verification gate remains unchecked. Proposed 60 seconds is not owner approval. Inject secrets privately; the [OIDC checklist](sso_registration_checklist.md) applies only to separately selected OIDC mode.
- [ ] Data/backup owners and staging notice/record handling approved; production retention/migration decisions tracked in [the policy inventory](learner_data_policy.md).
- [ ] Build uses the pinned runtime/dependencies; complete suite and content validation pass without opening the staging/production database.
- [ ] Durable storage verified; NEW learner and AD throttle stores explicitly provisioned/verified. The mandatory VM unit uses `scripts/start_real.py` with the private Unix socket, real mode enabled and demo/pilot disabled. No missing-state reseeding.
- [ ] Enroll A and B as distinct learners (use duplicate display labels for one isolation check), M as mentor assigned only to A, and a designated CCA identity with no local enrollment. No real learner row is repurposed for tests.

## Authentication, authorization and UI

| Check | Procedure | Required result |
| --- | --- | --- |
| Unauthenticated | Fresh browser/session: open Progress, Mentor View and a saved-result URL; try a direct progress POST. | No records disclosed or written; protected requests denied. Static assets and the login page can be public. |
| CCA AD sign-in | Use the actual HTTPS form and approved LDAPS host in Firefox/second browser; test short/full approved UPN, wrong/blank password, disabled account and nonmember. | Only enabled eligible enrolled A reaches A’s progress. Password absent from logs/state/cookies; safe failure for denied users. Verify certificate trust/hostname; no transport/referral fallback. |
| Unenrolled / group versus role | Sign in as an eligible unenrolled identity, an enrolled learner group member and an assigned mentor. | Unenrolled identity denied. Group eligibility never grants local roles or records. No automatic creation or name/email/UPN matching. |
| Cross-learner reads/writes | A and B record distinct agreed outcomes. Navigate/reload both. With these test accounts, send direct requests containing another learner ID/name/role; try Mentor View/detail URLs as a learner. | Submitted identity cannot change attribution; learner Mentor View denied (403); the other learner's saved values remain unchanged. Duplicate labels do not merge accounts. |
| Mentor scope | As M, open overview and A's detail; request B's detail URL directly and attempt a learner progress POST. | Only A listed/readable; B returns 404 without details; write denied. Mentor page is read-only. No HTTP role/grant management exists. |
| Local logout / replay / old cookies | Log out, use Back/reload; in an isolated harness replay a copied cookie and provide old-assistant cookie fields without retaining them in reports. | Fresh protected requests/replay denied. The distinct Launchpad cookie/key never reuse old identity. Already-rendered content is distinct from new authorized responses. Local logout works during AD outage. |
| Disablement / grant removal | Disable A locally/remove M’s assignment; retry sessions. Under directory-owner authorization, disable the test AD account/remove group membership and measure due checks across its sessions. | Local changes invalidate access. AD caches only within the configured interval; due denial revokes all account sessions. Measure replication/network/in-flight delay and emergency local revocation. OIDC remains manual institutional-to-local offboarding. |
| Expiry / invalid requests | Confirm eight-hour absolute/30-minute idle behavior with approved test tooling; send missing/invalid CSRF and cross-origin forms. | Expired access and invalid writes rejected; no saved-progress changes. Never shorten policy or disable checks just to make the test pass. |
| Directory/storage failures | In authorized staging, exercise directory/lookup outage, wrong-host/untrusted/expired certificate and unavailable learner/throttle state without changing source data. | Due AD failure denies the request and revokes all account sessions; fresh password sign-in required after recovery. No mutation on rejection, retained password, fallback/referral, diagnostic leak or replacement state. Logout stays local. |
| Persistent login limits | With approved nonproduction tests, verify global 50/60-second and canonical-user 5/300-second limits, successful-attempt counting, workers/restart and untrusted-IP headers. | Limits apply before directory attempts and survive restart; raw usernames/passwords absent from state. Do not deliberately lock out real AD accounts to prove an app limit. |

The local suite exercises isolated AD transport/identity/lifecycle/throttle and shared authorization; optional OIDC tests cover signed-token/state/nonce handling. See [current evidence](vm_verification.md). Neither backend’s fixtures prove CCA directory/provider behavior; repeat deployment-dependent checks on the actual host.

## Training, persistence and recovery

- [ ] Start the assessment with agreed fixture answers and independently recorded expected score/path. The existing local regression fixture yields **18%**; do not treat every valid submission as that score.
- [ ] Open a module, record completion, submit its quiz using the agreed correct answers (**3/3, 100%** for the existing three-question fixture), and check a valid wrong-answer attempt receives its exact lower score and is recorded as an attempt. On a fresh unrecorded module, quiz submission alone must not mark module reading or guided/path activities complete; the current quiz count does not require a passing score.
- [ ] Record checklist items, save a practice draft/help summary and explicitly complete guided practice. Starting a guided activity alone must not mark it complete. Submit the Progress Check and verify the agreed result; completion is not mentor-confirmed readiness.
- [ ] Navigate away, return and reload; sign out and back in; restart the **actual hosted process**. Verify exact saved scores, completions and text for A, with B unchanged. Unfinished guided interaction is session-local; explicit saved completion must persist.
- [ ] Verify the configured concurrency expected for the small cohort: simultaneous independent A/B actions, no cross-attribution, lock errors, unexpected timeouts or lost writes. Record observed capacity limits; a single local HTTP flow is not a load test.
- [ ] Create a consistent snapshot with `manage_real_data.py backup`; transfer through approved encrypted transport to the approved off-host destination and verify its checksum there. Confirm the schedule, failure alerts, retention owner and restricted access actually work.
- [ ] Create and retrieve a separate consistent restricted AD throttle-state backup through the approved SQLite backup/quiesced-copy procedure. The learner snapshot command does not back up that schema. Include both stores, stable namespace/configuration and private secret-recovery custody in the recovery inventory.
- [ ] Close traffic for a restore drill. Restore learners to a NEW path with `manage_real_data.py restore` and preserve originals. Restore/verify throttle state separately using a consistent SQLite backup/quiesced-copy procedure; the learner backup tool is not a throttle backup tool. Rotate signing key, reconcile current eligibility/grants, retain namespace and close all login admission for at least 300 seconds after rotation or lost/stale throttle state; then verify both limits and the compatible candidate.
- [ ] Verify exact backed-up state, absence of an intentional later test change, denial of old sessions/revoked accounts, correct mentor scope, new saves and another restart. Record recovery duration and recovered interval against CCA's targets.
- [ ] Review rollback: close Launchpad or use the approved maintenance response. Archived routing restores only the old failed-backend baseline; no automatic old-auth restart or old-code access to Launchpad records. Later rollback requires a compatible authenticated build/configuration; data recovery remains separate.

Commands and safeguards are in [real-user operations](real_user_operations.md). Provider disk snapshots or a local backup file alone do not establish off-host recovery.

## Browser and accessibility requirements

Run this matrix in **Firefox and a second browser**, noting exact versions:

- [ ] Rendered widths about **375, 768 and 1440 px**: login, home/next action, Learn/path, assessment/quiz, Practice/lab, Progress, Help and assigned-learner Mentor View. No clipped controls, unreadable content or accidental horizontal page scrolling.
- [ ] Keyboard-only navigation: skip link, meaningful focus order, visible focus, all forms, native disclosures, fragment links into collapsed steps, guided actions, sign-in and logout. No traps or unreachable actions.
- [ ] Screen-reader basics: page landmarks/headings, control names, required fields, errors, scores and completion states are understandable. Verify actual reading/interaction, not just DOM labels.
- [ ] **200% zoom**: next action, navigation, forms, error messages, disclosures and staff detail remain usable without hidden actions. Check text/button contrast in the rendered theme.
- [ ] AD login/logout/account switching: valid/denied identity, expired form/session, directory failure, Back/reload, old-cookie rejection and own-record attribution after another account signs in. If separately testing OIDC, include its full redirect chain.
- [ ] Intended-user tasks from README: start, resume, find/revisit, get help and review completion. Record task success, time, wrong turns, assistance and perceived density. Include an assigned mentor review. Do not infer that “less busy” is proven from the UI code or test count.

## Current status and acceptance

**Current local evidence:** see [VM verification](vm_verification.md); the older 210-test OIDC result is historical, not AD acceptance. **Unverified:** actual CCA LDAPS/group/lookup lifecycle, hosted cutover/runtime/persistence/coordinated recovery, rendered Firefox/second browser, responsive layouts, keyboard, screen reader, zoom and intended-user acceptance. No browser or screen reader is available in this environment.

Do not open real training until CCA's owner accepts the relevant policy and all blocking identity/isolation/persistence/recovery/browser checks. Record remaining nonblocking issues explicitly. Stop access on unauthorized records, unexpected grants, lost progress, authentication bypass or failed recovery; preserve restricted evidence and notify the named CCA owner through the approved process. This preparation sends no messages or invitations.
