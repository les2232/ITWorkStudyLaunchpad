# CCA staging proposal

> Current VM preparation (2026-10-08): Plan a future approved cutover of `lesliec.ccaurora.edu/` from the archived older assistant to Launchpad; preserve `itsupport` unless separately retired. The candidate uses verified LDAPS with explicit GUID enrollment, pending directory/lookup-account and lifecycle approval. No live directory access, retirement, deployment or routing change has occurred. Use [VM deployment](vm_deployment.md), [AD authentication](ad_authentication.md), [sysadmin decisions](vm_sysadmin_handoff.md) and [current validation](vm_verification.md). Historical OIDC test results below do not establish AD or hosted acceptance.

Updated 2026-10-08. The current preparation is the internal VM with future Launchpad routing at `lesliec.ccaurora.edu/`, verified AD authentication and explicit learner ownership. No deployment, archive, live directory bind or routing change has occurred. Mentor access remains read-only for assigned learners; feature scope is frozen.

## Selected staging shape

Use one non-root Launchpad service instance, the current Flask/Jinja application, one Gunicorn worker and dedicated persistent SQLite storage. The mandatory [VM systemd unit](../deploy/vm/launchpad.service) supplies the protected Unix socket. The [VM plan](vm_deployment.md) defines future retirement/archive of the older assistant and transfer of only `lesliec`; preserve `itsupport` unless separately retired. Do not restart the known failed old backend as a fallback.

Acceptance uses designated CCA accounts, a new database and invented training responses while invitations remain closed. This tests real-user authentication and persistence without adopting synthetic answers as real training progress. Keep test mappings/configuration separate from any later approved production dataset. The selected AD lookup option is prepared only: CCA account availability, exact permissions, directory trust/group policy and the configurable proposed 60-second lifecycle interval remain unapproved. [AD details](ad_authentication.md).

## Hosting contract

| Requirement | Concrete value / acceptance |
| --- | --- |
| Runtime/build | `.python-version` proposes 3.12.15; available VM validation uses 3.12.3. Install `requirements-real.txt`, then run `PYTHONDONTWRITEBYTECODE=1 python -B scripts/check_all.py` as non-root with isolated data/sockets/subprocesses. Validate the exact final runtime. No frontend build is required. |
| Startup/proxy | The mandatory VM unit runs `scripts/start_real.py`, one worker, `unix:/run/launchpad/gunicorn.sock`, strict umask and no public backend TCP listener. Nginx serves fixed `lesliec` HTTPS at `/` only after approved cutover, with sanitized headers/logs. |
| Identity network | Verify browser HTTPS/campus-VPN access and service-to-approved-DC LDAPS 636 with hostname/CA validation; maintain accurate time. No OIDC registration/callback is needed in AD mode. OIDC remains an optional separately reviewed backend. |
| Durable state | Private `/var/lib/launchpad/learners.sqlite` plus `/var/lib/launchpad/ad-security.sqlite`, outside the checkout. Explicit new-file provisioning; no missing-state reseed. Preserve SQLite sidecars and verify actual VM-disk durability, capacity and locking. |
| Configuration/secrets | Root-private `/etc/launchpad/launchpad.env`, separate random signing secret and privately approved lookup credential. Public directory CA at a root-owned app-readable path. Never copy the older assistant's environment or secret. |
| Authorization | Explicit namespace/GUID enrollment, learners' own records only, assigned-only read-only mentors. No group-derived role, name matching or automatic account creation. |
| Lifecycle | Lookup option selected for preparation, not provisioned. Proposed 60 seconds, configurable 1–300; due lookup error/denial revokes all local sessions for that account. Owner approves delay including replication/in-flight/network limits and emergency local disablement. |
| Operations/recovery | Named owners, consistent snapshots of both stores, encrypted off-VM retrieval/checksum/restore and monitored failures. Preserve namespace, revoke copied sessions/reconcile eligibility and rotate signing keys. Rotation/lost-or-stale throttle state requires at least 300 seconds of closed login admission before reopening and testing limits. |
| Logs/probes | Safe app journal and sanitized nginx method/status/duration. No raw directory responses, passwords or callback query logs. `/auth/login` is only liveness, not proof of identity, record access or recovery. |
| Capacity | One instance is the SQLite boundary. Measure the intended small cohort's simultaneous work, lock/errors and disk growth; no production sizing or availability claim is made. |

Use a production WSGI service, not Flask's development server. [Flask deployment guidance](https://flask.palletsprojects.com/en/stable/deploying/). The generic [staging env reference](../deploy/staging.env.example) is not this VM's install file; use [the VM example](../deploy/vm/launchpad.env.example) with its required unit.

