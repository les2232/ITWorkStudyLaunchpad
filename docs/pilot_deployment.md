# Deployment decision record — real-user release candidate

> Current VM preparation (2026-10-08): Plan a future approved cutover of `lesliec.ccaurora.edu/` from the archived older assistant to Launchpad; preserve `itsupport` unless separately retired. The candidate uses verified LDAPS with explicit GUID enrollment, pending directory/lookup-account and lifecycle approval. No live directory access, retirement, deployment or routing change has occurred. Use [VM deployment](vm_deployment.md), [AD authentication](ad_authentication.md), [sysadmin decisions](vm_sysadmin_handoff.md) and [current validation](vm_verification.md). Historical OIDC test results below do not establish AD or hosted acceptance.

Updated 2026-10-08. **Nothing has been deployed. Real learners must not be invited yet.** The first release requires individual authenticated accounts and private saved progress; shared invitations and selectable personas remain synthetic-only.

## Selected preparation and remaining decisions

Prepare Launchpad for the internal Linux VM, with its own service, Unix socket, configuration, secrets and SQLite records. The future root-path hostname is `lesliec.ccaurora.edu`; archive the complete older assistant and retain original code/databases before the separately authorized cutover. Preserve `itsupport` unless its owner separately retires it. Existing old service failure is the rollback baseline, not proof of a working application to restart. Follow [VM deployment](vm_deployment.md).

The user selected preparation of verified **AD LDAPS 636** with an approved read-only lookup account for periodic eligibility checks. The user's ADUC observation confirms group existence, exact DN and their own membership; both prepared examples use that DN. Lookup-account availability, host/CA/search settings, Launchpad eligibility approval and membership policy for the observed group, exact lookup permissions and acceptable removal delay remain unconfirmed. Proposed revalidation is 60 seconds, configurable 1–300; directory replication, in-flight requests and network checks limit the observed delay. Lookup failure when due denies access and revokes that account's local sessions. Learner passwords are not retained for rechecks. [AD evidence, design and minimum permissions](ad_authentication.md).

Mentors read only explicitly assigned learners. Group membership authenticates eligibility, never local role/record ownership. Enrollment uses the approved namespace issuer and immutable AD objectGUID. Existing OIDC/prototype/older-app records are not automatically matched or rebound. Fresh records are the default candidate; any historic migration needs a separately reviewed copy and mapping plan.

Still required: cutover/archive/rollback owners and window, certificate renewal/key match, live AD verification, lookup-account provisioning, group/lifecycle approval, record/retention policy, mentor assignments, backup/restore ownership and browser/user acceptance. Preparing files does not authorize service installation, directory binds, source upload or deployment.

## Release files and mode boundaries

| File / mode | Purpose and boundary |
| --- | --- |
| `requirements-real.txt` | Pinned Flask/Gunicorn, ldap3 and Authlib dependencies; build the full candidate without changing the existing service environment. |
| `.python-version` | Candidate Python 3.12.15; local VM interpreter 3.12.3. Accept the exact deployed runtime only after its checks pass. |
| `deploy/vm/launchpad.service` | Mandatory VM entrypoint: non-root dedicated identity, `scripts/start_real.py`, protected Unix socket, private state and no automatic database initialization. |
| `deploy/vm/launchpad.nginx.conf` | Future approved `lesliec` cutover only, fixed host/TLS/proxy headers and sanitized logging; never enable beside the old duplicate hostname. |
| `scripts/manage_real_data.py` | Restricted offline learner initialization, explicit enrollment/grants, revocation and consistent learner snapshot/new-file restore; separate `initialize-ad-state`/`verify-ad-state` commands. |
| `launchpad/ad.py`, `real_auth.py`, `accounts.py` | Verified AD identity, request authorization, explicit account/session/assignment mapping and scoped roles. No local password database or automatic record claiming. |
| Optional OIDC backend | Existing Authlib client remains available under its explicit mode and separate enrollment/lifecycle. The [OIDC checklist](sso_registration_checklist.md) is not required for AD mode. |
| Ordinary/demo/shared-pilot mode | Invented data only, including `render.yaml` and `scripts/start_pilot.py`. Not a real-learner release or rollback path. |

## Build, storage and operations

Build the reviewed release with:

```bash
pip install -r requirements-real.txt
PYTHONDONTWRITEBYTECODE=1 python -B scripts/check_all.py
```

The full suite uses isolated temporary data, loopback sockets and subprocesses. Do not point it at real records. The selected VM starts through the mandatory systemd unit, whose `GUNICORN_CMD_ARGS` binds only `unix:/run/launchpad/gunicorn.sock`; generic TCP startup defaults are not this VM's service configuration. No Node/frontend build or database-engine replacement is needed.

Explicitly provision both new private stores on verified durable storage: `learners.sqlite` and `ad-security.sqlite`. Missing configuration/data/security state must fail closed rather than reseed. Store the separate signing/lookup secrets in the approved root-private configuration, and place the public directory CA where the non-root app can read it. Use [real-user operations](real_user_operations.md) for exact settings, enrollment, backups and restore.

The learner backup command does not back up the throttle schema. Preserve both consistently, encrypt off-VM copies and verify retrieval/checksums/restore. Signing-key rotation changes per-user HMAC throttle keys; after rotation or lost/stale state recovery, keep login admission closed for at least 300 seconds, then test both limits before reopening. This is an operator gate, not automatic CLI behavior.

## Before traffic and rollback

1. Record owners' AD/lookup/group/lifecycle, record handling, certificate and archive/cutover decisions; finish the restricted old-app archive and isolated restore proof.
2. Under separate deployment authorization, build the exact runtime, provision both new stores, install the dedicated service and verify its restricted Unix-socket/storage configuration.
3. With designated accounts, prove actual LDAPS validation, allowed/disabled/nonmember/unenrolled behavior, GUID enrollment, scoped mentor access, logout/replay, removal/outage behavior and persisted login limits.
4. Cut over only the approved `lesliec` routing, preserve `itsupport`, and verify exact scoring/completion through reload and hosted restart; perform encrypted off-VM recovery including both state stores.
5. Complete Firefox/second-browser, 375/768/1440px, keyboard/screen-reader, 200% zoom and intended-user acceptance before invitations. [Hosted matrix](staging_verification.md).

On a blocker, close Launchpad access or use the approved maintenance response. Routing rollback may restore the archived vhost only with the recorded failed/disabled old service state. Never automatically restart the old assistant: its historical startup errors and later conditional LDAP transport gaps require separate hardening/approval before active restoration. Keep all originals and learner records; a failed cutover never authorizes deletion or pointing old code at Launchpad data.

For later Launchpad rollback, use a tested compatible authenticated release/configuration. Restore data to a new file, revoke copied sessions, rotate keys and reconcile current eligibility/grants before reopening. Current local results are maintained in [VM verification](vm_verification.md); they do not establish hosted authentication, recovery or accessibility.

## Historical hosting comparison

Render was researched for the earlier synthetic pilot and is not the selected or approved real-record host. The dated 2026-10-07 comparison in [staging proposal](staging_proposal.md) records its paid-disk, single-instance, ephemeral-outside-mount and first-provisioning constraints. Do not treat that historical research or the synthetic manifest as a current deployment authorization. Any change of host requires renewed provider verification and owner approval.
