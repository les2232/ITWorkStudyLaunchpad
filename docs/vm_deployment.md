# Internal Linux VM deployment change proposal

Updated 2026-10-09. **The operator has authorized certificate permission remediation and activation of the isolated controlled test using the current certificate, following Michael's approval. Privileged shared changes remain pending: noninteractive sudo is unavailable in this session. The application is not accepted for production training.** See the [current activation record](vm_verification.md#controlled-test-activation-authorization-2026-10-09) for executed results and remaining work. CCA selected its internal Linux VM for this preparation; Render is no longer the proposed host. Keep curriculum, scoring, completion, account mapping and assigned-mentor permissions unchanged. The [controlled browser route](#controlled-browser-test-routing) is a separate, supervised 15-minute-session test proposal; it does not install the production service below.

## Verified connection and existing services

The session runs as non-root `lesliec` (UID 1000) on Ubuntu 24.04.4, OS hostname `ccadlnxweb09`. Its local address is `10.117.1.127`, and this VM's resolver maps `lesliec.ccaurora.edu` to that address. This matches the supplied server; another SSH connection is not needed for the present session. CCA must still verify learner access from campus/VPN. Internal DNS alone does not establish a firewall/access boundary.

Nginx 1.24 and systemd 255 are present. Nginx is already active on IPv4/IPv6 ports 80 and 443. The enabled `/etc/nginx/sites-enabled/cca-it-support-assistant` configuration claims **both `lesliec.ccaurora.edu` and `itsupport.ccaurora.edu`** on HTTP and HTTPS; a default HTTP site also exists. No Launchpad-named service was found during the scoped inspection. No unrelated configuration or logs were dumped or changed.

**The selected future plan is to retire the older assistant at `lesliec.ccaurora.edu` and serve Launchpad at the root path `/` on that hostname.** The operator has now authorized the controlled-test routing and service actions below. The current vhost already claims that name: remove it from both old HTTP/HTTPS `server_name` directives before enabling the new single-host Launchpad vhost, with validation and maintenance rollback. Never enable duplicate names. Preserve `itsupport.ccaurora.edu` and its existing upstream unless the owner separately approves retirement of that alias too. Launchpad retains its own service, Unix socket, configuration, secrets and database; the older application's files and records are archived and preserved, not repurposed.

`/var/lib` currently sits on the VM's root ext4 filesystem. That is filesystem evidence, not proof of encryption, backup coverage or survival of a VM replacement. Confirm durable virtual-disk provisioning, capacity, monitoring and recovery ownership with CCA; no VM restart was performed.

### Existing application baseline and retirement boundary

The enabled aliases above point to `127.0.0.1:8000`. The installed `cca-it-support-assistant.service` identifies `/opt/project/it-ai-agent` and its Gunicorn `app:app` entrypoint; it does not identify this Launchpad repository or the development successor `/opt/project/itSupportAssistant`. Read-only inspection found that service failed/disabled with no backend PID or port-8000 listener. The older `it-ai-agent.service` is inactive/disabled. Preserve this baseline and the original configurations in the retirement archive. Restoring the old routing would restore a failed-backend baseline, not a verified working assistant.

The latest retained startup logs end on **July 17, 2026**, not the current preparation date. At 14:24:19 UTC, validation reported three errors: local-only mode conflicted with an OpenAI API key being present; production LDAP SSL was not enabled; and LDAP port 389 was configured for cleartext operation. Gunicorn then failed worker startup and exited at 14:24:49 UTC with status 3. These fixed messages match historical source revision `51b0908`; current validation code changed later. They establish the historical failure cause, **not today's protected environment values**, which remain unreadable to this account. Do not guess or copy that application's configuration into Launchpad.

A separate source/library review also found conditional LDAP transport gaps in the older application: its server setting accepts URL-style values that ldap3 2.9.1 can interpret as scheme/port overrides, and default referral behavior can select another server and forward bind credentials. This is evidence of reachable code paths, not a tested live downgrade, referral or credential exposure. Any future restoration of that application requires separate owner approval, rejection of embedded URL schemes/ports, confirmation that the constructed server actually uses SSL/636, and disabled referrals unless an explicitly approved protected referral design is implemented, with focused regression coverage. No older-app source, authentication, protected environment, records or service settings were modified here. Do not automatically restart it as a Launchpad fallback.

### Required archive before cutover

For the authorized supervised controlled test, preserve the old source, configuration and data in place and take a restricted routing/service-definition snapshot before changing only the hostname route. Do not delete, restart or migrate the old assistant. The complete encrypted off-VM archive and restore verification below remain required before destructive retirement or general production acceptance; neither has been established by this preparation. Record that remaining recovery work separately from the narrowly authorized controlled cutover.

1. Record the existing vhost/symlink and service states, release commit, dirty worktree inventory and checksums in a restricted manifest. Confirm the actual configured SQLite path through the authorized operator, not a guessed repository default. Preserve both hostnames' observed response status as the comparison baseline.
2. Quiesce any writers through the old application's approved service/maintenance procedure and confirm no process still writes its SQLite state. The known service is failed now; recheck instead of assuming that historical state persists. Do not start it to take a backup.
3. Archive the complete recoverable `/opt/project/it-ai-agent` source/worktree, including `.git`, uncommitted changes and untracked source/content. A clean checkout or `git archive` alone misses that work. Account for ignored sensitive configuration and runtime files explicitly in the restricted inventory; do not expose them in a public code archive. Preserve originals in place. Record dependency/runtime versions and any intentional cache/virtualenv exclusions needed for a reproducible restore.
4. Make a consistent SQLite snapshot to a **new** restricted destination with the SQLite backup API/tool while writes remain quiesced, and verify the snapshot's integrity. Do not copy only a live main database file or discard its journal/WAL files. Keep original databases untouched; no old records are imported into Launchpad. The [SQLite backup API](https://www.sqlite.org/backup.html) creates a consistent snapshot, including committed data managed by SQLite.
5. Through an authorized operator, archive the actual nginx vhost/symlink targets, both old service units and any drop-ins, protected environment/configuration and their ownership/modes. Record certificate/chain/key path references, expiry and renewal owner; rely on the institution's approved key-recovery custody rather than unnecessarily duplicating a shared private key into the app archive. Never print secret values or put the archive in this repository.
6. Encrypt the archive and restricted manifest using CCA's approved method, transfer it off the VM, verify checksums after retrieval and perform an isolated restore verification with network access and production credentials disabled. Verify file inventory/permissions and SQLite integrity without exposing record contents. Rebuilding the artifact is a restore check; starting vulnerable old authentication is not required or permitted by this plan. Have the named archive owner record the verified location, retention, access controls and recovery instructions before routing changes.

