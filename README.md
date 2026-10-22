# IT Work Study Launchpad

IT Work Study Launchpad helps new IT work-study students, including people with little or no prior IT background, learn foundational concepts, practice safe decisions, and ask for help early.

The release target is a small invited pilot with **individual sign-in and real saved training progress**. The current candidate supports certificate-verified AD sign-in and retains optional OIDC, with server-enforced record permissions. **It is not ready for real learners** until CCA directory/group and lookup-account settings, session revalidation policy, record policy, hosted persistence/recovery and browser QA are verified. A new OIDC registration is not required for AD mode. Local/shared-invitation demo modes remain synthetic-only.

The system helps new student workers:
- Complete a pre-assessment
- Receive an adaptive training path
- Review work style and role-alignment signals
- Learn beginner IT concepts
- Complete short module knowledge checks
- Complete Day 1 and Week 1 onboarding checklists
- Practice workflow and escalation scenarios
- Complete a post-assessment
- Generate mentor/supervisor summaries when stuck
- Retain saved training progress across navigation, refreshes and application restarts

## Product Philosophy

- Teach the mental model before the workflow.
- Use beginner-friendly, supportive language.
- Reinforce safe checks, clear documentation, and mentor escalation.
- Treat assessments as placement and growth tools, not pass/fail labels.
- Keep the assistant inside approved training content and safety boundaries.
- Keep credentials, live incident details and restricted procedures out of training content and free text. Store learner records only in an approved restricted service after the real-user release gates pass.

## MVP Focus

The first version focuses on:

1. Pre-assessment
2. Training path recommendation
3. IT Foundations content
4. Module knowledge checks
5. Day 1 checklist
6. Week 1 checklist
7. Post-assessment
8. Supervisor summary output

## Current Status

Real-user release candidate; invitations remain blocked. The current plan prepares Launchpad to replace the retired IT Support Assistant at `lesliec.ccaurora.edu` after owner-approved archival and cutover. No live routing or old-app state has changed. Launchpad keeps its own backend, service identity, storage and secrets.

Production AD mode (`LAUNCHPAD_AD_SESSION_POLICY=revalidate`, the default) uses verified LDAPS, explicit enrollment by a distinct directory namespace and `objectGUID`, learner isolation and read-only assigned mentors. Background eligibility checks require an approved read-only lookup account; learners' passwords are not saved for those checks. The interval is configurable from 1–300 seconds; **60 seconds is proposed, not approved**. Once a check is due, directory denial or outage blocks access and revokes that account's local sessions. Directory replication and in-flight requests limit immediate revocation claims. CCA must approve the lookup account, interval, outage behavior and directory policy before production launch. The current web certificate's October 28, 2026 expiry is verified. The operator reports Michael approved using it until renewal and authorized permission remediation; Michael is arranging renewal with Jordan next week. Permission remediation and validated activation must precede the controlled browser test; a replacement certificate is not a prerequisite for that authorized test.

