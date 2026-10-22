# Learner information, minimization and policy decisions

Updated 2026-10-08 from source definitions only: [progress storage](../launchpad/storage.py), [accounts](../launchpad/accounts.py), [real storage](../launchpad/real_data.py), [routes](../launchpad/web.py) [OIDC](../launchpad/oidc.py), [AD](../launchpad/ad.py) and [AD security state](../launchpad/ad_state.py). No learner rows, database contents or backups were queried to produce this inventory. It describes the schema and processing, not the number, identity or actual answers of existing learners.

CCA has confirmed real training and read-only mentor access to explicitly assigned learners. That access includes the assigned learner's saved training details, not just completion flags. CCA must approve the permitted purpose, notice, minimum identifying label, retention and custodians before real training. The application is not yet accepted for hosted real-user operation.

## Information currently stored

| Location | Types of information | Purpose and current behavior |
| --- | --- | --- |
| `students` | Internal integer ID, display label, creation/update timestamps | Links progress to a learner. One approved 1–120 character label is required; an alias is possible. Full legal name is not required and labels need not be unique. |
| `accounts` | Account ID, identity namespace and subject (AD directory namespace/objectGUID or exact OIDC issuer/subject), learner ID for learners, role, active flag, creation time | Explicit sign-in binding and local authority. Mentor/admin accounts have no learner binding. No email, institutional student number or local-password column. |
| `mentor_assignments` | Staff account ID, learner ID, assignment time | Read-only scope. Removing a grant removes the active link and records an audit event. The staff roster/approval remains an operational responsibility. |
| `assessment_results` | Learner and assessment IDs/type, technical score, readiness/path labels, role recommendation/summary JSON, complete answers JSON, submission time | Every pre/post attempt is saved. Answers include knowledge choices, confidence ratings, written responses and work-style/support answers; derived role summaries are personal training inferences. |
| `module_progress`, `checklist_progress`, `activity_progress` | Learner/content/item IDs, completion flags, completion/update times | Current progress, updated in place. These tables do not retain every change as a separate history entry. |
| `module_quiz_results` | Learner/module IDs, score/earned/possible, answer details JSON, submission time | Every submitted quiz attempt. Details include prompts, selected/correct answers, correctness and feedback. |
| `scenario_attempts` | Learner/scenario IDs, scenario title, written response, submission time | Saved written practice attempts. Required when submitting a draft; not a ticket or operational incident record. |
| `stuck_reports` | Learner ID, context, tried steps, blocker/question, generated summary, submission time, learner-set resolved time | Saved help requests. Summary text repeats the learner label and submitted training details. The app generates/saves text; it does not send it to anyone. `resolved_at` (schema version 2) is set when the learner marks that they no longer need help and cleared when they reopen; it is not mentor approval. The original text and time are never rewritten. |
| `auth_sessions` | SHA-256 token digest, account ID, creation/expiry/last-seen/idle-limit/revocation times | Server-checked sessions. The raw handle is not stored in this table. Expiry/revocation blocks use but does not delete the row. |
| `access_audit` | Event ID/type, linked account/learner IDs, time | Enrollment, mapping, activation, grant and session events. Linkable to people despite omitting names/answers/subjects. Not a complete record-read audit or human operator-attribution log. |
| Separate `ad-security.sqlite` | Keyed HMAC of canonical login name plus attempt timestamps; schema version | Persistent admission limits. No plain username, password, profile or progress. At most 1024 attempt rows; rows older than five minutes are cleaned during later login attempts, not on a background schedule. Protect and handle this metadata under CCA policy. |
| `real_dataset_metadata` | Schema version, random dataset identifier, creation time | Validation and recovery metadata, not a learner profile. |

Work-style signals include technical/support interests, documentation/process strengths, handling unclear tasks, asking for help and structured shadowing support. They are training-planning signals, not a competence certification. Their permitted interpretation and use require CCA policy input.

## Other processing and copies

- **Ask a Question:** processes the question and renders rule-based guidance; that route does not save the question in SQLite. This does not control browser history or proxy logging.
- **AD sign-in:** transiently handles a submitted username/password, verifies an enabled group-eligible directory account, and stores only the separately enrolled namespace/objectGUID binding. Passwords are not saved in records, cookies or attempt storage. The approved read-only lookup credential lives in protected service configuration/process memory, not learner storage. Background checks use that credential, never retained learner passwords. A bounded in-memory positive-check cache is empty after restart; AD outage or denial at the next due check revokes that account's local sessions.
- **Optional OIDC:** requests only `openid`. Provider tokens/claims are processed transiently; email/profile claims are not requested or used for enrollment. Issuer/subject bindings are stored as above.
- **Browser cookie:** signed and client-readable, not encrypted. Contains the opaque session handle, CSRF token, unfinished guided-lab state and transient login transaction material. Secure/HttpOnly/host-only/SameSite settings limit transport/access; do not record cookies in QA evidence. Full saved answers/help transcripts are in SQLite, not the cookie.
- **Backups, recovery and legacy copies:** SQLite snapshots contain all records, identities, assignments, sessions and audit history. SQLite sidecars, restored files and any reviewed migration copies require the same handling. File permission `0600` is not encryption; storage encryption and encrypted off-host transfer are host/operator responsibilities.
- **Logs:** Gunicorn emits time/method/status/duration; application errors use generic events, endpoint names, error type and a reference. CCA/hosting/SSO logs are separate and may contain addresses, identity details or callback query strings. Verify access, redaction and retention on the selected services.
- **Manual copies:** no application CSV/PDF export, upload, analytics or messaging integration is implemented. People can still copy, print or screenshot displayed records. Give reviewers an approved handling procedure.

