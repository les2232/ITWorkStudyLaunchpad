# Real-user release operations and acceptance gates

> Current VM preparation (2026-10-08): Plan a future approved cutover of `lesliec.ccaurora.edu/` from the archived older assistant to Launchpad; preserve `itsupport` unless separately retired. The candidate uses verified LDAPS with explicit GUID enrollment, pending directory/lookup-account and lifecycle approval. No live directory access, retirement, deployment or routing change has occurred. Use [VM deployment](vm_deployment.md), [AD authentication](ad_authentication.md), [sysadmin decisions](vm_sysadmin_handoff.md) and [current validation](vm_verification.md). Historical OIDC test results below do not establish AD or hosted acceptance.

Updated 2026-10-08. **This candidate is not approved for real learners or deployment.** The release now targets real learners and saved training progress. The previous shared invitation and selectable synthetic personas do not meet that requirement. This runbook prepares bounded operations; it does not establish institutional approval, hosted authentication, or hosted recovery.

CCA has confirmed online delivery, read-only mentors for explicitly assigned learners and frozen feature scope. The current preparation adds verified AD authentication; start with [AD configuration](ad_authentication.md), [VM cutover](vm_deployment.md), [data-policy inventory](learner_data_policy.md) and [hosted verification](staging_verification.md). The [OIDC checklist](sso_registration_checklist.md) is an optional alternative reference, not a prerequisite for AD mode.