The explicit [controlled work-study website test](docs/ad_authentication.md#controlled-work-study-website-test) uses `LAUNCHPAD_AD_SESSION_POLICY=controlled_test` with a newly marked isolated dataset, designated enrollment and invented training answers. It performs verified AD/group authentication at every sign-in, requires no background lookup account and sets a proposed **15-minute absolute session limit**. Activity never extends that limit; after expiry the learner must authenticate again. AD disablement/group removal can leave an existing session usable until expiry or local revocation. Production never silently selects this mode when lookup configuration is missing.

The [controlled browser routing proposal](docs/vm_deployment.md#controlled-browser-test-routing) prepares `https://lesliec.ccaurora.edu/` through existing Nginx to verified HTTPS on **loopback-only 8443**, using a separate backend key. It includes the exact old-route patch, certificate prerequisites, smoke checks and 503 rollback. The designated learner is already enrolled in private isolated `work-study-01` storage; the supplied identity, narrow search base and `direct` membership policy need no further input. Live authentication remains untested. The operator has authorized certificate permission remediation and activation using the existing owner-approved certificate. The latest shared-route check still returned the older route's 502; privileged execution remains pending because this session cannot use noninteractive sudo. See the [current activation record](docs/vm_verification.md#controlled-test-activation-authorization-2026-10-09). Do not enter credentials until remediation and endpoint validation are complete.

Use the [AD integration plan](docs/ad_authentication.md), [VM archive/cutover/rollback runbook](docs/vm_deployment.md), [sysadmin decisions](docs/vm_sysadmin_handoff.md) and [validation evidence](docs/vm_verification.md). The [learner-data inventory](docs/learner_data_policy.md) and [operations runbook](docs/real_user_operations.md) cover policy and recovery.

Completed pieces:

- Project plan and chatbot behavior requirements
- Pre-assessment v1 and post-assessment v1
- Separate role-alignment signal for work style and support needs
- Adaptive training paths
- Day 1 and Week 1 onboarding checklists
- Beginner IT foundation modules
- Low-stakes module knowledge checks
- App-readable JSON manifests for modules, module quizzes, checklists, assessments, and training paths
- Flask web prototype
- Safe rule-based "Ask a Question" guidance
- "Report I'm Stuck" mentor-summary flow
- Mentor review restricted to explicitly assigned learners in real-user mode
- Learner next-step guidance: Home, Learn, Progress and the learning path explain the next step (what it is and why it matters, from content `purpose` fields), show Not started / In progress / Completed text badges (display-only; completion rules unchanged), show the learner's open help requests (Open/Resolved; Resolved means the learner no longer needs help, not mentor approval), and turn the completed-path state into concrete follow-ups (Progress Check, remaining knowledge checks, mentor check-in)
- Read-only mentor check-in comparison: the descriptive difference between recorded starting-point and Progress Check scores (different questions, so not a validated measure of learning growth) and the one identical self-reported confidence question; it uses saved values only, never rescores, and is not readiness sign-off
- SQLite progress persistence with separate, explicitly provisioned real-user storage
- AD username/password sign-in over verified LDAPS, persistent attempt limits and bounded session revalidation; optional OIDC remains supported
- Explicit immutable account mapping, session expiry/revocation and CSRF protection
- Consistent backup/new-file restore tooling and startup checks
- Content validation, authorization tests and local TLS/process integration tests

Not included in this MVP:

- A configured or verified institutional identity tenant
- An approved hosted learner database, off-host backup service or completed hosted restore drill
- Web-based account administration, mentor progress editing or readiness sign-off
- Teams or SharePoint integration
- Full chatbot or LLM integration
- Sensitive internal IT procedures
- Advanced analytics

## Student Navigation

The student journey is **Assess → Follow your learning path → Practice → Check readiness**.

Learners have four header destinations. The product name returns to the homepage. In real-user mode, **Progress** always belongs to the signed-in learner and there is no learner selector. Learners cannot access **Mentor View**, even through its URL. Authorized staff enter a separate read-only Mentor View with an explicitly assigned learner list; each detail page shows only that learner. Local demo mode retains its separate footer Mentor View and synthetic learner selector.

| Destination | Existing capabilities available there |
| --- | --- |
| **Learn** (`/learn`) | Starting assessment and results, recommended path, all learning paths, modules and their knowledge checks, Day 1 and Week 1 checklists |
| **Practice** (`/scenarios`) | Written practice scenarios and the guided troubleshooting lab |
| **Progress** (`/student`) | Own saved progress, next action, detailed records and Progress Check; learner switching exists only in synthetic/local modes |
| **Help** (`/help`) | Ask a Question, Prepare a help request (the existing I'm Stuck form), My Help Requests (`/help-requests`: every open request plus recent resolved ones; the learner resolves or reopens their own), mentor-summary template |
| Staff **Mentor View** (`/supervisor`) | Explicitly assigned learners; `/supervisor/learners/<id>` opens authorized read-only details in real-user mode, including a descriptive starting-point and Progress Check comparison and read-only open help requests from assigned learners |

The homepage presents one main next action:

- **New learner:** Sign in with the approved organization account, then start the assessment. Enrollment is an operator action; signing in never claims an existing record by name. Synthetic demos instead require selecting an invented learner first.
- **Returning learner:** Continue at the first unfinished step, with a compact count of recorded path steps.
- **Current path recorded:** Review progress and discuss readiness with a mentor.

Learn uses the same start/continue/review states. Its module library, checklists, other paths, and assessment links remain available in expandable sections below the main action. Progress puts the next step before detailed records. **Switch demo learner** appears only in local/demo modes; real-user identity comes from the authenticated account.

A learning-path page puts the current step first, previews up to two upcoming steps, and groups the full remaining plan and recorded steps into separate expandable sections. Upcoming steps remain available; the suggested order does not introduce new locks. Path guidance, mentor-review prompts, additional practice, and the Progress Check are still accessible below.

The path-step count follows the existing completion rules. Module knowledge-check status is shown separately, and recorded completion does not establish mentor-confirmed readiness or permission to work independently. Module pages put reading first, followed by recording progress and one knowledge-check action. Recording the module does not complete its knowledge check.

Existing student URLs remain available for bookmarks. The Day 1 and Week 1 shortcut URLs still redirect to their checklist pages. Activity fragment identifiers are retained, and links are set up to reveal targeted steps inside expandable sections; browser verification remains pending.

## Demo Walkthrough

For a facilitated synthetic-data demo, use this flow:

1. Open the homepage and select **Start assessment**. Save an invented demo display name, or choose one of the fixed synthetic learners when guarded demo mode is in use.
2. Submit synthetic starting-assessment answers and review the recommended path. Open **Learn** to continue it or find a resource.
3. Follow the current path step. Read a module, record its completion, and take its knowledge check. Return to Learn to find the next unfinished step. Expand the plan when you need to review upcoming or recorded work.
4. Open **Practice** for a written scenario or the guided troubleshooting lab. Use **Progress** to inspect recorded work and reach the **Progress Check** after learning and practice.
5. Open **Help → Prepare a help request** and create a summary from an invented blocker. This generates text to share; it does not send a message. Ask a Question and the summary template remain available in Help.
6. For the mentor portion of the demonstration, use **Mentor View** in the footer to review saved local demo progress and the selected learner’s saved assessment signals, help summaries and practice drafts. Keep recorded completion separate from the mentor's readiness decision.

Saved progress uses local SQLite storage; the standard setup defaults to `instance/`. This is for prototype demos only, not production student tracking.

For a structured run, follow the [synthetic pilot checklist](docs/pilot_checklist.md). The [synthetic pilot results](docs/pilot_results.md) describe earlier evidence and do not establish browser or usability acceptance of this UX revision.

## Setup

Use Python 3.11 or newer and a local virtual environment for development. The candidate hosted runtime is pinned in `.python-version`; exact dependencies are in `requirements-real.txt`. The full suite requires those dependencies, including Authlib and Gunicorn. Installing them does not contact or configure an identity provider.

For local development:

```bash
python3 -m venv .venv
./.venv/bin/pip install -r requirements-real.txt
```

## Supervised synthetic usability test

This earlier synthetic-only exercise is retained as an optional development procedure. It does **not** satisfy the current request: the designated student must use their own AD account through the [controlled browser test](docs/ad_authentication.md#controlled-work-study-website-test). Do not substitute this demo for that test. Synthetic mode must remain loopback-only, with invented identities and answers, and must not load controlled-test/Pilot A inputs or use shared certificates.

Only the CCA VM is accessible in this workspace. Use its existing project environment (already sufficient for this demo; no installation needed). A fresh private participant dataset was prepared at `/tmp/launchpad-usability-20261009.3Sow3g/demo.sqlite`. Its `DEMO Nova Byte` persona has no submitted work. Startup was verified and then stopped. In the **VM terminal**, start the supervised foreground process:

```bash
cd /opt/project/ITWorkStudyLaunchpad
./.venv/bin/python -B scripts/start_usability_demo.py \
  --db /tmp/launchpad-usability-20261009.3Sow3g/demo.sqlite --serve
```

In **PowerShell or a terminal on the supervising operator's computer**, use the existing authorized `lesliec` SSH account, on the network/VPN that reaches this VM:

```bash
ssh -N -T -o ExitOnForwardFailure=yes -o StrictHostKeyChecking=yes -L 127.0.0.1:8765:127.0.0.1:8765 lesliec@10.117.1.127
```

Keep both terminals open. The student uses **`http://127.0.0.1:8765/`** in a fresh browser profile on that supervised computer. The operator authenticates SSH privately; no student server account or AD sign-in is involved. Both ends bind only to loopback; SSH encrypts the network hop, following the official [OpenSSH local forwarding semantics](https://man.openbsd.org/ssh#L). Browser HTTP is limited to that computer's loopback endpoint, not the VM's network address. Do not add `-g`, listen on `0.0.0.0`, publish a port, proxy through live Nginx or bypass a certificate warning. If the SSH host key is unknown/changed, stop and verify it through the existing IT/VM-owner process rather than disabling host-key checks. If port 8765 is busy, stop and inspect it instead of killing an unrelated process. The tunnel itself has not been tested from the supervising computer here.

The launcher fixes the bind address, disables debugger/reloader, validates a private guarded demo dataset before startup, uses a separate private demo signing key, and overrides inherited real/controlled/hosted configuration **in this process only**. It never initializes a missing database or silently adopts another dataset. It saves only to the selected synthetic database; cookies/persona selection are demo conveniences, not authentication. There is no production 15-minute session policy in this usability mode. Existing AD/session enforcement is unchanged.

For each additional participant, or if `/tmp` was cleaned, create a **new** dataset (never reset the earlier participant's work):

```bash
cd /opt/project/ITWorkStudyLaunchpad
LP_USABILITY_DIR=$(mktemp -d /tmp/launchpad-usability.XXXXXX)
./.venv/bin/python -B scripts/demo_data.py prepare --db "$LP_USABILITY_DIR/demo.sqlite"
./.venv/bin/python -B scripts/start_usability_demo.py --db "$LP_USABILITY_DIR/demo.sqlite"
./.venv/bin/python -B scripts/start_usability_demo.py --db "$LP_USABILITY_DIR/demo.sqlite" --serve
```

Stop on errors. Preflight without `--serve` opens no listener. The private dataset and signing key survive normal app stops/restarts; `/tmp` is disposable and is not backup or durable hosting. Stop only this foreground demo and its SSH tunnel with Ctrl-C when supervision ends. Keep anonymous usability notes in the [results record](docs/pilot_results.md#supervised-usability-preparation-2026-10-09); do not record real names, identifiers, credentials or private learner details. If data is unexpectedly missing, start a newly identified run rather than treating reseeding as successful recovery.

Use the [five student tasks, invented answer cards and observation sheet](docs/pilot_checklist.md) to record first click, completion time, wrong turns, assistance, confusion and a 1–5 busyness rating. Start as **DEMO Nova Byte** through the UI; don't preselect it for task 1. Riley and Quinn are seeded returner examples, not people to enroll. A real work-study student can participate while role-playing a synthetic persona; this exercise does not save their actual training performance or establish readiness for independent work. The three personas are intentionally selectable, so this test does not demonstrate learner isolation or mentor permissions.

If an approved copy and Python environment already exist **on the supervised test computer**, the same demo preparation/launcher works on Linux with a canonical private `/tmp` directory and loopback access, without SSH. No local computer filesystem or environment is accessible here; the Windows operator commands above use the verified VM environment instead. Do not copy protected databases, credentials, certificates or the full VM as part of setting up a local demo.

## Run Locally

```bash
LAUNCHPAD_SECRET_KEY="replace-with-a-local-demo-secret" \
  ./.venv/bin/flask --app app run --host 127.0.0.1 --port 5000
```

This development command is for loopback access only. Do not expose it or `python app.py` to invited users.

Then open:

```text
http://127.0.0.1:5000
```

## Run Checks

After setup:

```bash
./.venv/bin/python scripts/check_all.py
```

The check command validates Markdown and JSON content, then runs the complete automated suite. Local network tests need loopback sockets and subprocess execution. The real-user integration test runs a temporary HTTPS identity server and Gunicorn against a new isolated database; it does not contact an institutional provider. The test subprocess removes hosted Launchpad configuration so it cannot inherit a live database or access settings. All persistence tests use disposable databases.

The tests cover:

- Assessment auto-scoring and mentor-review separation
- Role alignment scoring and recommendations
- Module quiz content, scoring, and local completion progress
- SQLite progress persistence
- Training path routing
- Content/checklist loading
- Safe guidance behavior
- Stuck summary generation
- Homepage onboarding and continuation states
- Four-category navigation and separate Mentor View access
- Regular-use sign-in policy (`LAUNCHPAD_AD_SESSION_POLICY=signin`) and schema-version-2 migration: see [docs/regular_use_release.md](docs/regular_use_release.md)
- Current-step path displays, recorded-work disclosures, and preserved feature links
- Module action states and unchanged saved data during page browsing
- Invalid-session and malformed-progress recovery
- Hosted invitation/host checks, CSRF, secure-cookie settings and required-form validation
- Safe storage errors without exposing request details
- Full written responses stored in SQLite while cookies stay below browser limits
- Real HTTP scoring/completion persistence across an actual server-process restart
- Guarded startup, consistent SQLite backup, new-file restore and build-environment isolation
- Signed OIDC token validation, state/nonce/PKCE checks and denial of unregistered identities
- Own-record attribution, cross-learner read/write denial, assigned mentor-only reads and privilege-escalation denial
- Server session expiry, account/assignment revocation and copied-cookie rejection after logout
- Real OIDC over local TLS, exact scoring and saved progress through a Gunicorn process restart
- Real-user backup/restore, restored-session invalidation and refusal to open real data in ordinary/demo mode
- On non-root Linux with nginx installed: temporary TLS proxy → Unix-only Gunicorn, secure forwarding/Host rules, scoring and callback-log redaction. This check is explicitly skipped when its system prerequisites are unavailable; it executed on the CCA VM.

## UX Verification Still Required

Browser execution was unavailable for this UX revision. Firefox and a second browser have not been tested, and rendered checks at approximately **375px**, **768px**, and **1440px**, keyboard-only navigation, screen-reader basics, and **200% zoom** remain pending. HTTP responses, template inspection, and automated tests do not establish visual or browser compatibility.

The interface uses native `details`/`summary` disclosures and retains skip navigation and focus styling. These choices support accessible interaction, but their behavior still needs the browser and keyboard checks above. Verify compact navigation, visible focus, touch targets, text wrapping, disclosure operation, and links into collapsed content.

Run these five tasks with another person using prepared synthetic learner states:

1. **Start:** As a new learner, find the starting assessment and explain what comes after it. Use invented answers only.
2. **Resume:** As a returning learner, identify the next unfinished action and the recorded-step count, then open that action without facilitator direction.
3. **Find and revisit:** Find the Day 1 checklist and a module outside the current step. Return to the full learning plan and locate a recorded step.
4. **Get help:** Prepare a help request for an invented blocker and explain how the mentor receives the summary.
5. **Review completion:** With the current path recorded, find progress and the Progress Check, explain what still requires a mentor's judgment, and locate the separate Mentor View for the facilitated review.

Record task completion, time, navigation mistakes, assistance needed, and the participant's comments about density and next-action clarity. Do not treat the reported “busy” concern as resolved until another person has tried the revised interface.

## Architecture and Data

- Flask serves route handlers and Jinja templates.
- Markdown and JSON under `content/` provide training and assessment material.
- SQLite stores synthetic progress under the ignored `instance/` directory in local mode. Real-user mode requires a separate explicitly initialized database on an approved persistent volume; existing prototype databases are never adopted automatically. Assessment answers, help summaries and written scenario drafts stay in SQLite, not session cookies. Mentor View loads the selected learner’s latest assessments, 10 help summaries and 20 written drafts; older records remain stored.
- Rule-based Python modules handle scoring, paths, guidance, quizzes, and summaries.
- Authentication is selected explicitly by `LAUNCHPAD_AUTH_BACKEND=ad` or `oidc` (the compatibility default). AD requires an approved directory namespace and verified `objectGUID`; OIDC retains its exact HTTPS issuer/subject binding. Switching modes never reinterprets existing identities. Names, email, form fields, headers and directory/provider role claims grant no record access. Only explicitly enrolled identities can enter. No institutional directory or provider has been contacted by the tests.
- Server-side sessions use stored token digests. Production defaults to eight hours absolute/thirty minutes idle; the explicit isolated work-study test uses 15 minutes absolute with no sliding extension or remember-me. Local logout, account disablement and removed mentor assignments revoke access. Upstream institutional logout is a separate provider acceptance check.
- Real mode refuses demo/pilot configuration and unrecognized storage. Conversely, ordinary/demo mode refuses datasets containing real-user account tables or a real-data marker. No password management, analytics or institutional content integration is added.

## Project Structure

```text
app.py                         Flask entrypoint
launchpad/                     App logic, content loading, scoring, guidance
templates/                     Jinja screens for the MVP prototype
static/                        CSS and lightweight client behavior
instance/                      Ignored local SQLite database location
content/modules/               Human-readable training modules
content/checklists/            Day 1 and Week 1 checklist Markdown
content/assessments/           Human-readable assessment drafts
content/data/                  App-readable manifests, quizzes, and assessment data
docs/                          Planning and behavior requirements
scripts/check_all.py           One-command validation and tests
scripts/validate_content.py    Content and data validation
tests/                         Unit, authorization and local HTTP/TLS integration tests
```

## MVP Routes

- `/` home
- `/learn`
- `/help`
- `/pre-assessment`
- `/assessment-results`
- `/training-path/<slug>`
- `/modules`
- `/modules/<module>`
- `/modules/<module>/quiz`
- `/day-1-checklist`
- `/week-1-checklist`
- `/checklists/<slug>`
- `/scenarios`
- `/scenarios/<scenario_id>`
- `/ask`
- `/stuck`
- `/mentor-summary`
- `/post-assessment`
- `/supervisor`
- `/supervisor/learners/<learner_id>` (real mode, explicit staff assignment required)
- `/student`
- `/auth/login`, `/auth/callback`, `/auth/logout` (real mode only)

## Real-User Deployment Preparation

Use the [VM deployment plan](docs/vm_deployment.md) for the proposed owner-approved archive and replacement of the assistant at `lesliec.ccaurora.edu`. The [VM environment example](deploy/vm/launchpad.env.example) selects AD with the exact group DN verified by the user's ADUC observation on 2026-10-08; other unresolved required settings remain blank and block startup. The user also confirmed the group's existence and their own membership. See [the evidence and pending approvals](docs/ad_authentication.md#identity-eligibility-and-enrollment): broader production eligibility, membership policy, CCA approval of the supplied CA fingerprints and lookup-account availability remain pending. The isolated designated test separately has an operator-supplied `direct` policy, search base and explicit enrollment; it does not require a background lookup account. No new OIDC registration is required. The [generic AD environment](deploy/staging.env.example) carries the same DN but is a non-VM reference, not the selected Unix-socket configuration. The [operations runbook](docs/real_user_operations.md) covers isolated provisioning, explicit enrollment, persistence and recovery. The release target remains one WSGI service and one durable local SQLite volume. Nothing has been installed or deployed; the older Render files remain historical synthetic references.

On 2026-10-08 at 22:01:51 UTC (16:01:51 MDT), a bounded credential-free connection to `CCCDC01.ccc.ccofc.edu:636` completed TLS 1.3 with hostname and chain validation against an explicit temporary bundle of the user-supplied public Windows-store exports. This verifies LDAPS against that bundle; centrally managed deployment provenance and CCA approval of its exact fingerprints remain unverified. No credentials were sent and system trust was unchanged. See [CA evidence and verification](docs/ad_authentication.md#ad-trust-discovery-and-public-certificate-export).

Build with `requirements-real.txt` and `scripts/check_all.py`. The VM unit runs `scripts/start_real.py` with a mandatory Unix-socket binding. AD mode requires exact trusted hosts, independent signing secret, persistent learner and AD throttle files, verified CA/host/group/namespace settings and approved lookup credentials. Explicitly provision new files through `scripts/manage_real_data.py`; startup never initializes or migrates them. Follow the runbook for permissions, archival and separately authorized service actions.

If OIDC is selected instead, the retained adapter requires authorization code, PKCE S256, RS256 ID tokens, `client_secret_basic` and same-origin authorization metadata. Its [registration checklist](docs/sso_registration_checklist.md) is optional for that backend; none of those registration values is required by AD mode.

Real-user enrollment and mentor grants require restricted operator access. Start with a new empty database unless an authorized, separately tested migration is necessary. Existing records must never be matched by name or email. CCA has confirmed read-only mentor access to explicitly assigned learners. The existing admin label grants no additional web permissions; operators manage enrollment and assignments outside the web UI. Actual rosters and assignments still require CCA authorization.

The older `render.yaml`, `scripts/start_pilot.py` and invitation gate are **synthetic-only references**, not a real-user release path. Their shared invitation cannot protect individual learner records. See [deployment status](docs/pilot_deployment.md) before using any deployment file.

## Known Limitations and Release Gates

The [standalone initial-login diagnostic](docs/ad_authentication.md#standalone-initial-login-diagnostic) reuses the existing AD adapter and private Pilot A identity for one terminal-prompted bind, GUID and group check against the pinned CA bundle. It needs no lookup account or enrollment and creates no app session. It is prepared but unexecuted: the user search base and diagnostic direct/nested selection are still needed. Institutional CA approval remains separately pending; a diagnostic against the supplied bundle does not establish that approval. The full application's background checks are unchanged.

The [next controlled AD login test](docs/ad_authentication.md#controlled-login-test-preparation) is prepared separately from deployment. The [non-secret configuration example](deploy/ad-login-test.example.json) uses the preserved, Git-ignored public bundle at `work/ad-ca-review/launchpad-ad-ca.pem`; its bytes match the bundle that passed LDAPS hostname/chain validation. Institutional fingerprint approval and actual authentication remain pending. The user designated their own AD account as learner A with role `learner` and has [supplied its ADUC-verified UPN and GUID](docs/ad_authentication.md#verify-learner-as-identity--read-only-preparation). Those values passed offline format checks and are retained only in a private Git-ignored input file; no additional learner identifier is missing. Enrollment will use a new isolated dataset. The full application test requires a separate approved read-only lookup account and human-operated memory-only password prompts; the user's account cannot supply the background lookup identity. No enrollment or credentialed test has been performed. The helper opens no web listener and does not establish browser or hosted acceptance.

- LDAPS hostname/chain validation passed against the supplied temporary CA bundle; institutional approval of its fingerprints and centrally managed provenance remain unverified. Username conventions, group eligibility, read-only lookup permissions, replication delay and session-revalidation policy remain unverified. No learner password is retained; the background check uses a separately approved lookup credential. Local mode is synthetic-only.
- Hosting/content authorization, minimum learner labels, retention/deletion, mentor assignments, incident ownership and the audit policy need organizational approval. The access-audit table records local security changes, not a comprehensive record-read audit or operator approval history.
- No automatic record-retention/deletion setting or purge job exists. The [retention policy template](deploy/retention-policy.example.json) is an operator worksheet, not application configuration; CCA must choose periods and an approved enforcement procedure. Session expiry does not delete records.
- Off-host encrypted backup transport/scheduling, host logs, durable mount behavior and actual hosted recovery are not configured or verified. Local backup tests do not satisfy that gate.
- Firefox, a second browser, responsive layouts, keyboard, screen-reader behavior and 200% zoom remain unverified. Intended-user evidence that the interface feels less busy is still needed.
- Completion is recorded practice and does not demonstrate competence or authorize independent work. Staff cannot edit progress or grant readiness through the app.
- Unfinished guided-lab interactions remain browser-session state; explicit completion and written drafts are saved. Refreshing a submitted quiz/help/scenario/post-assessment can repeat the submission; counts represent attempts, not distinct tasks. Resume unfinished labs before signing out or expect to restart that practice interaction.
- Rule-based guidance cannot know local procedures and does not replace a mentor. No Teams/SharePoint, analytics, LLM, accessibility certification or formal security approval is included.

Before launch, verify approved sign-in, two learners' separation and assigned mentor access on the actual host; restart it and prove persistence; retrieve an off-host backup, restore to a new file, reconcile permissions and prove continued saving. Complete the browser and intended-user checks. Keep feature scope fixed while closing those gates.

Do not put credentials, live tickets, device identifiers, internal URLs or restricted procedures in training responses. Do not publish code, learner records, identity mappings or operational evidence in a portfolio without authorization and sanitization.