Archival is preservation, not permission to delete originals or restart the old service. Any later deletion, service masking/removal or retirement of `itsupport` requires its own explicit scope and owner approval.

## Certificate findings and ownership

| Item | Read-only result |
| --- | --- |
| Leaf | `/opt/project/certs/ccaurora.cer`; SAN `*.ccaurora.edu` covers the selected `lesliec.ccaurora.edu` hostname. Confirm the actual installed/renewed certificate before cutover. |
| Actual intermediate | `/opt/project/certs/DigiCertCA.crt`: Thawte TLS RSA CA G1. |
| Actual root | `/opt/project/certs/TrustedRoot.crt`: DigiCert Global Root G2. |
| Existing served-chain file | `/opt/project/certs/fullchain.pem` contains the matching leaf and intermediate, but also a private-key marker. Treat it as a secret-bearing file, not a public-only chain; see the separate exposure finding below. |
| Chain/purpose/hostname | `openssl verify` passes using the supplied root and, separately, the VM system trust bundle, with server purpose and the existing `lesliec.ccaurora.edu` hostname. This does not establish revocation status or every learner device's trust. |
| Live TLS / ordinary request | Rechecked 2026-10-09: this VM resolves `lesliec.ccaurora.edu` to `10.117.1.127`; a bounded connection validates hostname and chain using system trust with TLS 1.3. The served leaf matches the on-disk public certificate. An unauthenticated `GET /auth/login` returns **502 Bad Gateway** from the existing route. This establishes reachable Nginx HTTPS, not a deployed Launchpad or a student's network path. |
| Expiry | **Verified October 28, 2026 at 23:59:59 UTC** (5:59:59 p.m. MDT), valid from October 29, 2025. Read from the current leaf and matched to the live served certificate. The operator reports Michael approved current-certificate reuse and is arranging renewal with Jordan next week. Exact renewal time and renewed installation remain unverified; complete renewed chain/key/hostname verification before expiry. |
| Permissions / key match | Certificate directory is root-owned 0755. `ccaurora.cer` and `fullchain.pem` are root:root 0644 and contain private-key markers; local readability is confirmed. `ccaurora.key` is root:root 0640 and unreadable by this account. No private key was parsed or compared; matching the exposed material to the deployed key remains unverified. |

No private key or certificate body was copied into the repository or report. The operator reports Michael has authorized reuse of the current certificate and moving/restricting these files on this VM, provided required consumers retain access. This authorizes the scoped remediation below; replacement issuance is not a prerequisite. Nginx's privileged master can read root-owned 0600 key-bearing files; neither its workers nor Launchpad needs that access. Keep the current paths if tightening modes suffices, avoiding unnecessary moves or new key copies. A mixed chain file remains secret-bearing even though Nginx sends only its public certificates.

An authorized certificate operator can compare **only public-key digests** locally, without printing private-key material:

```bash
openssl x509 -in /opt/project/certs/ccaurora.cer -pubkey -noout | openssl pkey -pubin -outform DER | openssl dgst -sha256
openssl pkey -in /opt/project/certs/ccaurora.key -pubout -outform DER | openssl dgst -sha256
```

Both commands must succeed and the digests must match. Use the approved terminal/prompt if the key is encrypted; never put a passphrase in a command, environment example, chat or log. The operator must also verify renewed chain/hostname/expiry, test configuration, and arrange the separately authorized reload of all affected shared TLS sites. These privileged steps have not been run here.

### Website private-key exposure and permission proposal

**Separate issue from AD CA trust.** Read-only confirmation on 2026-10-08, rechecked 2026-10-09, counted public-certificate blocks and private-key BEGIN markers without displaying, copying, parsing or transmitting key contents. No file contents, ownership, modes, certificates or service state were changed. The observation establishes local filesystem readability, not exfiltration, disclosure over HTTPS or that the detected material matches the currently used key. The current public leaf DER SHA-256 is `50236CF66452A79E4DC0D4325093F460C37DABBBCE1955998B8FC82B562FE8FD`.

| Inspected item | Result |
| --- | --- |
| `/opt`, `/opt/project`, `/opt/project/certs` | root:root, mode 0755; ordinary users can traverse these paths |
| `/opt/project/certs/ccaurora.cer` | root:root 0644; one certificate block and one private-key BEGIN marker; readable by non-root `lesliec` |
| `/opt/project/certs/fullchain.pem` | root:root 0644; two certificate blocks and one private-key BEGIN marker; readable by non-root `lesliec` |
| `/opt/project/certs/ccaurora.key` | root:root 0640; contents not read |
| ACL inspection | No POSIX ACL xattrs on the inspected parents/directory/three files; `getfacl` was unavailable |
| Live Nginx identities | Master PID 414840 root:root; four workers www-data:www-data; `/etc/nginx/nginx.conf:1` sets worker user www-data |
| Static TLS consumers | `/etc/nginx/sites-enabled/cca-it-support-assistant:14` reads fullchain.pem as `ssl_certificate`; line 15 reads ccaurora.key as `ssl_certificate_key`. Both existing hostnames use this site. |
| Old application identities | `cca-it-support-assistant.service` specifies www-data:www-data and is failed; `it-ai-agent.service` specifies root and is inactive. Neither application has an established need for the website key. |
| Prepared Launchpad | `deploy/vm/launchpad.service` specifies User=launchpad, Group=launchpad-proxy, SupplementaryGroups=launchpad. TLS terminates at Nginx; Launchpad needs only its public AD CA bundle, not a website private key. |

Readable configuration searches under `/etc/nginx`, `/etc/systemd/system`, `/usr/lib/systemd/system` and `/etc/apache2` found no other references to these shared paths; `/etc/caddy` was absent. Protected environment files and unknown renewal/backup automation were not inspected, so the consumer inventory is incomplete. Recheck service/process state in the eventual maintenance window.

**Owner-authorized scope; execution requires privileged access and recorded validation:**