**Controlled-test exception, prepared 2026-10-09:** use the separate [work-study website test procedure](ad_authentication.md#controlled-work-study-website-test) for designated students, new isolated storage and invented answers. Explicit `controlled_test` policy needs no background lookup account and enforces 15 minutes absolute; existing sessions can outlive AD disablement/group removal until expiry or local revocation. This production runbook and VM service remain on `revalidate`; production startup refuses the test policy and missing lookup credentials never cause fallback. No controlled run or account was provisioned during preparation.

## Decisions that must precede hosting

The internal VM is selected for a future approved Launchpad cutover at `lesliec.ccaurora.edu/`. Archive the older assistant and preserve `itsupport` unless separately retired. Authentication configuration, retirement/cutover authorization, learner-record retention, operational ownership and actual mentor assignments remain unresolved:

- AD owner approval of bare directory host, verified LDAPS 636/CA trust, UPN domain/search base, use of the [ADUC-verified group DN](ad_authentication.md#identity-eligibility-and-enrollment) for Launchpad eligibility and its direct-or-nested policy, stable identity namespace UUID and designated test subjects. The user's confirmed membership does not enroll them or authorize other members. Approve the read-only lookup-account proposal, scope/rotation and revalidation interval before provisioning credentials. Enrollment uses namespace issuer plus immutable objectGUID, never matching email, UPN or display name. No OIDC registration is required in AD mode.
- Approval to archive/retire the older assistant at `lesliec`, install the reviewed new service and change only the intended vhost names during the approved window. Preserve `itsupport` and its failed-backend baseline unless separately retired; verify archive restore, TLS renewal and durable storage/recovery first. Follow the mandatory VM systemd/nginx plan; `render.yaml` and `scripts/start_pilot.py` remain **synthetic-only**.
- Named operators authorized to provision/revoke accounts, independently verify any historic-record mapping, maintain secrets and recover storage. CCA has confirmed **read-only mentor review of explicitly assigned learners**. Neither mentor nor admin label gets global learner access, progress editing, impersonation, account administration in the web UI, or readiness-signoff powers. Confirm the authorized operators, roster and actual learner assignments before enrollment; the read-only scope itself is decided.
- Approved fields, minimum display label, legal/organizational basis for training records, learner notice, retention/deletion rules, and who may read assessment answers, work-style signals, help text and practice drafts. Real identity does not authorize entering credentials, live incident details or sensitive internal procedures in free text.
- Named offboarding owner and maximum accepted end-to-end removal delay. AD mode proposes positive eligibility caching for 60 seconds (configurable 1–300), then GUID lookup on the next protected request; a due denial/error revokes all local sessions for that account. Include AD replication/in-flight/network limits and an emergency local-disable procedure. OIDC mode remains manual institutional-to-local revocation; it has no directory synchronization.
- Backup frequency, retention, encrypted off-host destination, recovery-point/recovery-time targets, backup custodian and an incident/support owner. These are decisions, not values silently chosen by this repository.

The AD candidate uses a verified directory bind, not local password storage or password management. OIDC remains available only as an explicit separate backend, with its documented RS256/PKCE-S256/`client_secret_basic` and issuer-origin constraints. Neither backend falls back to the other on failure. Actual browser login/logout, disabled/nonmember denial and lifecycle checks against the approved identity system remain required; isolated fixtures do not prove that integration.

## Runtime and persistent storage

Use the pinned WSGI and established identity-client dependencies in `requirements-real.txt` and the exact Python version in `.python-version` as the candidate runtime. Build with:

```bash
pip install -r requirements-real.txt
PYTHONDONTWRITEBYTECODE=1 python -B scripts/check_all.py
```

The real dependency set includes ldap3 for the AD candidate and Authlib for the optional OIDC backend. The existing Gunicorn configuration runs one synchronous worker and excludes addresses, URL/query strings, credentials and answers from access logs. One service instance is the supported SQLite deployment boundary; do not use multiple replicas or ephemeral filesystems. No identity account or resources have been created.

Choose a dedicated persistent directory outside the source checkout and ordinary temporary storage. Examples below use `/var/lib/launchpad`, which must already be a private, writable **persistent mount**. Operators must verify its actual lifecycle on the approved host. Set restrictive permissions/umask, restrict shell and backup access, and monitor capacity and lock errors. Do not attach real traffic to the development server.

Real mode requires explicit configuration and an already provisioned database. It must refuse missing configuration, demo/pilot mode, missing data, an unrecognized schema or the default prototype database. It never silently creates replacement records during a restart. Ordinary/demo startup also refuses a database containing real-user account tables or a real-data marker, so a missing mode flag cannot expose that dataset through the development routes. The provider-specific build, WSGI startup, proxy handling, TLS and mounted-disk retention remain acceptance checks.

Use the [VM environment example](../deploy/vm/launchpad.env.example) and [mandatory systemd unit](../deploy/vm/launchpad.service) for the selected internal VM. The [generic environment example](../deploy/staging.env.example) is a non-VM reference, not this VM's installation file. Examples are not loaded automatically and empty secrets deliberately prevent startup. Apply approved values through the restricted service configuration.

Required settings:

| Setting | Meaning |
| --- | --- |
| `LAUNCHPAD_REAL_MODE=1` | Enforce authenticated accounts and scoped authorization. |
| `LAUNCHPAD_DEMO_MODE=0`, `LAUNCHPAD_PILOT_MODE=0` | Explicitly disable selectable personas/shared invitation mode. |
| `LAUNCHPAD_DATA_DIR` | Existing canonical absolute persistent directory. |
| `LAUNCHPAD_DB_PATH` | Canonical `.sqlite` file directly inside that directory, provisioned explicitly. |
| `LAUNCHPAD_SECRET_KEY` | Stable random signing secret of at least 32 characters, separate from identity credentials. Rotate after restore or suspected exposure. |
| `LAUNCHPAD_TRUSTED_HOSTS` | `lesliec.ccaurora.edu` for the approved future cutover; exact host, not a wildcard/URL. |
| `LAUNCHPAD_AUTH_BACKEND` | `ad` for this candidate; no implicit fallback to OIDC. |
| `LAUNCHPAD_AD_SESSION_POLICY` | `revalidate` for production (also the default); `start_real.py` rejects the separate `controlled_test` policy. |
| `LAUNCHPAD_AD_*` | Explicit endpoint on port 636, trust/domain/base/group/policy/namespace and proposed private lookup credentials; exact required keys in [AD configuration](ad_authentication.md#candidate-configuration). |
| `LAUNCHPAD_AD_REVALIDATE_SECONDS` | Proposed 60; owner-approved 1–300 seconds, with documented outage/replication limits. |
| `LAUNCHPAD_AD_STATE_PATH` | `/var/lib/launchpad/ad-security.sqlite`, explicitly initialized persistent throttle state, separate from learners. |
| `LAUNCHPAD_OIDC_*` | Required only if separately choosing `oidc`: approved issuer, client ID/secret and exact `https://lesliec.ccaurora.edu/auth/callback`. See the optional [OIDC checklist](sso_registration_checklist.md). |
| `GUNICORN_CMD_ARGS` | Supplied by the VM unit: `--bind=unix:/run/launchpad/gunicorn.sock --umask=0o117 --worker-tmp-dir=/run/launchpad`. Do not override in the environment file. |
| `PORT` | Non-VM default only: generic Gunicorn startup uses 10000. Do not copy this setting into the VM environment; its required unit overrides the TCP bind with the private Unix socket. |

The VM unit invokes `python -B scripts/start_real.py` with the protected Unix-socket configuration; do not start the generic TCP defaults as the VM service. Its dependency and configuration checks precede opening data; the application validates existing real-user storage and does not initialize it. Installation/start remain separately authorized operator steps in the VM runbook.

Keep secrets out of shell history, source, logs, screenshots and browser-test evidence. A provider rollback may reinstate old settings; inspect auth flags, allowed hosts, secrets and database paths before reopening. Disable automatic deployment until the owner authorizes a specific tested release. Document source revision and all configuration-version identifiers without copying secret values.

## New dataset and account provisioning

**The recommended first real-user release starts with an empty, separate database.** Preserve every prototype/synthetic database. Run the following only after approving the persistent location and record policy:

```bash
python scripts/manage_real_data.py initialize --db /var/lib/launchpad/learners.sqlite
python scripts/manage_real_data.py verify --db /var/lib/launchpad/learners.sqlite
python scripts/manage_real_data.py initialize-ad-state --path /var/lib/launchpad/ad-security.sqlite
python scripts/manage_real_data.py verify-ad-state --path /var/lib/launchpad/ad-security.sqlite
```

Learner initialization refuses existing paths, sidecars, symlinks and the default prototype database. It creates base progress tables plus account/assignment/session/audit tables and a versioned real-data marker. It does not seed learners or infer identity from existing names. AD state initialization is separate and contains no learner records. New files use mode `0600`. Both are explicit offline operator actions, never web requests or app-startup side effects; missing/corrupt established state must fail closed.

Enroll each verified immutable identity in the restricted operator shell. The command prompts for subject and display label without echo so they do not enter shell history. Use a label consistent with the approved minimization policy. It creates a **new** learner record even if another learner has the same display label:

```bash
python scripts/manage_real_data.py enroll --db /var/lib/launchpad/learners.sqlite \
  --issuer urn:launchpad:ad:APPROVED_NAMESPACE_UUID --role learner
```

`APPROVED_NAMESPACE_UUID` is a placeholder; substitute the approved stable lowercase UUID and enter the independently verified canonical objectGUID subject in the private prompt. Never paste real mappings here. An authenticated but unenrolled identity must receive no learner records. OIDC uses its separately verified issuer/subject; no automatic conversion exists. Provision an authorized mentor/admin account with the matching role, then grant the confirmed read-only access to each intended learner explicitly:

```bash
python scripts/manage_real_data.py grant-mentor --db /var/lib/launchpad/learners.sqlite \
  --account-id APPROVED_ACCOUNT_ID --learner-id APPROVED_LEARNER_ID
python scripts/manage_real_data.py revoke-mentor --db /var/lib/launchpad/learners.sqlite \
  --account-id APPROVED_ACCOUNT_ID --learner-id APPROVED_LEARNER_ID
python scripts/manage_real_data.py disable-account --db /var/lib/launchpad/learners.sqlite \
  --account-id APPROVED_ACCOUNT_ID
```

The identifiers above are placeholders. Keep mapping/approval records outside the repository in an approved restricted location. Operator filesystem access is a privileged boundary, not a learner-facing feature. The audit table records event/target IDs, not comprehensive read access or human attribution for offline commands; obtain the institution's acceptance of that scope. AD due-check denial/error revokes all local account sessions as described in [lifecycle handling](ad_authentication.md#session-lifecycle-and-removal); OIDC institutional disablement/group removal still requires the named operator's local revocation within the approved delay. Test emergency local disablement and local mentor-grant removal in both modes. Logout rejects copied-cookie replay. Default session ceilings are eight hours absolute and thirty minutes idle; changing identity issuer invalidates old-issuer sessions. Logout is application-local, not Windows/upstream global logout.

## Historic-record migration plan — requires separate review

Do **not** automatically assign older records by display name or email. Names are neither unique nor proof of ownership. Do not repurpose a synthetic demo dataset as real progress. No existing database has been migrated by this work.

The current CLI cannot rebind an already-owned OIDC learner to a new AD account. Fresh AD enrollment creates a new learner; carrying such existing progress forward requires separately reviewed migration tooling on a verified copy. Do not rewrite issuer/subject fields or bypass unique ownership constraints as an operational shortcut.

1. Inventory historic records with authorized custodians, using restricted tools; determine whether they are synthetic, real and authorized for retention, or unverifiable. Record consent/authority and retention decisions outside this repository.
2. Close writes, make a consistent SQLite backup, record checksums and candidate schema, and retain the original untouched. Work only on a new restricted migration copy; never run account initialization directly on the original.
3. Review schema compatibility and use `init_accounts_schema(copy, allow_existing_records=True)` only as an explicitly authorized migration step. A migration also needs the reviewed real-data metadata/version and validation; the ordinary initialization CLI deliberately cannot adopt an old database. Prepare and test this migration for the actual source schema once it is known. Do not invent a marker on unreviewed data merely to pass startup.
4. Independently verify each `issuer` + immutable `subject` → numeric learner ID mapping. Uncertain, duplicate or unclaimed records stay unbound and inaccessible; identical names must never trigger merging. Review assessor notes/help text/role signals before granting access. `bind_existing_learner(..., migration_reviewed=True)` and the guarded `bind-existing --migration-reviewed` command support a reviewed explicit mapping, not discovery or automatic matching.
5. On the copy, compare record counts and representative scores/completions to the retained source, test unauthorized and cross-learner requests, test assigned/unassigned mentor access and test duplicate-name identities. Document exceptions without exposing content.
6. Rehearse rollback to the unchanged original **offline**, and recovery to another copy of the new schema. Approve the mapping and retention outcome before pointing a real-user service at the migrated copy. The old unauthenticated app is never a public rollback target.

A first release can avoid historic migration by starting fresh while preserving the source securely, provided the owner approves that learner experience. A need to preserve older real progress must be resolved before release; it is not a reason to guess ownership.

## Off-host backups and restore verification

Retention periods remain CCA decisions. The [policy template](../deploy/retention-policy.example.json) leaves them unset and is not consumed by the app: there is no purge scheduler or automatic record deletion. Expired/revoked sessions remain stored; UI history limits do not prune records. Approve the operational enforcement process and backup/log retention separately before real training.

Back up before deployments or account/schema changes and at the approved interval. Local snapshots alone do not survive disk, account or region loss. Configure and monitor an approved scheduled off-host process; the CLI does not install a scheduler, transport, encryption service or retention pruning.

```bash
python scripts/manage_real_data.py backup \
  --source /var/lib/launchpad/learners.sqlite \
  --destination /var/lib/launchpad/backups/release-001.sqlite
sha256sum /var/lib/launchpad/backups/release-001.sqlite
```

Create the restricted backups directory first. Every destination must be new. The tool opens the source read-only and uses SQLite's consistent backup API, including committed WAL changes. It checks the recognized real-user schema, integrity and relationships. Backups include learner answers, identity mappings, mentor grants, server sessions and access-audit records: handle the entire file as restricted learner information. Transfer only the snapshot through approved secure transport to encrypted off-host storage, verify its SHA-256 there, and restrict restore access. Do not use a raw copy of an active SQLite file as the backup procedure.

AD mode additionally needs a consistent restricted snapshot of `ad-security.sqlite`, its configuration/namespace and secret-custody references. The learner `backup` command validates learner schemas and is **not** a throttle-state backup command. Use the approved SQLite backup procedure or a verified quiesced copy for that separate store; never raw-copy it while active. Its HMAC keys derive from the signing secret. After signing-key rotation or loss/stale restoration of throttle state, keep **all login admission closed for at least 300 seconds** before reopening, then verify global/per-user limits. This is an operator recovery gate, not an automatic sleep or reset implemented by the CLI.

For a restore drill and an actual recovery:

1. Close learner traffic. Preserve the failing database and restricted operational evidence. Record expected backed-up test scores/completion and the intentionally later change that should be absent after recovery. Retrieve an authorized off-host backup and verify its checksum.
2. Restore into a **new** filename; source and active database stay untouched:

   ```bash
   python scripts/manage_real_data.py restore \
     --source /var/lib/launchpad/backups/release-001.sqlite \
     --destination /var/lib/launchpad/restored-001.sqlite
   python scripts/manage_real_data.py verify --db /var/lib/launchpad/restored-001.sqlite
   ```

3. Restore revokes all application sessions in the **new** copy. Rotate the application signing key as well, leave traffic closed, and review/reapply all account disables and mentor-grant removals since the snapshot. Reconcile against current directory/IdP eligibility. Restore/verify AD throttle state separately, preserve the namespace, and apply the closed-login recovery gate of at least 300 seconds after rotation/loss/stale-state recovery; never silently reset limits and reopen.
4. Point `LAUNCHPAD_DB_PATH` to the restored file, preserve the persistent directory, run the same validated application release and start through `scripts/start_real.py`. If the schema is incompatible with a rollback build, use its separately verified compatible backup in a new path; do not drop tables or rewrite the retained database to force compatibility.
5. In fresh authenticated sessions using designated test accounts, verify exact backed-up score/completion, learner separation, denied old cookies and revoked accounts, assigned mentor access and denial for other learners. Save new progress, restart the actual hosted process and verify it again. Confirm logs contain no tokens, submitted answers or identifiers beyond the approved operational policy.
6. Record recovery duration, lost interval, checksums, restored candidate, identity configuration version and backup owner. Resume real traffic only when the owner accepts the evidence. Treat ordinary code rollback and data restore as separate operations.

## Release checklist and stop conditions

Before real learners, record all of the following against the actual hosted candidate:

- Actual approved AD bind, TLS-failure/wrong-password/disabled/nonmember denial, GUID enrollment, periodic lookup/removal/outage behavior, persistent attempt limits and emergency local revocation; unenrolled identity denial, logout/replay, learner A/B separation and duplicate-name separation. If OIDC is chosen instead, verify its actual registration/state/nonce/code and separate offboarding policy.
- Learner selector and submitted learner IDs cannot alter attribution; direct endpoint calls cannot bypass it. Mentors/admins can read only assigned learners and cannot write their progress or gain new grants through HTTP.
- Complete learner assessment, module/quiz, checklist and guided activity using designated test accounts. Record exact score/completion, navigate/reload, restart the hosted process, and verify durable state. Scoring/curriculum/completion rules remain unchanged.
- Verify HTTPS-only ingress, exact trusted hosts, secure cookies, CSRF, safe errors and restricted logs. Test the provider's private source settings and account permissions. Confirm disk mount, disk capacity monitoring, backup schedule, successful off-host checksum and full restore drill.
- Firefox and a second browser; 375/768/1440px layouts; keyboard-only navigation/forms/disclosures/lab, visible focus, screen-reader labels/errors/results, and 200% zoom. This environment has not supplied a browser or screen reader; HTTP and HTML tests do not verify those behaviors.
- Authorized learner/mentor acceptance, named support/incident owners, learner notice and approved retention. Check whether the simplified interface improves task completion and perceived density; no such user evidence is inferred from test counts.

Stop access on cross-learner exposure, unexpected grants, authentication bypass, lost progress, broken recovery or repeated storage/server failures. Preserve restricted evidence, revoke sessions when indicated and notify the named owner through approved channels. Do not add features to address missing organizational decisions. Keep scope focused on authentication, authorization, reliable progress and release QA.

## Protocol and hosting references

- [OpenID Connect claim stability](https://openid.net/specs/openid-connect-core-1_0.html#ClaimStability): use issuer and subject as the account key.
- [Authlib Flask integration](https://docs.authlib.org/en/latest/oauth2/client/web/flask.html): established client implementation for authorization-code/OIDC processing.
- [OAuth security best current practice](https://datatracker.ietf.org/doc/html/rfc9700#section-2.1.1): code-flow and PKCE protections.
- [Flask production deployment](https://flask.palletsprojects.com/en/stable/deploying/): use a production WSGI server behind the approved host's TLS ingress.
- [Browser `form-action` behavior](https://developer.mozilla.org/en-US/docs/Web/HTTP/Reference/Headers/Content-Security-Policy/form-action): redirect handling differs; actual Firefox and second-browser sign-in are release requirements.

## Schema version 2 and the sign-in session policy (2026-10-22)

Release code expects real schema version 2 (`stuck_reports.resolved_at`). A version-1 database refuses startup; it is never upgraded in place. Run `manage_real_data.py migrate --source <v1 file> --destination <new file>` against a consistent snapshot, then `verify` the new file and point configuration at it. The source is unchanged and existing help requests start Open. Restoring an older version-1 backup follows the same path, followed by `revoke-sessions` on the new file. `LAUNCHPAD_AD_SESSION_POLICY=signin` is accepted by `start_real.py`; see [the regular-use release plan](regular_use_release.md) for its access-removal trade-off and the deployment sequence.