## Historical Render comparison — not the selected host


**Not as checked in.** Review based on `render.yaml`, `scripts/start_real.py`, `deploy/gunicorn.conf.py` and official documentation checked 2026-10-07:

| Area | Prepared configuration / result |
| --- | --- |
| Build and interpreter | Full pinned dependency/test build is present. Render supports `.python-version`; actual build on that interpreter remains unverified. [Python version selection](https://render.com/docs/python-version) |
| Authentication | **Fails the real-user requirement:** starts `scripts/start_pilot.py`, sets demo/pilot mode to `1`, configures a shared invitation and has no individual real-mode identity configuration. Installing Authlib during build does not change this. |
| Disk / scale | One instance and 1 GB synthetic disk are declared. Render requires paid disk-capable compute; only mounted files persist, and a disk limits the service to one instance. Real data needs its own approved mount and capacity decision. [Disks](https://render.com/docs/disks) |
| First initialization | **Incomplete:** normal real startup refuses a missing database. Disks are unavailable in build/predeploy/one-off jobs; ordinary SSH needs a running instance. A failed first deploy cannot be solved by assuming a shell with the volume will be available. [Disks](https://render.com/docs/disks), [SSH](https://render.com/docs/ssh) |
| Domain / edge | Render can manage custom-domain TLS and HTTPS redirects. CCA must approve the exact staging domain and public-versus-restricted ingress; a private source connection does not make the website private. [Domains](https://render.com/docs/custom-domains) |
| Region / access | The manifest does not select an approved region or define CCA operational ownership. Choose the region before creation; Render does not support an in-place region change. [Regions](https://render.com/docs/regions) |
| Operations | Automatic deployment is off, but no off-host backup job, operator roster, alerts, retention policy or verified recovery is configured. Disk-backed deploys have downtime. [Deploy lifecycle](https://render.com/docs/deploys) |
| Readiness probe | No application readiness endpoint is declared. Render's default TCP check detects a listening process, not successful authentication or record writes. Use the acceptance checklist separately. [Health checks](https://render.com/docs/health-checks) |

Render's own disk snapshots are not the application's tested SQLite recovery procedure. Keep the consistent backup/new-file restore workflow and an approved off-host copy. [Database recovery caveat](https://render.com/docs/disks)

If Render is chosen, prepare a **separate** real-user configuration and explicitly authorized first-provisioning procedure. That procedure must validate the runtime mount/configuration, durably record that first provisioning was attempted, create only a new database and refuse retries/reseeding after data loss. Switch permanently to `start_real.py` after provisioning. This host-specific bootstrap is **not implemented or hosted-tested**; do not place an unconditional initializer in steady-state startup or the build. CCA-hosted offline volume provisioning avoids this particular first-start problem. No new Render manifest is presented as deploy-ready.

## Proposed sequence after owner decisions

1. Approve the old-app archive/retirement boundary, `lesliec` cutover/window and safe rollback; preserve `itsupport` unless separately retired. Name certificate, directory/group/lookup, service and recovery owners.
2. Complete [AD decisions](ad_authentication.md) and [sysadmin handoff](vm_sysadmin_handoff.md), including minimum lookup permissions, account availability, interval/outage policy and stable namespace. Supply secrets only through approved private custody; no OIDC registration is required.
3. Approve minimum learner information, retention and backups through [the policy inventory](learner_data_policy.md). Create no automatic mappings from old OIDC/prototype/assistant records.
4. After explicit deployment authorization, archive/verify the old app, build/test the exact runtime, provision both NEW stores and install the dedicated VM service/configuration.
5. Enroll A/B and a mentor assigned only to A. Verify live AD, unauthorized requests, lifecycle failures, login limits, exact scoring/completion persistence and off-VM recovery. Then perform the reviewed nginx cutover and [hosted/browser matrix](staging_verification.md) while invitations remain closed.
6. Record owner acceptance before real training. Use a separate approved production dataset or only an independently reviewed migration; preserve originals and frozen feature scope.

## Local evidence and limits

The dated 2026-10-07 OIDC candidate recorded 210 passing tests and local HTTPS/Gunicorn restart, scoring/completion, isolation and session-revocation evidence. Those results do not prove the new AD implementation, CCA directory integration or hosted acceptance. Current candidate results are recorded in [VM verification](vm_verification.md); do not infer a new pass from this historical count. No real institution credential, hosted recovery, rendered browser, screen reader or user study has been verified by this document.

The exact next step is Michael/directory-owner confirmation of the restricted lookup identity, CA/host/search/group/namespace and acceptable delay, alongside certificate renewal and archival/cutover ownership. Local preparation does not authorize directory access, service changes or invitations.