1. Michael has approved using the existing production certificate until renewal, which he is arranging with Jordan next week (operator-reported confirmation on 2026-10-09). Do not request replacement as a prerequisite to this test. Recheck actual consumers and key-bearing copies, including both existing hostnames and accessible renewal/backup references. Record the historical local readability and unresolved scope of past access: it does not prove compromise, and restricting permissions does not erase it. Preserve evidence without copying key-bearing contents into the repository or chat.
2. In the approved change, restrict **every** key-bearing file, including misleading `.cer`/`fullchain.pem` names, and the standalone key to root:root 0600 after checking consumers. No group grant to `www-data`, `launchpad` or `launchpad-proxy` is required for this static Nginx configuration: its root master reads the files. If a genuine non-root consumer is found, design a narrowly scoped access arrangement with its owner first; do not use world readability or a broadly shared web-worker group.
3. Retain the shared directory's traversal permissions until public-certificate and automation consumers are reviewed; a blanket 0700 on the shared directory could break legitimate public-only reads. An eventual clean layout can use a root-owned 0700 private directory with a 0600 key and a separate root-owned 0644 public-only certificate chain. Moving files and restricting access are authorized, but the smallest change is to preserve current consumer paths and restrict all secret-bearing files; avoid a layout change unless needed to maintain safe access. Verify the chain has no private-key blocks before treating it as public.
4. Have the authorized operator test the final configuration in the actual root-master context, then perform the authorized reload and HTTPS smoke check for each affected hostname. Verify ordinary users, the older assistant's non-root `www-data` identity and Launchpad cannot open key-bearing files. The inactive alternate `it-ai-agent.service` is configured as root: these modes cannot isolate it from root-owned keys, and this proposal does not authorize starting it. Ensure renewal preserves the intended owner/modes. Record executed mode changes, privileged `nginx -t`, reload and smoke results separately; this proposal alone does not establish they succeeded.
5. Rollback may restore a reviewed working path/configuration with restrictive permissions; it must not restore world-readable key material. A failed permission plan is resolved with the identified consumer and owner, not blanket read grants or an automatic old-backend restart.