## Minimum collection for this release

Keep the immutable issuer/subject binding, internal IDs, one approved short display label, role/active status, explicit assignments and training records required by the current workflow. Prefer a short work-study alias or other CCA-approved label over a full legal name. A label is a convenience, never proof of identity.

Do not add email, student number, date of birth, contact details, demographics, directory profile scopes or extra identity claims. Use concise training-only responses. Never enter credentials, live tickets, personal cases, device identifiers, internal URLs or restricted procedures. In real mode every saved written field (assessments, practice drafts, help requests) now shows a sensitive-information warning, and Ask a Question states that it is not saved; an approved participant notice is still required before real training. No extra profile collection is proposed.

The current assessments require written and work-style answers, and result reconstruction/mentor review uses saved answers. Silently dropping those fields, storing only a score or suppressing role questions is not an existing configuration option; it would change the current workflow. If CCA does not approve those records, that is a launch policy decision requiring a bounded reviewed change before collecting them. No curriculum, scoring or completion rule was changed in this preparation.

## Retention stays undecided and operator-configurable

Use [the policy template](../deploy/retention-policy.example.json) to record CCA's chosen periods, triggers, owners and procedure references. The `progress_and_assessment_results` category includes derived work-style/support signals; CCA must explicitly decide whether those signals should instead have a shorter period. The current JSON storage does not enforce different periods within an assessment. All durations are deliberately `null`: **undecided**, not zero-day deletion or permission to retain forever. Keep completed policy/approval records in CCA's approved location; do not add learner identifiers or credentials to the template.

**The application does not read this policy file. There is currently no automatic retention/deletion setting or purge scheduler.** Filling the worksheet does not enforce disposal. CCA must approve and establish the operational procedure, or require a separately reviewed implementation, before real training. No deletion command or scheduler has been added or run.

| CCA decision | Required distinction |
| --- | --- |
| Training-record period and trigger | From last activity, end of appointment, training completion or another approved event; determine any correction, appeal or hold process. |
| Written responses and work-style signals | Whether they have the same period/purpose as completion records; current storage cannot selectively omit them through configuration. |
| Departed accounts and mappings | When to disable access versus when records may be disposed of. Disablement preserves progress/history and is not deletion. |
| Sessions, audit and admission metadata | Access expires after 30 minutes idle/eight hours absolute, but expired/revoked rows remain. Choose metadata retention and audit responsibilities separately. |
| Backups and retained copies | Snapshot interval, retention, encrypted destination, key custodian, failure alerts, recovery targets, drill interval and holds. Include legacy/migration/recovery copies and disposal after restore. |
| External logs | Proxy, hosting, SSO and operational records may use separate policies; specify access owner and duration for each. |
| Authority / accountability | Data custodian, backup/recovery operator, approval for disposal/corrections and learner notice. Confirm whether the existing limited audit plus restricted operator records meets CCA's requirements. |

The latest-10-help/latest-20-drafts UI limits are display limits, not retention. Assessment/quiz/help/practice attempts accumulate; account disablement and session revocation do not remove them. Backup pruning is not implemented. A restored snapshot can reintroduce older permissions or records; reconcile current revocations/holds/disposal decisions before reopening access.

## Fresh start and migration options

| Option | When appropriate | Safe boundary |
| --- | --- | --- |
| **Fresh real-user dataset — recommended if continuity is not required** | CCA agrees learners may begin with empty real training progress. | Explicitly initialize a separate empty database; enroll verified subjects and approved labels. Preserve existing databases unchanged. Do not imply their contents were inspected or are necessarily synthetic. |
| **Reviewed migration** | CCA identifies older real progress that must carry forward and can independently verify ownership. | Work only on a restricted new copy after a consistent retained backup. Review the actual schema, authority and record quality; independently map exact issuer/subject to numeric learner ID. Never match names/email. Uncertain records stay unbound/inaccessible. |

Staging itself should always use a separate acceptance dataset with designated test accounts. Test answers are not real completion credit. AD enrollment must use the approved stable directory namespace and independently verified objectGUID. Existing OIDC identities remain distinct; switching the backend does not relink progress. If optional OIDC is used, production subjects may differ across client registrations. Do not copy staging bindings blindly.

If migration is required, the custodian must authorize inspection separately, review mappings and schema, compare scores/completions on the copy, test access isolation and demonstrate recovery before pointing a live service at it. Existing helpers support reviewed explicit bindings, but the CLI deliberately cannot automatically convert/adopt an arbitrary legacy database. A source-specific migration needs its own tested plan. No existing database was migrated, assigned, pruned or deleted here. See [the migration and recovery runbook](real_user_operations.md).

The assistant archive is a separate restricted retirement record, not Launchpad training data. Archive ownership, retention and eventual authorized disposal need their own policy decision; do not import its logs or credentials into Launchpad. See the [archive/cutover plan](vm_deployment.md).