Nginx documents that static private keys must be readable by its master process, that combined certificate/key files require restricted access, and that only certificates are sent during TLS. Worker identity does not determine the necessary filesystem key grant. [Official Nginx HTTPS guidance](https://nginx.org/en/docs/http/configuring_https_servers.html), [worker user directive](https://nginx.org/en/docs/ngx_core_module.html#user).

## Active Directory authentication candidate

The candidate requires AD authentication over **verified direct LDAPS on port 636**, with configuration and release gates in [AD authentication](ad_authentication.md). Earlier credential-free checks with VM system trust failed on 636/StartTLS 389. A subsequent 15-second-bounded LDAPS check to `CCCDC01.ccc.ccofc.edu:636` **passed using the supplied Windows-store CA bundle**, including TLS 1.3, chain validation and exact hostname validation. See [fingerprints and provenance](ad_authentication.md#ad-trust-discovery-and-public-certificate-export). CCA approval and centrally managed deployment of those fingerprints remain unverified; production trust is not approved by this diagnostic. Search base, eligible group use and lookup/lifecycle policy still require approval. No live directory bind, AD change, certificate installation or credential provisioning has been performed. The diagnostic StartTLS check does not change the LDAPS-only adapter or permit a fallback, certificate bypass or referral credential forwarding. Microsoft documents the directory-server naming, trust and server-authentication certificate requirements for [LDAPS](https://learn.microsoft.com/en-us/troubleshoot/windows-server/active-directory/enable-ldap-over-ssl-3rd-certification-authority).

Existing OIDC support remains a separate explicit configuration choice; its prior enrollment is not silently converted. AD enrollment uses a stable operator-approved directory namespace UUID and the authenticated account's immutable `objectGUID`, with issuer `urn:launchpad:ad:<namespace-UUID>`. Usernames, names and email addresses are not ownership keys. Keep the namespace stable through backups/restores and do not create automatic matches to existing learner records.

On 2026-10-08 the user verified in ADUC that `CCA_Leslie_Project` exists, confirmed their own membership and read the exact DN now populated in both prepared AD examples. See [the dated observation and DN](ad_authentication.md#identity-eligibility-and-enrollment). Launchpad eligibility approval, membership ownership and direct/nested policy remain pending; the separate `CCA_IT_Testlab` listing conveys no Launchpad permission. The earlier `CCA_IT_WorkStudy_Launchpad` proposal remains unverified. A new group is not assumed necessary. If the owner chooses a different group, obtain its exact approved DN and policy; for a new group, follow CCA's supplied requirements: under CCA > CCA_Groups_Security_User, name beginning with CCA and using underscores, Security type, Universal scope, and a description. This repository preparation has not queried or modified AD or installed the example configuration.

Group eligibility and learner authorization are separate. The AD candidate must enforce the exact configured group using the approved direct/nested membership policy and reject accounts that are ineligible or disabled. The ADUC observation does not establish ownership, other members, working LDAPS or lookup-account availability. Group membership must never grant mentor/admin authority or another learner's records. Local enrollment and explicit read-only mentor assignments remain required; no directory credential can select a different learner in a form.

Directory disablement and group-removal handling require an explicit lifecycle decision and named operator. The [AD lifecycle section](ad_authentication.md#session-lifecycle-and-removal) records the candidate's selected mechanism and what remains unverified; do not infer instantaneous revocation from successful login. Approve the maximum acceptable delay, test directory outage/denial behavior and include local account disablement/session revocation in the emergency procedure. OIDC sessions remain governed by their separate documented lifecycle. App logout revokes the local session, not a Windows or upstream SSO session.

Reusing the hostname does not reuse browser identity. Launchpad uses its distinct `__Host-launchpad_session` cookie, a separate random signing secret and its own server-side account/session records. Old assistant cookies may remain in a browser but must neither authenticate Launchpad nor select a learner. Do not copy the old Flask secret, interpret its `logged_in`/username fields or broaden the cookie domain. Verify fresh-browser login, old-cookie denial, logout and copied-cookie replay during cutover QA. Flask supports a separate [session cookie name](https://flask.palletsprojects.com/en/stable/config/#SESSION_COOKIE_NAME); the application's server-side authorization remains the decisive boundary.

## Concrete change set for review — not applied

| Change | Prepared result / permission boundary |
| --- | --- |
| New application identity | Dedicated non-login `launchpad` account, private `launchpad` group and separate `launchpad-proxy` group. Verify names are unused or already approved before creation. Add only the nginx worker identity (`www-data` here) to the proxy group through an approved change. No account/group has been created or altered. |
| Versioned release | Root-owned reviewed release at `/opt/launchpad/releases/<release-id>` and root-managed `/opt/launchpad/current` symlink. Use root:launchpad directories 0750, files 0640 and required executables 0750. The app receives the private group; nginx joins only `launchpad-proxy`. App user can read/execute code but cannot modify releases, and nginx cannot read the release. Include the reviewed new/untracked candidate files; do not assume a tracked-only archive includes the authentication work. Exclude databases, keys, `.env`, logs, caches and unrelated projects. |
| Configuration | [launchpad.env.example](../deploy/vm/launchpad.env.example) → future `/etc/launchpad/launchpad.env`, root:root 0600 within root-owned 0700 directory. Use Launchpad-specific signing and any approved identity-service secrets; do not reuse or source the older application's environment. Secret values remain blank in the repository. Inject them privately; never source/dump the populated file into a report. |
| Private persistent state | `/var/lib/launchpad`, `launchpad:launchpad-proxy` 0700; separate `learners.sqlite` and `ad-security.sqlite` files 0600, each explicitly provisioned. The latter preserves login limits across restarts. Existing prototype data stays untouched. Root filesystem durability/backup/encryption still need CCA acceptance. |
| Runtime connection | `/run/launchpad` 0750; socket `gunicorn.sock` is `launchpad:launchpad-proxy` 0660. Nginx gets socket access, not database/config/key access. Gunicorn has **no TCP listener** in this service. |
| New systemd unit | [launchpad.service](../deploy/vm/launchpad.service) → future `/etc/systemd/system/launchpad.service`. Runs as the dedicated non-root account, uses `start_real.py`, private state/runtime directories, a restrictive process umask, restart limits, safe journal output and service-specific hardening. It creates directories, never a missing database. |
| Hostname routing | [launchpad.nginx.conf](../deploy/vm/launchpad.nginx.conf) proposes Launchpad at `lesliec.ccaurora.edu/`. In the approved cutover, remove only `lesliec` from both old server-name directives before enabling the candidate. Preserve `itsupport`, its existing upstream, the default site and unrelated services unless separately authorized. |
| TLS and proxy trust | Fixed `https://lesliec.ccaurora.edu` HTTP redirect, TLS 1.2/1.3, exact Host check and Unix proxy. Verify certificate renewal/coverage and key match before cutover. Nginx overwrites the secure-scheme header and clears other forwarded scheme/host/path claims. No blanket ProxyFix or wildcard proxy trust is added. |
| Logs / health | Minimal nginx access log contains time, method, status and duration; no query/identity/cookie fields. Raw vhost error output goes to `/dev/null`: the isolated test proved that even `crit` can expose callback query values on Unix-backend failure. Sanitized access logs retain 5xx/latency; safe application journal messages provide app error references. Raw nginx request diagnostics are intentionally unavailable. Review CCA log ownership/rotation; never enable raw debug logging on real sessions. Health probes do not substitute for authenticated smoke checks. |

Gunicorn trusts Unix-socket proxy peers, so socket permissions and nginx's header replacement are part of the security boundary. The shared default Gunicorn configuration still supports other modes; the unit's required `GUNICORN_CMD_ARGS` overrides its TCP bind. Do not override that variable in the secret file. The socket umask is temporary; private file creation retains the process's restrictive umask. [Gunicorn proxy settings](https://gunicorn.org/reference/settings/), [nginx proxy headers](https://nginx.org/en/docs/http/ngx_http_proxy_module.html)

## Controlled browser test routing

**The operator has now authorized the controlled-test installation, certificate permission remediation, backend preparation, startup and validated Nginx reload, with maintenance rollback if activation fails.** Current noninteractive sudo access is unavailable; privileged execution remains pending. The retirement decision is settled. This proposal uses `https://lesliec.ccaurora.edu/` for the controlled test at the root path, not a subpath or alternate public port. Preserve the unretired `itsupport.ccaurora.edu` alias. No DNS change, firewall opening, new service account or systemd installation is needed for this supervised test.

Read-only baseline on 2026-10-09: enabled `/etc/nginx/sites-enabled/cca-it-support-assistant` links to `/etc/nginx/sites-available/cca-it-support-assistant`. Both HTTP and HTTPS blocks claim both names and proxy to `http://127.0.0.1:8000`. Nginx is active with a root master and `www-data` workers. The older assistant is failed/disabled, `it-ai-agent.service` is inactive/disabled, and neither 8000 nor 8443 is listening. `lesliec` currently returns 502 over verified HTTPS. The default site and other hostname remain outside this change.

The exact prepared files are:

| File | Purpose |
| --- | --- |
| [retire-lesliec-route.patch](../deploy/vm/retire-lesliec-route.patch) | Removes only `lesliec.ccaurora.edu` from the two existing `server_name` lines, retaining `itsupport` and its upstream. Dry-run against current configuration before applying; stop if it has changed. |
| [launchpad-controlled.nginx.conf](../deploy/vm/launchpad-controlled.nginx.conf) | New single-host vhost: existing HTTPS/443 → `https://127.0.0.1:8443`, explicit chain/hostname verification, TLS 1.2/1.3, fixed canonical Host and stripped forwarding claims. Never enable alongside the production Launchpad vhost. |
| [launchpad-controlled-maintenance.nginx.conf](../deploy/vm/launchpad-controlled-maintenance.nginx.conf) | Mutually exclusive rollback vhost: trusted HTTPS and 503 with no backend, no-store and Retry-After. |
| [controlled-backend.ext](../deploy/vm/controlled-backend.ext) | Server-only leaf constraints and SAN `launchpad-controlled.invalid` for a separate short-lived local backend CA. This name is an internal certificate identifier, never a student URL or DNS request. |
| [controlled-test.example.json](../deploy/controlled-test.example.json) | Generic example keeps participant-specific fields blank. The designated `work-study-01` run already contains the privately supplied UPN suffix, narrow search base and `direct` policy, alongside the known host, DC/636, supplied AD CA bundle and verified group DN. Do not initialize or enroll it again. |

The app remains a supervised non-root foreground process under the run's owner (`lesliec` for these commands), using `start_controlled_test.py` and the marked, Git-ignored `work/controlled-work-study/<run-id>` dataset. This is distinct from the proposed production `launchpad` service/Unix socket. Its separate signing key, learner/throttle stores, GUID enrollment, permissions and fixed 900-second sessions remain unchanged. No background lookup account is required; AD disablement/group removal can leave a session usable until expiry or local revocation. Saved progress survives expiry; unsent answers are not autosaved. No Pilot A configuration is used.

### Three independent TLS boundaries

1. **Browser → Nginx:** use the current certificate at the existing paths under Michael's operator-reported approval, after securing every identified key-bearing copy and preserving required consumer access. The current wildcard chain validates and expires October 28; Michael is arranging renewal with Jordan next week. The minimal permission change is root:root 0600 for `ccaurora.cer`, `fullchain.pem` and `ccaurora.key`, plus any further identified key-bearing copies, after inspection. Nginx supports a restricted combined certificate/key file; a public-only replacement chain or new certificate is not a prerequisite. Its root master can read these files; neither `www-data` workers nor Launchpad needs filesystem access. Verify leaf/key match, privileged configuration and both hostnames after the change. Past world readability is evidence of exposure opportunity, not proof of compromise; permission changes do not erase that history. Renewal must preserve access restrictions and cover both current aliases.
2. **Nginx → backend:** separate seven-day local CA and backend leaf; app-owner key 0600 in the ignored run, only the CA's public certificate copied to root-managed `/etc/nginx/launchpad-controlled/backend-ca.pem`. No trust-store installation. Nginx uses fixed `proxy_ssl_name launchpad-controlled.invalid`, explicit trusted CA and `proxy_ssl_verify on`; a different name, issuer or expired certificate must fail. Never give Launchpad the institutional wildcard key. [Official Nginx proxy TLS directives](https://nginx.org/en/docs/http/ngx_http_proxy_module.html#proxy_ssl_verify) document verification as off by default, so the explicit checks are required.
3. **App → AD:** the unchanged explicit supplied Windows-store public bundle verifies `CCCDC01.ccc.ccofc.edu:636`. Its transport verification is passed; institutional fingerprint approval and actual password/group authentication remain pending. It is not a substitute browser or backend certificate.

### Preparation and preflight commands for the authorized operator

Run one step at a time; stop on any error. The designated `work-study-01` learner is already enrolled with privately supplied verified identity, narrow search boundary and `direct` policy. Do **not** repeat initialization or enrollment; run the read-only verification below. The [new-only initialization procedure](ad_authentication.md#exact-future-operator-commands) is for separately authorized new runs. The existing validation interpreter is usable for this supervised test while it exists; if removed, select an approved `requirements-real.txt` environment, not the incomplete project `.venv`. Persistent controlled data and the AD CA bundle do **not** live under `/tmp`.

The dedicated backend key/certificates for `work-study-01` were created and validated on October 9; see the [execution record](vm_verification.md#executed-independent-checks-for-the-authorized-activation). **Do not repeat this generation block for that existing run.** Retain this recipe only for a separately authorized new run: it refuses an existing TLS directory, creates no public listener and makes no directory connection.

```bash
cd /opt/project/ITWorkStudyLaunchpad
LP_TEST_PY=/tmp/launchpad-real-validation-6qhv4cbn/venv/bin/python
LP_TEST_RUN=work-study-01
LP_TLS_DIR="$PWD/work/controlled-work-study/$LP_TEST_RUN/tls"
(
  set -e
  umask 077
  test -d "$PWD/work/controlled-work-study/$LP_TEST_RUN"
  mkdir -m 700 "$LP_TLS_DIR"
  openssl req -x509 -newkey rsa:3072 -nodes -sha256 -days 7 \
    -subj '/CN=Launchpad controlled backend CA' \
    -addext 'basicConstraints=critical,CA:TRUE,pathlen:0' \
    -addext 'keyUsage=critical,keyCertSign,cRLSign' \
    -keyout "$LP_TLS_DIR/ca.key" -out "$LP_TLS_DIR/backend-ca.pem"
  openssl req -new -newkey rsa:3072 -nodes -sha256 \
    -subj '/CN=launchpad-controlled.invalid' \
    -keyout "$LP_TLS_DIR/backend.key" -out "$LP_TLS_DIR/backend.csr"
  openssl x509 -req -in "$LP_TLS_DIR/backend.csr" \
    -CA "$LP_TLS_DIR/backend-ca.pem" -CAkey "$LP_TLS_DIR/ca.key" -CAcreateserial \
    -days 7 -sha256 -extfile deploy/vm/controlled-backend.ext -out "$LP_TLS_DIR/backend.pem"
  openssl verify -CAfile "$LP_TLS_DIR/backend-ca.pem" -no-CApath -no-CAstore \
    -purpose sslserver -verify_hostname launchpad-controlled.invalid "$LP_TLS_DIR/backend.pem"
  openssl x509 -in "$LP_TLS_DIR/backend-ca.pem" -noout -dates -fingerprint -sha256
)
"$LP_TEST_PY" -B scripts/manage_controlled_test.py verify --run "$LP_TEST_RUN"
"$LP_TEST_PY" -B scripts/start_controlled_test.py --run "$LP_TEST_RUN" \
  --certfile "$LP_TLS_DIR/backend.pem" --keyfile "$LP_TLS_DIR/backend.key"
```

`--serve` is deliberately absent from preflight. Record the public CA fingerprint and expiry in restricted test evidence; never display any `.key` file. The browser continues to use its normal public trust and sees only the Nginx wildcard leaf. Seven days is a proposed maximum for these disposable backend certificates, not a renewal service; end or reauthorize the test before expiry. Only a public CA file leaves the private run.

After certificate-owner remediation, validate the front end using normal trust and **metadata only**. Do not use `-k`, `-verify 0`, a trust bypass, `nginx -T`, or raw debug logs. Certificate/private-key public-digest matching is an owner step in the [certificate section](#certificate-findings-and-ownership).

```bash
openssl x509 -in /opt/project/certs/fullchain.pem -noout -dates -checkhost lesliec.ccaurora.edu
openssl x509 -in /opt/project/certs/fullchain.pem -noout -checkend 604800
timeout 15 openssl s_client -connect lesliec.ccaurora.edu:443 \
  -servername lesliec.ccaurora.edu -verify_hostname lesliec.ccaurora.edu \
  -verify_return_error -CAfile /etc/ssl/certs/ca-certificates.crt -brief </dev/null
```

The certificate must cover the full planned test window and the installed leaf/key must match. Recheck every identified key-bearing path's mode/owner before installation; a combined chain must remain root-only, and only a proven public-only chain may be generally readable. Do not paste protected configuration or key blocks into evidence.

### Authorized activation sequence — not executed

**Status update, October 12:** the public controlled-test login route now returns 200 with verified HTTPS. The following initial-activation handoff is historical; do not run it again for the login investigation or an application-only update. Use the [latest request evidence](vm_verification.md#login-post-investigation-after-worker-restart--2026-10-09) and the full-master restart note below. A new interruption still requires coordination with the facilitator.

Preserve all old source/data in place and capture the current route/service definitions in a restricted snapshot before changing the route. Retain the failed/disabled baseline. The [full retirement archive](#required-archive-before-cutover) remains separate recovery work; this test does not delete or restart the assistant. Verify the configured `itsupport` route against its recorded baseline (this VM currently cannot resolve that alias; use `curl --resolve itsupport.ccaurora.edu:443:10.117.1.127` with normal TLS validation). Record the routing snapshot path privately.

**Current operator handoff:** noninteractive `sudo` requires a password, so certificate containment and public activation could not be executed by the preparation session. The temporary backend smoke-test process was stopped. The existing enrollment, configuration and backend TLS files are ready; do not initialize or enroll again. Use these two terminals on the VM:

Terminal 1, as `lesliec`, remains open and supervised:

```bash
cd /opt/project/ITWorkStudyLaunchpad
/tmp/launchpad-real-validation-6qhv4cbn/venv/bin/python -B scripts/start_controlled_test.py \
  --run work-study-01 \
  --certfile "$PWD/work/controlled-work-study/work-study-01/tls/backend.pem" \
  --keyfile "$PWD/work/controlled-work-study/work-study-01/tls/backend.key" --serve
```

Terminal 2: review [activate-controlled-test.sh](../deploy/vm/activate-controlled-test.sh), then run it. `sudo` may prompt for the operator's password privately in that terminal; never put it in chat, command arguments or a file.

```bash
sudo bash /opt/project/ITWorkStudyLaunchpad/deploy/vm/activate-controlled-test.sh
```

**Loading later Python changes:** this launcher creates the application in the Gunicorn master before forking workers. Recycling a worker or sending HUP is not a reliable source-code update: the replacement worker can inherit the old imported application. After the facilitator ends the active test and approves the brief interruption, stop only the identified controlled backend master and relaunch the same command above, with the existing signing key, configuration, enrollment and databases. Confirm a new master start time, child worker and expected loopback listener. Do not initialize the run again, rotate its signing key, rerun the activation helper or reload Nginx for an application-only change. The operator authorized this full controlled-backend restart on October 12, conditional on no active test; future interruptions still need coordination.

**Controlled-test diagnostics:** serving now creates an operator-private `logs/` directory under the existing ignored run. `login-diagnostics.log` records rejected AD login POSTs with UTC timestamp, fixed `/auth/login` path, HTTP status and an allowlisted reason (for example `csrf_session_absent`, `csrf_mismatch`, `origin_rejected` or `login_fields_invalid`). It excludes identities, query strings, bodies, passwords, cookies and tokens. `ad_denied_or_unavailable` deliberately does not claim whether a password, group or directory transport check failed. `csrf_after_session_invalid` does not distinguish expiry from local revocation. No response or authentication decision changes. This file rotates at 1 MiB with two retained copies; the CLI's 077 umask keeps them private.

`backend-access.log` records only fixed method/path classifications and status; `backend-events.log` records fixed server lifecycle/parser reason codes, without formatting raw Gunicorn exceptions or request headers. A parser failure may have `path=unavailable`; never infer a path that could not be parsed. Files are 0600 within a 0700 directory. Raw stdout/stderr capture is disabled. If the launcher is detached for the supervised window, discard its raw stdout/stderr; use these private sanitized files for diagnostics. These are local test records, not centralized monitoring or a permanent hosting service.

Each worker emits `event=worker_ready` with master/worker PIDs, a fingerprint of repository application/template/static/launcher source and an offline check that the loaded W-number and full-UPN normalization agree. Verify a new master, that boot record and its source fingerprint after a restart; an updated HTML hint alone is insufficient. Preflight without `--serve` remains read-only and does not create logs.

For the next supervised attempt, correlate the UTC timestamp in both backend diagnostic files with the existing sanitized Nginx access log. An Nginx rejection before reaching the backend still lacks an exact reason/path in its existing minimal format; the backend cannot fabricate that evidence. Do not enable raw Nginx error logs or capture browser headers/bodies. If that boundary is implicated, prepare a separately scoped proxy diagnostic change. The original October 9 400 is not considered resolved by adding diagnostics or restarting.

The helper checks actual consumers and file layout, rejects unexpected copies, compares only public-key digests, restricts the three shared key-bearing files to root:root 0600, verifies denied non-root access and tests Nginx's retained access. It preserves a root-private routing/service-definition snapshot under `/var/backups/launchpad-routing.*`. It then requires the loopback backend's verified TLS/200/401 behavior, installs only the dedicated public backend CA and prepared vhosts, patches only the two `lesliec` names, validates Nginx before reloading, and verifies the public responses. The `itsupport` comparison pins the known VM IP while preserving hostname validation because that alias currently does not resolve here. It never starts the app as root, contacts AD, reenrolls learners or copies a wildcard key into the repository.

Post-enable failure or interruption selects the verified-HTTPS maintenance 503 route; certificate restrictions are never reversed. If rollback validation itself fails, the helper reports that explicitly instead of claiming closure. A pre-enable failure leaves routing unreloaded or restores its saved configuration. Review a failed invocation and its restricted evidence before retrying; it intentionally refuses pre-existing activation destinations. The expanded manual commands below explain the same operation and recovery; **do not apply them again after successful helper activation**. The helper has passed shell syntax, non-root refusal and eight isolated mocked rollback/validation checks, but has not been run with root privileges against this VM.

Success establishes the reachable login page, not actual AD authentication. Yasmin then uses `https://lesliec.ccaurora.edu/` from campus or approved VPN, requires normal browser HTTPS without warnings, enters her own full CCA UPN/password herself, uses invented training answers, and logs out afterward. Sessions expire absolutely after 15 minutes; submitted progress persists, unsaved answers do not automatically submit. Keep the test supervised and close it using the maintenance procedure below before stopping the backend. The prepared backend leaf expires **October 16, 2026 at 21:28:14 UTC**; close the test before expiry unless a renewed backend pair is separately prepared and validated.

In one supervised non-root terminal, start only the isolated app after successful preflight:

```bash
"$LP_TEST_PY" -B scripts/start_controlled_test.py --run "$LP_TEST_RUN" \
  --certfile "$LP_TLS_DIR/backend.pem" --keyfile "$LP_TLS_DIR/backend.key" --serve
```

Leave that terminal supervised. No production systemd unit is used. In a second operator terminal set the same path variables, then require backend certificate/hostname and HTTP checks before changing routing:

```bash
ss -ltn '( sport = :8443 )'
timeout 15 openssl s_client -connect 127.0.0.1:8443 \
  -servername launchpad-controlled.invalid -verify_hostname launchpad-controlled.invalid \
  -verify_return_error -CAfile "$LP_TLS_DIR/backend-ca.pem" -no-CApath -no-CAstore -brief </dev/null
curl --noproxy '*' --cacert "$LP_TLS_DIR/backend-ca.pem" \
  --resolve launchpad-controlled.invalid:8443:127.0.0.1 \
  -H 'Host: lesliec.ccaurora.edu' --connect-timeout 5 --max-time 15 \
  -sS -o /dev/null -w '%{http_code}\n' https://launchpad-controlled.invalid:8443/auth/login
```

Expected: **only** `127.0.0.1:8443`, successful chain/name validation, login page 200. Stop for `0.0.0.0`, `[::]`, any TLS error or unexpected response. Never open 8443 to the student. These anonymous checks establish neither AD sign-in nor enrolled access.

The exact root-managed routing proposal below runs from the repository and assumes candidate destinations do not already exist. Stop on any error or unexpected existing path; review rather than overwrite a different deployment. Do not regenerate an existing run or bypass a failing preflight.

```bash
test ! -e /etc/nginx/sites-available/launchpad-controlled
test ! -L /etc/nginx/sites-available/launchpad-controlled
test ! -e /etc/nginx/sites-available/launchpad-controlled-maintenance
test ! -L /etc/nginx/sites-available/launchpad-controlled-maintenance
test ! -L /etc/nginx/sites-enabled/launchpad-controlled
test ! -e /etc/nginx/sites-enabled/launchpad-controlled
test ! -e /etc/nginx/launchpad-controlled
test ! -L /etc/nginx/launchpad-controlled
sudo patch --dry-run --forward -p0 -d /etc/nginx/sites-available < deploy/vm/retire-lesliec-route.patch
LP_ROUTE_ARCHIVE=$(sudo mktemp -d /var/backups/launchpad-routing.XXXXXX)
sudo cp -p /etc/nginx/sites-available/cca-it-support-assistant "$LP_ROUTE_ARCHIVE/cca-it-support-assistant"
sudo install -d -o root -g root -m 0755 /etc/nginx/launchpad-controlled
sudo install -o root -g root -m 0644 "$LP_TLS_DIR/backend-ca.pem" /etc/nginx/launchpad-controlled/backend-ca.pem
sudo install -o root -g root -m 0644 deploy/vm/launchpad-controlled.nginx.conf /etc/nginx/sites-available/launchpad-controlled
sudo install -o root -g root -m 0644 deploy/vm/launchpad-controlled-maintenance.nginx.conf /etc/nginx/sites-available/launchpad-controlled-maintenance
sudo patch --forward -p0 -d /etc/nginx/sites-available < deploy/vm/retire-lesliec-route.patch
sudo ln -s /etc/nginx/sites-available/launchpad-controlled /etc/nginx/sites-enabled/launchpad-controlled
sudo nginx -t
```

Inspect validation locally; require success **without duplicate-name warnings**, correct public-only chain, protected matching key and correct backend trust. Keep the exact pre-change route archive. If validation fails, restore the old config/remove only the newly added symlink using the routing-reversal steps below; do not reload the invalid candidate. If validation passes and authorization remains in effect:

```bash
sudo systemctl reload nginx
curl --noproxy '*' --connect-timeout 5 --max-time 15 -sS -o /dev/null -w '%{http_code}\n' https://lesliec.ccaurora.edu/auth/login
curl --noproxy '*' --connect-timeout 5 --max-time 15 -sS -o /dev/null -w '%{http_code}\n' https://lesliec.ccaurora.edu/student
```

Expected 200 for login, 401 for anonymous learner progress; no cookies/headers/bodies are recorded. Nginx reload follows its [official validation/reload procedure](https://nginx.org/en/docs/beginners_guide.html#control). Confirm `itsupport` remains at its recorded baseline and repeat the hostname/certificate check on the student's actual browser/network. Then the student signs in privately with their own UPN/password and invented answers. Verify allowed enrolled account, denied non-enrolled/ineligible access without inducing AD lockouts, learner isolation, score/completion persistence, 15-minute expiry, logout and local revocation. Firefox plus another browser, responsive layouts, keyboard, screen reader and 200% zoom remain required human checks. No real credential attempt is part of repository validation.

### Closed-access rollback and exact routing reversal

On failed acceptance, close the public test first. Keep the private dataset, signing key, namespace and throttle state; never delete/reinitialize them. The following replaces only the dedicated Launchpad site contents with the prepared 503 version. Recheck syntax and have the authorized operator reload. The other alias retains its old route:

```bash
sudo install -o root -g root -m 0644 /etc/nginx/sites-available/launchpad-controlled-maintenance /etc/nginx/sites-available/launchpad-controlled
sudo nginx -t
sudo systemctl reload nginx
curl --noproxy '*' --connect-timeout 5 --max-time 15 -sS -o /dev/null -w '%{http_code}\n' https://lesliec.ccaurora.edu/
```

Expected verified HTTPS and **503**. Then stop only the manually launched controlled-test foreground process with Ctrl-C; do not restart the old service. Local session revocation/disablement remains available in the [test procedure](ad_authentication.md#exact-future-operator-commands). Record failed smoke checks without credentials/answers; preserve a consistent snapshot if any progress was written.

If a complete **routing-only** reversal is required, verify that `LP_ROUTE_ARCHIVE` names this change's restricted snapshot and that no intervening shared change will be lost. Restore the saved old site and remove only the new symlink; candidate files and test data remain for review:

```bash
sudo test -f "$LP_ROUTE_ARCHIVE/cca-it-support-assistant"
sudo cp -p "$LP_ROUTE_ARCHIVE/cca-it-support-assistant" /etc/nginx/sites-available/cca-it-support-assistant
sudo unlink /etc/nginx/sites-enabled/launchpad-controlled
sudo nginx -t
sudo systemctl reload nginx
```

Stop on errors; never reload an invalid configuration. This restores the documented **502 / failed backend** baseline, not a working assistant. Certificate exposure remediation/renewal is a separate shared change and must **not** be reversed to restore an old/exposed key. No old service restart, data restore, AD change or deletion is implied.

## Operator sequence after separate deployment authorization

These are future steps, not commands executed by this preparation. Keep invitations closed until authentication, group eligibility, archival and the hosted checklist pass. A repository test pass does not authorize any command against shared infrastructure.

1. Obtain the owners' explicit approval for the `lesliec` cutover, archival/retirement boundary and shared-nginx maintenance window. Preserve `itsupport` unless separately retired. Resolve certificate renewal/key match, verified LDAPS trust/connectivity, exact group and identity namespace, lookup/lifecycle policy, removal owner/delay and the [data/retention/recovery decisions](learner_data_policy.md). Identify the rollback authority and approve a closed/maintenance response if Launchpad cannot pass verification.
2. Verify OS/service/ports/routes again immediately before the change and complete the [required archive](#required-archive-before-cutover), including an off-VM restore check. Record both hostnames' baseline behavior and retain the failed old-service state. Do not disable the whole old site, restart the old backend or reboot the shared VM as a convenience.
3. Provision the approved service identity, proxy group, private configuration directory and durable state directory. Code/config remains root-managed. Group-membership changes must use the shared service owner's reload/restart procedure; verify the resulting worker groups and socket access rather than assuming they changed.
4. Build the approved release's virtual environment at its intended final path with `requirements-real.txt`, using a non-root build identity. Run the full suite as non-root with isolated test data, then make the release root-owned/read-only to the app. Current VM tests use Python 3.12.3; the repository pins 3.12.15. Have CCA approve/install the pinned runtime or approve a revised pin after its full suite passes. Do not silently claim the exact pinned runtime was tested or relocate an old virtual environment blindly.
5. For a fresh staging dataset only, explicitly initialize and verify the NEW file as `launchpad` after verifying the storage path. Do not run these against any existing database:

   ```bash
   sudo -u launchpad /opt/launchpad/current/.venv/bin/python -B /opt/launchpad/current/scripts/manage_real_data.py initialize --db /var/lib/launchpad/learners.sqlite
   sudo -u launchpad /opt/launchpad/current/.venv/bin/python -B /opt/launchpad/current/scripts/manage_real_data.py verify --db /var/lib/launchpad/learners.sqlite
   sudo -u launchpad /opt/launchpad/current/.venv/bin/python -B /opt/launchpad/current/scripts/manage_real_data.py initialize-ad-state --path /var/lib/launchpad/ad-security.sqlite
   sudo -u launchpad /opt/launchpad/current/.venv/bin/python -B /opt/launchpad/current/scripts/manage_real_data.py verify-ad-state --path /var/lib/launchpad/ad-security.sqlite
   ```

   These are proposed operator commands; neither the account nor this dataset was created here. Enroll designated test subjects using the verified AD namespace issuer and objectGUID through private prompts, and grant only the approved mentor-to-learner mappings. An AD login alone creates no learner or mentor. Never migrate by display name; existing OIDC/prototype/older-app records stay separate unless a reviewed explicit migration is authorized.
6. Install/populate the root-private environment file through the approved secret channel, install the reviewed unit and validate it. Empty secrets deliberately refuse startup. Start **only the new Launchpad service** under authorization, then verify its non-root user, Unix-only socket, file modes and safe startup. Do not run `sudo python app.py` or Gunicorn as root.
7. In the approved window, remove **only `lesliec.ccaurora.edu`** from both existing HTTP/HTTPS vhost name lists, preserving `itsupport` and its upstream. Add the reviewed Launchpad vhost for `lesliec` at `/`, validate the complete configuration with privileged `nginx -t`, and have the shared-service owner perform the authorized reload. If syntax or certificate checks fail, restore the staged configuration before any reload. Never leave duplicate names or disable unrelated sites. Nginx reload applies validated configuration without requiring a VM reboot; follow its [documented reload behavior](https://nginx.org/en/docs/beginners_guide.html#control).
8. Execute [VM verification](vm_verification.md), including actual CCA LDAPS sign-in, disabled/nonmember rejection, namespace/enrollment isolation, lifecycle removal handling, old-cookie denial, learner/mentor permissions, persistence, encrypted off-VM restore and browser/accessibility checks. Compare `itsupport` with its recorded baseline. A VM reboot requires its own approved shared maintenance window; it has not been performed here. Enable boot startup/open invitations only after the owner accepts the evidence.

Future validation/status commands include `systemd-analyze verify /etc/systemd/system/launchpad.service`, selected safe `systemctl show launchpad` fields, sanitized application-journal inspection, socket/listener inspection and an HTTPS status-only request to `/auth/login`. A 200 on that route proves a reachable sign-in page, not working AD authentication or database writes. Never paste raw authentication headers/cookies, directory diagnostics, passwords or callback URLs into evidence. Do not enable verbose nginx/identity request logging for debugging.

## Backups, restarts and rollback

Retain the [real-user recovery procedure](real_user_operations.md). Choose backup interval, retention, encrypted destination, recovery targets and named owner through CCA policy; no timer, pruning policy or off-host destination is invented. A private local snapshot directory such as `/var/lib/launchpad/backups` (0700) is a staging location, not disaster recovery. Keep off-VM transport/encryption credentials outside the web process and verify transfer/checksum/failure alerts through approved operations.

Before an authorized release change, make a consistent SQLite snapshot and verify it off the VM. Use an approved new destination every time; never raw-copy a live SQLite database. Restart only `launchpad` for ordinary app changes after approval; missing data/configuration must refuse startup, not create replacements. After any app or VM restart, confirm exact test progress and account isolation.

Back up the separate AD throttle store consistently as well; the learner backup command is not its schema-specific backup tool. Signing-key rotation changes its per-user HMAC identities. After key rotation or lost/stale throttle-state recovery, keep all login admission closed for at least 300 seconds and verify both login limits before reopening. This is an operator recovery gate, not an automatic startup delay. See [AD storage/recovery](ad_authentication.md#login-limits-storage-and-recovery).

If initial cutover fails, close Launchpad access or use the preapproved maintenance response for `lesliec`; preserve `itsupport` and unrelated sites. The operator may restore the archived nginx routing only as an explicit routing rollback, with the recorded old-service failed/disabled baseline and **no automatic old-backend restart**. That rollback does not restore a working assistant. Restoring the archived old application to active service requires separate owner approval, LDAP/security fixes and verification; never route real learners to its known unverified authentication as a convenience.

Preserve Launchpad data and a consistent snapshot if any writes occurred before rollback. Never point old code at Launchpad records. For later application rollback, select the retained compatible authenticated Launchpad release and configuration; review AD namespace/group/lifecycle or OIDC issuer changes, host and signing secret as well as code. A previous incompatible/unauthenticated app is never a rollback target for real records.

Data recovery is separate: restore a checked off-VM snapshot into a NEW file, retain original/failed data, revoke copied sessions, rotate the signing key and reconcile disabled accounts, removed assignments/group eligibility and current record policy. Run the isolated restore checks before switching the configured path or reopening access. Never overwrite learner data or delete tables to make an older build start.

## Executed versus pending

- **Executed:** VM identity/DNS and scoped service inspection; certificate metadata/chain/hostname verification and TLS-only live handshake; historical **210-test OIDC baseline on 2026-10-07** and content validation as non-root with isolated data. Current AD-candidate results are in [VM verification](vm_verification.md).
- **Prepared:** repository nginx/systemd/environment files, auth handoff, future provisioning/restart/backup/rollback steps and [hosted verification](vm_verification.md).
- **Local configuration validation:** final results are recorded in the verification document; no systemd service installation/start or shared nginx configuration test requiring the private key is implied.
- **Pending:** privileged execution of the authorized controlled-test cutover and archive/restore proof; decision about any later `itsupport` retirement; certificate renewal/direct key match; actual verified CCA LDAPS, approved exact group/namespace and lookup/lifecycle policy; removal owner/delay/procedure; exact-runtime acceptance; service-account/permission/hardening verification after authorized installation; VM restart persistence; off-VM recovery; intended-user network access and all rendered browser/accessibility checks.

No institutional credentials, live directory binds, AD changes, firewall changes, real-record migrations/deletions, purchases, commits, pushes, deployments, shared-service restarts or Codex sandbox-disable flags were used. Keep this operational document internal; portfolio material must omit internal addressing, infrastructure and identity details.
