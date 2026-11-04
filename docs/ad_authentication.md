# Active Directory authentication candidate

Prepared 2026-10-08. **Repository implementation and isolated validation only; not an approved or deployed CCA directory integration.** No AD account/group has been created or changed, no institutional password has been supplied and no live CCA bind has been performed. The user selected preparation of the lookup-account option; CCA availability, permissions, credentials and the removal-delay policy still need the directory owner's approval before real learners are invited. See [VM verification](vm_verification.md) for executed checks and limits.

The selected preparation targets Launchpad at `https://lesliec.ccaurora.edu/`, replacing the older assistant only through the separately approved [archive and cutover procedure](vm_deployment.md). Existing support-assistant secrets, cookies, logs and databases are not authentication or enrollment inputs to Launchpad. Curriculum, scoring, completion rules and explicit read-only mentor assignments remain unchanged.

## Transport and credential handling

The AD backend uses direct LDAPS on **port 636**, TLS 1.2 or newer, trusted-chain validation and exact directory-hostname verification before sending a bind. Configuration accepts a bare DNS hostname, rejecting URL schemes, embedded ports and IP literals. The adapter also checks the constructed ldap3 server's transport and port. Referrals and alias dereferencing are disabled; directory result failures, multiple matches and malformed identities deny access rather than selecting a fallback.

Credential-free LDAPS verification on 2026-10-08 **passed against the user's supplied Windows-store CA bundle**, including chain and hostname validation for `CCCDC01.ccc.ccofc.edu`. Earlier checks using only VM system trust failed; no system trust was changed. CCA approval of the supplied fingerprints and centrally managed deployment provenance remain unverified; `ccc.ccofc.edu` is still an unverified login-domain convention. See [the separate transport and provenance evidence](#ad-trust-discovery-and-public-certificate-export). The public web wildcard certificate is not proof of the DC's certificate or issuer. Plain LDAP, opportunistic StartTLS, `CERT_NONE`, anonymous/empty-password fallback and following referral credentials are not supported alternatives. The official [ldap3 TLS guidance](https://ldap3.readthedocs.io/en/latest/ssltls.html) requires explicit certificate verification; [connection settings](https://ldap3.readthedocs.io/en/latest/connection.html) expose referral handling separately. Microsoft's [LDAPS certificate requirements](https://learn.microsoft.com/en-us/troubleshoot/windows-server/active-directory/enable-ldap-over-ssl-3rd-certification-authority) describe directory-server names, trust and server-authentication usage.

In the web workflow, learners submit their directory password through the HTTPS sign-in form. The adapter uses it for that bind/search and does not write it to cookies, application databases or logs. It does not implement password storage, password resets or a local password fallback. The separate standalone diagnostic below uses a private terminal prompt for one learner bind only. The candidate lookup credential is a separate protected operational secret; it is not the learner's retained password. Application diagnostics use bounded outcomes rather than raw LDAP errors, results or request bodies. Do not enable library/request debug logging or paste directory diagnostics into reports.

## Identity, eligibility and enrollment

The browser field is labeled **CCA username** and hints that a **W-number** or full UPN is accepted. Surrounding username whitespace is removed and username case is normalized; a bare W-number uses `LAUNCHPAD_AD_DOMAIN` exactly once. The same normalization feeds the LDAPS bind/search and persistent per-account login limiter, so case, whitespace and short/full-UPN variants cannot obtain separate attempt budgets. Passwords are passed through unchanged, including leading/trailing whitespace. GUID enrollment, group eligibility and permissions are unchanged. This source change requires a backend restart to take effect; defer that restart until the active supervised test has ended. No Nginx change or re-enrollment is needed.

The supported login convention is a short **UPN local part**, or a full UPN in the configured domain. A short input is resolved to that domain's UPN; arbitrary alternate domains, `DOMAIN\\user` and an unrelated `sAMAccountName` convention are not silently accepted. CCA must confirm the convention for intended users before release.

Authentication searches for exactly one enabled person/user matching that UPN and the configured eligibility group. The operator must explicitly choose `direct` or `nested`: direct tests `memberOf`; nested uses AD's matching rule `1.2.840.113556.1.4.1941`. These policies use membership links and must be tested against CCA's actual group structure; do not assume primary-group-only membership or an arbitrary nested arrangement is included.

**User ADUC observation, 2026-10-08:** the user verified that `CCA_Leslie_Project` exists, confirmed their own account is a member, and read this exact `distinguishedName`:

```text
CN=CCA_Leslie_Project,OU=CCA_Groups_Security_User,OU=CCA,DC=ccc,DC=ccofc,DC=edu
```

Both prepared AD environment examples now use this observed DN for `LAUNCHPAD_AD_GROUP_DN`. It matches the older application's source default, but the evidence for existence, DN and the user's membership is the user's ADUC observation, not that default or an agent-performed directory query. The user also observed `CCA_IT_Testlab` listed separately; its purpose, membership and authorization are not inferred or reused.

**Still pending:** approval to use this group for Launchpad eligibility, its purpose and membership owner, the `direct` or `nested` policy, CCA approval of the CA fingerprints used by the successful LDAPS check, actual directory authentication and availability/permissions of the read-only lookup account. The earlier group observation alone established neither other members nor a stable account `objectGUID` or local enrollment. Pilot A's subsequent user-object verification is recorded separately below, with personal values retained only in private local preparation. Do not enroll the existing membership automatically. The earlier `CCA_IT_WorkStudy_Launchpad` proposal remains unverified; a new group is not assumed necessary. No AD membership or installed configuration is changed by populating the repository examples.

The next concrete step is to confirm the recorded root and issuing-CA SHA-256 fingerprints against an authoritative CCA PKI/GPO/MDM record or the certificate owner. The supplied-bundle handshake below succeeded; that result does not by itself establish central deployment, approval, a bind, group eligibility or lookup permissions.

The identity returned to Launchpad is:

| Part | Meaning |
| --- | --- |
| Issuer | `urn:launchpad:ad:<namespace-UUID>`, using an operator-approved, nonzero canonical lowercase UUID for this directory identity namespace. |
| Subject | The account's raw 16-byte AD `objectGUID`, decoded with AD's byte ordering and represented as a canonical lowercase UUID. |

AD's `objectGUID` is a system-set identifier maintained for the object's lifetime, rather than a display name. [Microsoft attribute reference](https://learn.microsoft.com/en-us/windows/win32/adschema/a-objectguid). A recreated or migrated object may need a separately reviewed mapping; matching names, UPNs or email addresses does not prove continuity of ownership.

A valid AD login and group membership still require an **explicitly enrolled local account**. They create no learner and grant no mentor/admin role automatically. Operators independently verify the namespace/GUID through the approved private process, then use the existing enrollment CLI's prompts. Old OIDC issuers/subjects, synthetic personas and older assistant records are not automatically remapped. If existing records require migration, work on a verified new copy and obtain explicit reviewed bindings; preserve original databases. Record the namespace with the recovery configuration and keep it stable across releases, replicas and restores.

The current enrollment/binding CLI does **not** rebind a learner already owned by an OIDC account to a new AD identity. Default to a new explicitly enrolled AD account with fresh progress. Carrying already-bound OIDC progress forward requires a separately reviewed migration on a copy and purpose-built, tested tooling; do not rewrite issuer/subject fields or bypass unique ownership constraints manually.

Learners read/write only the learner attached to their enrolled authenticated account. Mentors/admins read only explicitly assigned learners; membership in an AD group never grants global access, progress editing or impersonation. Local disabling and assignment removal remain immediate application authorization controls.

## AD trust discovery and public certificate export

This issue is separate from the [website private-key exposure](vm_deployment.md#website-private-key-exposure-and-permission-proposal). Do not use the website wildcard chain or copy any website key-bearing file as AD trust material.

### Historical VM system-trust observations — 2026-10-08

From `ccadlnxweb09` as non-root UID 1000, DNS resolved the specified DC to `10.240.63.60`. OpenSSL 3.0.13 connections had a 15-second limit, SNI/hostname verification and `-verify_return_error`, using `/etc/ssl/certs/ca-certificates.crt` and `/etc/ssl/certs`. No bind, password, referral, certificate installation or trust bypass was attempted.

| Stage | LDAPS 636 | Mandatory StartTLS 389 diagnostic |
| --- | --- | --- |
| TCP | Connected | Connected |
| Upgrade | Direct TLS | LDAP StartTLS accepted before TLS; no bind |
| TLS | TLS 1.3 / TLS_AES_256_GCM_SHA384 selected; handshake aborted during certificate validation | Same |
| Hostname | Offline comparison of presented leaf SAN matched `CCCDC01.ccc.ccofc.edu`; peer identity is not authenticated without chain trust | Same presented leaf and result |
| Trust | Error 20, unable to get local issuer certificate, at depth 1 `CCC Enterprise CA01` | Same failure |

The LDAP client file `/etc/ldap/ldap.conf` selects the system CA bundle. The inspected bundle contained 121 certificates; the bundle and readable certificate-directory entries contained no certificates named CCC ROOT CA or CCC Enterprise CA01. `/usr/local/share/ca-certificates` was empty. The proposed installed `/etc/ssl/certs/launchpad-ad-ca.pem` was absent and has not been created. Subsequent user-supplied exports were tested separately below, without altering this system trust. StartTLS observation does not add StartTLS support to Launchpad, whose adapter remains LDAPS-only.

### Supplied Windows exports and bounded LDAPS result — 2026-10-08

The user supplied `work/ad-ca-review/CCC-ROOT-CA.cer` and `CCC-Enterprise-CA01.cer` and reported exporting them from the CCA-managed Windows computer's **Local Computer > Trusted Root Certification Authorities** and **Local Computer > Intermediate Certification Authorities**, respectively. The user also reported Windows showed “This certificate is OK” for the intermediate's chain to CCC ROOT CA. These are user observations; the agent has not inspected the Windows stores, GPO/MDM deployment or central PKI approval. Centrally managed deployment provenance remains unverified.

Strict whole-file validation found **one DER X.509 certificate in each file**, with byte-for-byte equality to its DER re-encoding, no extra/trailing data and no private-key content. This excludes a concatenated key/certificate, PFX or unrelated payload in either supplied file. Both are currently valid RSA-4096 CA certificates signed with SHA-256/RSA. Both have CA=true, no explicit path-length limit, and Digital Signature, Certificate Sign and CRL Sign usages. Inputs remain unchanged and ignored by Git.

SHA-256 below means the fingerprint of the **DER-encoded certificate**, not the PEM text-file hash. These are public certificate metadata, not private-key fingerprints:

| Certificate | SHA-256 | Provenance / authenticity |
| --- | --- | --- |
| `CCC ROOT CA` | `61E11456BD4F7107A9547EA955A43EC22A5B9E2DC80172A08055411E18EC41E8` | Supplied Windows-store export; subject and issuer `CN=CCC ROOT CA`; validity 2018-03-30 20:03:20 UTC to 2038-03-30 20:13:19 UTC; serial `121A61A4A8268FB8467D80EB2EFA8261`. Central provenance/CCA approval remain unverified. |
| `CCC Enterprise CA01` | `EF9EBE597E4D69726AAC71741B4449DF3CEC5890C94E8A8D97DEEF85ED22D3AE` | Supplied Windows-store export; subject `CN=CCC Enterprise CA01,DC=ccofc,DC=edu`, issuer `CN=CCC ROOT CA`; validity 2018-04-04 19:53:35 UTC to 2028-04-04 20:03:35 UTC; serial `29000000036AA80C04136AFABA000000000003`. Matches the earlier peer-presented intermediate; this match is not CCA approval. |
| DC leaf, for comparison only | `72C8F8134FFE319240CDA680CE9819157100DE8010F018AD08917F4CBC777440` | Presented on both ports; issuer CCC Enterprise CA01, SAN includes the requested hostname; validity 2026-01-20 20:55:47 UTC to 2027-01-20 20:55:47 UTC. Not a CA or trusted identity assertion. |

Only public PEM derivatives were written to a new private temporary directory: `/tmp/launchpad-ad-ca-review-d50wpje_/`. Original exports were not overwritten. The test bundle is `launchpad-ad-ca.pem` in that directory; its **PEM-file** SHA-256 is `3FCA2B4261A70C682C5A52399A910D8DCB04EEDC4159F4254222AB51094A3A8E` (different from each DER certificate fingerprint). Sanitized command results are in `verification.json` there; the directory is temporary and is not an installed trust path.

**Preserved project staging copy, 2026-10-08:** the public root/intermediate PEM files and the byte-identical verified bundle are now retained under `/opt/project/ITWorkStudyLaunchpad/work/ad-ca-review/`. Use `/opt/project/ITWorkStudyLaunchpad/work/ad-ca-review/launchpad-ad-ca.pem` for controlled preparation; its PEM-file hash is exactly the value above. The originals are unchanged and all five certificate files are Git-ignored. No dependency on the temporary path is needed to reconstruct or use the bundle; the durable evidence is recorded here. This local staging copy is neither an installed system trust store nor a backup/recovery guarantee.

| Executed check | Result / limit |
| --- | --- |
| Root self-signature | `openssl verify -check_ss_sig` against the supplied root alone: OK |
| Intermediate signature/chain | `openssl verify` with **only the supplied root** as the trust file, default CA path/store disabled: OK |
| TCP / TLS | `CCCDC01.ccc.ccofc.edu:636`; 15-second command bound; completed at **4:01:51 p.m. MDT (22:01:51 UTC), October 8, 2026**; TLS 1.3, TLS_AES_256_GCM_SHA384 |
| Chain and hostname | Exit 0, `Verification: OK`, `Verified peername: CCCDC01.ccc.ccofc.edu`; explicit supplied bundle, SNI and hostname verification, `-verify_return_error`, TLS minimum 1.2, default CA path/store disabled |
| Authorization scope | Credential-free TLS only, no LDAP bind/password, no other host scanned, no system trust/configuration/service changes, no deployment |
| Institutional approval | **Unverified.** This proves LDAPS validation against the supplied certificates, not that CCA centrally deployed or approved those fingerprints. Revocation status, user authentication, eligibility and lookup permissions were not tested. |

### Locate and inspect on the CCA-managed Windows computer

The agent has access to the Linux VM, **not** this Windows computer. These Windows instructions are prepared and reviewed against Microsoft documentation, not executed. They read stores; do not import, delete, refresh policy or request private keys. If access is denied, obtain the relevant read-only certificate metadata from the device/PKI owner; do not change access controls.

1. Run `certlm.msc` and confirm the console is **Certificates — Local Computer**. Under **Trusted Root Certification Authorities > Certificates**, locate candidates named CCC ROOT CA. Under **Intermediate Certification Authorities > Certificates**, locate candidates named CCC Enterprise CA01. Do not select by name alone or assume a certificate visible under Current User came from institutional management.
2. For every candidate, inspect subject, issuer, serial number, validity, Basic Constraints (CA=true), Key Usage (certificate signing), signature algorithm and Certification Path. Record duplicates/renewals separately. A green chain/status or self-signed root alone does not establish an approved institutional CA. An unexpected associated CA private key on a workstation should be referred to the PKI owner; do not access or export that key.
3. In PowerShell on that computer, obtain only the named candidates' metadata and SHA-256 fingerprints with the following read-only commands. `ThumbprintSHA1` is only the Windows store locator; use `SHA256` for the authenticity comparison.

```powershell
$caNames = @('CCC ROOT CA', 'CCC Enterprise CA01')
$caMetadata = foreach ($storeName in @('Root', 'CA')) {
    foreach ($cert in (Get-ChildItem -Path "Cert:\LocalMachine\$storeName" -ErrorAction Stop)) {
        if ($caNames -notcontains $cert.GetNameInfo(
            [System.Security.Cryptography.X509Certificates.X509NameType]::SimpleName, $false)) {
            continue
        }
        $sha = [System.Security.Cryptography.SHA256]::Create()
        try {
            $fingerprint = [BitConverter]::ToString($sha.ComputeHash($cert.RawData)).Replace('-', '')
        } finally {
            $sha.Dispose()
        }
        [pscustomobject]@{
            Store = "Cert:\LocalMachine\$storeName"
            Subject = $cert.Subject
            Issuer = $cert.Issuer
            Serial = $cert.SerialNumber
            ThumbprintSHA1 = $cert.Thumbprint
            SHA256 = $fingerprint
            NotBeforeUTC = $cert.NotBefore.ToUniversalTime().ToString('o')
            NotAfterUTC = $cert.NotAfter.ToUniversalTime().ToString('o')
            SignatureAlgorithm = $cert.SignatureAlgorithm.FriendlyName
            BasicConstraints = (($cert.Extensions | Where-Object { $_.Oid.Value -eq '2.5.29.19' } | ForEach-Object { $_.Format($false) }) -join '; ')
            KeyUsage = (($cert.Extensions | Where-Object { $_.Oid.Value -eq '2.5.29.15' } | ForEach-Object { $_.Format($false) }) -join '; ')
            HasPrivateKey = $cert.HasPrivateKey
        }
    }
}
$caMetadata | Format-List
```

4. Establish management provenance for each exact candidate, rather than its friendly name. With the selected SHA-1 store locator substituted below, inspect the machine Group Policy and Enterprise store views. These commands have no output-file argument and do not export anything. Review output locally and record only the selected certificate's identity, matching SHA-256 from step 3, source store and result; do not share full machine policy/store dumps.

```powershell
certutil -grouppolicy -store Root '<ROOT_SHA1_STORE_LOCATOR>'
certutil -enterprise -store Root '<ROOT_SHA1_STORE_LOCATOR>'
certutil -grouppolicy -store CA '<INTERMEDIATE_SHA1_STORE_LOCATOR>'
certutil -enterprise -store CA '<INTERMEDIATE_SHA1_STORE_LOCATOR>'
```

Microsoft explains that Local Machine logical stores combine physical stores; policy certificates come from Group Policy templates, and enterprise stores hold directory-distributed certificates. Presence in either view supports managed distribution but is not an independent guarantee of approval or uncompromised device state. Absence does not rule out MDM, imaging or another approved distribution method. Record the authoritative GPO/MDM/PKI deployment record and owner that identify the exact SHA-256 fingerprints. Do not run `gpupdate`, `certutil -addstore`, a repair/import command or an online certificate enrollment as part of this inspection. [Windows store locations](https://learn.microsoft.com/en-us/windows/win32/seccrypto/system-store-locations), [certutil store options](https://learn.microsoft.com/en-us/windows-server/administration/windows-commands/certutil), [Local Computer inspection](https://learn.microsoft.com/en-us/windows-server/identity/ad-cs/inspect-certificates-manage-certificate-stores).

### Public export and authenticity record

Export only the two individually selected candidates. In the certificate export wizard, select **No, do not export the private key**, then **DER encoded binary X.509 (.CER)**. Do not export a PFX/PKCS#12 file, an entire store, or any associated key. Alternatively, in an approved existing output directory, replace the two locators and run:

```powershell
$rootCert = Get-Item -LiteralPath 'Cert:\LocalMachine\Root\<ROOT_SHA1_STORE_LOCATOR>' -ErrorAction Stop
$issuingCert = Get-Item -LiteralPath 'Cert:\LocalMachine\CA\<INTERMEDIATE_SHA1_STORE_LOCATOR>' -ErrorAction Stop
Export-Certificate -Cert $rootCert -FilePath '.\CCC-ROOT-CA.cer' -Type CERT -NoClobber
Export-Certificate -Cert $issuingCert -FilePath '.\CCC-Enterprise-CA01.cer' -Type CERT -NoClobber
Get-FileHash -Algorithm SHA256 -LiteralPath '.\CCC-ROOT-CA.cer', '.\CCC-Enterprise-CA01.cer'
```

`Export-Certificate` exports no private key. With DER output, each file's SHA-256 must equal that selected certificate's `SHA256` above. `-NoClobber` protects existing files. [Microsoft public-certificate export](https://learn.microsoft.com/en-us/powershell/module/pki/export-certificate). Exporting public bytes is permitted for inspection but does not itself approve trust.

Keep the following evidence in the approved internal record; no passwords, keys or full device inventories are needed:

| Evidence | Current status |
| --- | --- |
| Windows verifier/date and managed-device provenance | User reported exports from a CCA-managed computer's Local Computer stores and an OK intermediate chain on 2026-10-08; agent has no Windows access; central deployment remains unverified |
| Root and intermediate exact store, subject/issuer/serial, validity/CA constraints and DER SHA-256 | Stores are user-reported above; uploaded bytes, public-only content and metadata/fingerprints independently inspected on the VM |
| Matching policy/enterprise physical-store result or authoritative managed-deployment record | Pending; record the applicable GPO/MDM/PKI reference, owner and date, or explicitly record that provenance is unavailable |
| Confirmation that these exact certificate fingerprints are the active approved chain for this DC | Pending authoritative institutional evidence; names, local installation and a match to the untrusted peer alone are insufficient |
| SHA-256 after transfer to the VM | Recorded above for both original DER files in the ignored review directory; temporary PEM derivatives verified without changing shared website files or system trust. Independent Windows-computed fingerprints have not been supplied for a separate transfer comparison. |

If managed-policy evidence cannot establish the chain's identity and intended use, the narrow certificate-owner question is: **“Are root SHA-256 `<value>` and issuing CA SHA-256 `<value>` the approved active CA chain for `CCCDC01.ccc.ccofc.edu:636`, and which authoritative policy/distribution record confirms them?”** Obtain that confirmation through a known CCA channel, not from the unauthenticated DC connection. If a different CA generation is approved, obtain its exact public certificate and fingerprint instead of selecting a same-named candidate automatically.

### Explicit application-specific VM verification procedure

The user explicitly authorized a diagnostic test against the supplied Windows-store exports while central provenance remains unverified. The executed result is recorded above. The repeatable procedure below does not establish production approval: verify hashes and record provenance/approval status separately. Reject private-key/PFX content, unexpected fingerprints, CA=false, expired/not-yet-valid certificates or ambiguous CA versions. Do not trust a server-presented root or fetch unknown AIA URLs as an automatic fallback.

The following commands are for a **new task-specific staging directory** containing only those public DER exports. First inspect the public inputs; compare every displayed fingerprint to the independently established DER fingerprint before continuing.

```bash
sha256sum CCC-ROOT-CA.cer CCC-Enterprise-CA01.cer
openssl x509 -inform DER -in CCC-ROOT-CA.cer -noout -subject -issuer -dates -fingerprint -sha256 -ext basicConstraints,keyUsage
openssl x509 -inform DER -in CCC-Enterprise-CA01.cer -noout -subject -issuer -dates -fingerprint -sha256 -ext basicConstraints,keyUsage
```

After the authenticity and metadata comparisons pass, this Bash subshell creates new public PEM derivatives and stops at the first failed command. It changes no system trust; `noclobber` prevents replacement of existing outputs. Incomplete outputs from a failed attempt are not accepted as a bundle or overwritten by a retry.

```bash
(
set -euo pipefail
set -o noclobber
openssl x509 -inform DER -in CCC-ROOT-CA.cer -outform PEM > CCC-ROOT-CA.pem
openssl x509 -inform DER -in CCC-Enterprise-CA01.cer -outform PEM > CCC-Enterprise-CA01.pem
openssl verify -check_ss_sig -CAfile CCC-ROOT-CA.pem -no-CApath -no-CAstore CCC-ROOT-CA.pem
openssl verify -CAfile CCC-ROOT-CA.pem -no-CApath -no-CAstore CCC-Enterprise-CA01.pem
cat CCC-ROOT-CA.pem CCC-Enterprise-CA01.pem > launchpad-ad-ca.pem
timeout 15s openssl s_client -connect CCCDC01.ccc.ccofc.edu:636 \
  -servername CCCDC01.ccc.ccofc.edu -verify_hostname CCCDC01.ccc.ccofc.edu \
  -verify_return_error -verify 8 -CAfile ./launchpad-ad-ca.pem \
  -no-CApath -no-CAstore -min_protocol TLSv1.2 -no_ticket -brief </dev/null
)
```

Self-signature and intermediate-chain verification establish cryptographic consistency, not institutional authenticity; independent approval evidence remains mandatory for production use. Diagnostic transport acceptance requires exit status 0, completed TLS, hostname match and `Verification: OK` under this explicit bundle. Record time/timezone, endpoint, certificate fingerprints/expiry, protocol/cipher, trust-bundle fingerprints and operator. A timeout or verification error is a failure. `-brief` avoids dumping TLS session secrets; no bind or application credentials are sent. This check does not test revocation status, user authentication, group policy, lookup permissions or session lifecycle.

Do not install these files, run `update-ca-certificates`, copy them into `/etc/ssl/certs`, change shared Nginx configuration or populate live Launchpad secrets. Supplied-bundle transport success is now recorded; future installation of an approved app-readable public CA bundle remains a separately scoped deployment action. Prepared host/CA installation settings are not promoted to approved production values by this diagnostic; CCA approval and a check under the eventual service identity remain pending.

## Candidate configuration

For the next isolated test, use [the controlled login preparation](#controlled-login-test-preparation) and its separate non-secret example. Deployment paths below remain future installation proposals.

Use [the VM environment example](../deploy/vm/launchpad.env.example). The user-authorized non-secret group DN is populated; remaining blank required values deliberately block startup. Supply secrets and private account mappings only through approved private custody, never this repository or a chat response. Populating the observed DN does not approve its use for Launchpad.

| Setting | Required value or decision |
| --- | --- |
| `LAUNCHPAD_AUTH_BACKEND` | `ad`; OIDC is a separate explicit backend, not a fallback on directory failure. |
| `LAUNCHPAD_AD_HOST` | `CCCDC01.ccc.ccofc.edu` passed hostname/chain validation under the supplied bundle. CCA approval of that trust and production use remain pending; prepared host remains blank. |
| `LAUNCHPAD_AD_PORT` | Exactly `636`. |
| `LAUNCHPAD_AD_CA_FILE` | Absolute readable PEM CA bundle containing approved directory trust. Candidate path `/etc/ssl/certs/launchpad-ad-ca.pem`, root-owned 0644. This file does not automatically add system-wide trust. |
| `LAUNCHPAD_AD_DOMAIN` | Approved DNS UPN suffix; confirm intended users' actual login convention. |
| `LAUNCHPAD_AD_BASE_DN` | Approved search boundary; exact DN required. |
| `LAUNCHPAD_AD_GROUP_DN` | The exact DN above, verified by the user's ADUC observation and populated in both examples. Owner approval for Launchpad eligibility remains pending. |
| `LAUNCHPAD_AD_GROUP_POLICY` | Explicit `direct` or `nested`, confirmed with the group owner and real test accounts. |
| `LAUNCHPAD_AD_IDENTITY_NAMESPACE` | Stable nonzero canonical lowercase UUID for the directory namespace, not a learner GUID and not a secret. |
| `LAUNCHPAD_AD_LOOKUP_USERNAME` | Candidate dedicated read-only lookup UPN. Account approval/provisioning, search scope and rotation owner remain pending. |
| `LAUNCHPAD_AD_LOOKUP_PASSWORD` | Lookup secret delivered privately; blank in the example. Never use a learner password for this setting. |
| `LAUNCHPAD_AD_REVALIDATE_SECONDS` | Proposed `60`, bounded to 1–300 seconds; owner must accept the lifecycle/outage policy below. |
| `LAUNCHPAD_AD_STATE_PATH` | `/var/lib/launchpad/ad-security.sqlite`; separately and explicitly provisioned persistent login-throttle state. |
| `LAUNCHPAD_SECRET_KEY` | Independent random signing secret of at least 32 characters. Do not reuse the older assistant's key. |

`/etc/launchpad/launchpad.env` remains root:root 0600 in a root-only 0700 directory, read by systemd. Put the public directory CA bundle in the separately readable trust location above; putting it inside that root-only configuration directory would prevent the non-root app from loading it. No CA is installed by repository preparation. The directory owner must approve trust material and its renewal process.

The approved operator must explicitly initialize the **new** throttle store before the service starts:

```bash
sudo -u launchpad /opt/launchpad/current/.venv/bin/python -B /opt/launchpad/current/scripts/manage_real_data.py initialize-ad-state --path /var/lib/launchpad/ad-security.sqlite
```

This is a future operator command, not an executed action. The separate learner database still uses `initialize --db ...` and its normal verification/recovery workflow. Missing/corrupt throttle state must refuse operation rather than silently reset limits. Include both stores in the approved persistence/recovery plan and do not point the throttle path at a learner database.

## Session lifecycle and removal

**Lookup option selected for preparation; operation pending CCA approval:** a least-privilege lookup account rechecks the authenticated immutable GUID for enabled status and approved group membership. CCA has not confirmed availability; no such account has been created or credential supplied. Approve its read/search scope, secret delivery and rotation, the proposed 60-second check interval and outage behavior before deployment. The interval remains configurable from 1–300 seconds and 60 is a proposal, not an approved maximum removal delay.

Positive eligibility may be cached for at most the configured interval. On the next protected request after a check is due, verified lookup must succeed. Directory denial, disabled/group-removed results, malformed responses, TLS failures and lookup outages reject that request and revoke all local sessions for that account; password authentication is required after recovery. Logout remains local and works during a directory outage. Restart clears the positive cache; there is no claim of background push revocation while a user is idle.

This is not instantaneous revocation or a guarantee of “60 seconds from an AD change.” AD replication visibility, requests already in flight and bounded network verification time affect the observed delay. The owner must approve the maximum end-to-end delay, test it against the selected DC and decide whether an emergency local disable/revoke procedure meets institutional policy. Default local session ceilings remain 30 minutes idle/eight hours absolute unless the reviewed implementation/configuration changes them; shorter lifecycle checks are an additional eligibility control. OIDC upstream disablement/group changes are not automatically governed by this AD mechanism.

### Minimum lookup permissions for Michael and the directory owner

Approve a dedicated identity permitted to bind over verified LDAPS and search only the required configured base for intended user objects. It needs enough read/filter visibility for `objectGUID`, enabled status (`userAccountControl`) and approved group membership (`memberOf`, including the relevant ancestor relationships if nested evaluation is selected). The query returns only `objectGUID`; directory-owner testing must establish the exact AD ACLs needed for those filters and group rules. Do not guess an OU-wide administrative grant to make a failed search succeed.

It needs **no domain/admin role, write, account creation, group modification, password reset or password-change privilege**. Approve account ownership, noninteractive use, lockout/rotation policy, delivery into the root-private Launchpad configuration and monitoring. Rotate the lookup secret through that process. Directory outage, lookup-account failure or denied search means due checks fail closed and revoke local sessions; restored connectivity requires fresh user sign-in. Learner passwords are never retained for these periodic checks. If CCA cannot supply the restricted identity, leave AD deployment blocked and revisit the lifecycle design explicitly.

## Login limits, storage and recovery

The candidate uses persistent limits of **50 sign-in attempts per 60 seconds globally** and **5 per canonical username per 300 seconds**, consumed before directory work, including successful attempts. This deliberately limits directory load and password attempts across workers/restarts without trusting caller-supplied client-IP headers. Under abuse the global limit may also deny legitimate sign-ins; name the monitoring/support owner and test the expected behavior before launch. Existing AD lockout policies still apply and must be checked with the directory owner.

Persistent attempt keys are HMAC-derived from the signing secret; raw usernames and passwords are not stored in the throttle database. Treat that file as private operational state, retain it across restarts and include it in restricted backups. Do not delete or reinitialize it to bypass throttling. A signing-key change changes the per-user HMAC namespace even if old global timestamps remain. After rotation, lost state or a stale-state restore, keep all login admission closed for **at least 300 seconds**, then verify both limit types before reopening. This closed-admission recovery gate is an operator responsibility, not an automatic CLI delay. Use a consistent SQLite backup or verified quiesced copy, never a raw copy while writers are active.

Learner-data restore follows [real-user operations](real_user_operations.md): new destination, preserved originals, revoked copied sessions, signing-key rotation and reconciliation of local disables/assignments and current directory eligibility before reopening. Keep the namespace stable. Treat the learner store and throttle store as distinct artifacts; a learner snapshot alone is not a complete AD-mode recovery package. The exact coordinated restore and post-rotation throttle checks remain a hosted recovery requirement.

## Controlled work-study website test

**Enrollment update, 2026-10-09:** the operator supplied and authorized one designated student's ADUC-verified identity, reported adding that student directly to the existing group, selected `direct` membership for this test, and supplied the containing OU as a proposed narrow search base. That learner is now enrolled offline in fresh `work-study-01` storage as **Test Learner A**, with no existing progress attached. Identifying UPN/GUID/user DN/OU evidence and the enrollment verification record are retained only in private Git-ignored inputs. The generic example stays blank for participant-specific directory settings. No additional learner identity input is missing for this run. These operator observations are not a live directory query or successful authentication.

The [dated verification record](vm_verification.md#designated-controlled-test-enrollment-2026-10-09) supersedes the earlier unexecuted-enrollment state below for this run only. Do **not** rerun initialization or enrollment for `work-study-01`; use `scripts/manage_controlled_test.py verify --run work-study-01` for read-only storage validation. Authentication, institutional AD CA approval and trusted HTTPS activation remain pending. The operator now reports Michael approved using the current production certificate until renewal and authorized restricting its key-bearing copies; Michael is arranging renewal with Jordan next week. Both controlled-test and maintenance vhosts may retain the current paths after that remediation and configuration/HTTPS validation. A replacement certificate is not a prerequisite. The [activation record](vm_verification.md#controlled-test-activation-authorization-2026-10-09) distinguishes authorization from executed changes.

**Prepared 2026-10-09; not started or deployed.** This explicit mode lets designated work-study students test the website with their own verified AD identities and invented training answers, without a background lookup account. It does not reuse the operator's Pilot A identity, its private JSON, an existing dataset or any existing progress. Production remains `LAUNCHPAD_AD_SESSION_POLICY=revalidate`; missing lookup configuration still refuses production startup. The production `start_real.py` launcher rejects `controlled_test` outright.

Select `LAUNCHPAD_AD_SESSION_POLICY=controlled_test` only through the new isolated configuration. The application requires AD real-user mode, a new marked dataset in `work/controlled-work-study/<run-id>`, its own immutable namespace, persistent throttle storage and explicit learner/mentor enrollment. Wrong paths, symlinks/hard links, non-private permissions, mismatched dataset markers, foreign identity namespaces and unbound imported learners are rejected. There is no automatic enrollment from group membership and no shared learner selector. The setting is not a response to a failed lookup: no automatic mode switch exists.

### Session behavior and limits

- Every sign-in performs certificate- and hostname-verified LDAPS, enabled-account and the configured direct/nested group check, then resolves the returned immutable GUID against explicit local enrollment. No password is stored for later use. Existing sign-in throttling and CSRF checks remain active.
- The proposed test policy is **900 seconds (15 minutes) absolute from sign-in**, enforced in the server session store and on reads. Activity does not extend it, there is no remember-me option, and the test mode rejects an older session after 900 seconds even if that row originally had a longer lifetime. Expiry requires fresh AD authentication; there is no silent renewal.
- **AD disablement or group removal does not immediately end an existing test session.** There are no background directory rechecks in this mode. Access can persist until the 15-minute expiry or earlier local logout, account disablement or session revocation. A directory outage likewise need not interrupt an existing valid session, but fresh sign-in fails. Changes must be visible on the selected DC for the next sign-in to detect them. Checks occur on requests; they do not erase an already displayed page or cancel work already authorized in flight.
- Saved assessments, scores, module/checklist completion, submitted practice answers and other database-backed progress survive expiry and a later sign-in. An expired POST receives 401 before saving anything and is not automatically replayed after login. Typed but unsubmitted text has no autosave guarantee; browser Back may or may not retain it. Unfinished guided-practice steps live in the browser session and must be restarted after sign-in; already recorded completion remains saved. Use invented text only and submit short activities before the limit.
- Mentors can only read explicitly assigned learners. They cannot submit training answers or edit progress. Emergency local revocation still works without directory access. The 15-minute proposal is for this controlled test, not approval of a production offboarding policy.

### Inputs for a new participant

For the enrolled `work-study-01` participant, identity, direct-membership policy and proposed search base have been supplied privately as recorded above. The table is the reusable checklist for another explicitly authorized participant; it is not a request to supply those values again or enroll additional users.

| Input | Required action |
| --- | --- |
| Work-study student's identity | Independently verify **that student's** full UPN and canonical objectGUID on the same user object. Keep the mapping private. Use a neutral display label such as `Test Learner A`; do not use the operator's Pilot A inputs. |
| Directory scope | Fill the student's observed UPN suffix, approved user search base and explicit `direct`/`nested` group policy. The staged CA/DC/group DN are prepared; actual student authentication/group eligibility is unverified. No AD membership changes are part of this procedure. |
| Browser HTTPS | Selected URL: `https://lesliec.ccaurora.edu/`. The [controlled Nginx proposal](vm_deployment.md#controlled-browser-test-routing) supplies verified HTTPS to the loopback backend. The existing browser certificate validates but expires October 28, 2026; Michael has approved reuse until renewal, with key-bearing-file permission remediation required before credentials are entered. Use a separate operator-private backend key; the AD CA bundle is neither website nor backend TLS trust. |
| Controlled use | Agree on designated participants, invented answers, the proposed 15-minute limit, facilitator/local-revocation contact and handling of these restricted test files. Real account GUIDs remain personal data even with invented training answers. Institutional CA approval remains separately pending. |

The launcher binds **only `127.0.0.1:8443` on the VM**. The prepared route is browser → existing Nginx HTTPS/443 → certificate-verified HTTPS loopback/8443. Students use the normal URL without a port, tunnel or certificate bypass. Do not open 8443 in a firewall or bind it to a public interface. Live Nginx/DNS/routing remain untouched; the current hostname returns the old route's 502, not Launchpad. The [routing runbook](vm_deployment.md#controlled-browser-test-routing) includes the separate backend certificate, exact hostname-removal patch, validation and closed-access rollback. The retirement and controlled-test activation decisions are settled; privileged execution, certificate permission remediation and endpoint validation remain. No password should be entered until those checks pass.

### Exact future operator commands

These are the reusable provisioning commands. **`work-study-01` has now been initialized and its sole designated learner enrolled offline; do not repeat those mutations.** For that run, skip to read-only verification and the still-pending HTTPS setup. A different participant needs a new authorized run ID, not a reset of this dataset. Use the already installed validation Python shown below (the project `.venv` lacks `ldap3`/`pyasn1`). If that temporary interpreter is removed, choose an approved environment containing `requirements-real.txt`; do not fall back to an incomplete environment. Run one step at a time and stop on failure.

```bash
cd /opt/project/ITWorkStudyLaunchpad
LP_TEST_PY=/tmp/launchpad-real-validation-6qhv4cbn/venv/bin/python
LP_TEST_RUN=work-study-01
"$LP_TEST_PY" -B scripts/manage_controlled_test.py initialize --run "$LP_TEST_RUN"
```

Initialization refuses an existing run and creates only empty `learners.sqlite`, separate `ad-security.sqlite`, the matching dataset marker, a new random namespace, a stable private signing key and incomplete `config.json`. The run parent/directory are 0700 and files 0600 under the narrowly Git-ignored `work/controlled-work-study/`. It creates no learner, copies no record and reads no Pilot A input. Do not replace an existing run or regenerate its signing key to bypass throttling.

Edit only the new run's `work/controlled-work-study/work-study-01/config.json`, preserving its generated namespace, paths and `controlled_test` policy. These are the **four previously blank settings**; one is now resolved in the [committed example](../deploy/controlled-test.example.json):

| Setting | Value / how to obtain the remaining input |
| --- | --- |
| `LAUNCHPAD_TRUSTED_HOSTS` | Now prepared as `lesliec.ccaurora.edu`, without scheme or `:8443`. No hostname decision remains. An older private run, if any, must be reviewed explicitly; examples do not silently rewrite it. |
| `LAUNCHPAD_AD_DOMAIN` | Read the suffix after `@` from the **student's** verified ADUC `userPrincipalName`. `ccc.ccofc.edu` is already observed for the operator, but does not establish the student's suffix. If the student has that same suffix, use `ccc.ccofc.edu`; otherwise verify the different suffix with the directory owner. Still blank pending that observation. |
| `LAUNCHPAD_AD_BASE_DN` | Read the student's `distinguishedName` in ADUC and have the directory owner identify the permitted user search boundary containing that object. Do not infer a user OU from the access group's DN or assume domain-wide search. A single-user DN can be proposed for this one-learner test if its scope and query behavior are approved/verified; no guessed DN is supplied. |
| `LAUNCHPAD_AD_GROUP_POLICY` | Obtain the group owner's explicit choice `direct` or `nested`, plus approval to use this existing group for the controlled test. An ADUC membership listing does not choose the policy. Still blank. |

The student's full UPN and canonical `objectGUID`, verified on the same ADUC user object, are the identity inputs. Keep them private; the enrollment prompt uses the GUID and an invented label. A user DN is additional evidence for selecting the search base, not a substitute identity key. The existing `CCCDC01.ccc.ccofc.edu:636`, supplied public CA bundle and exact verified `CCA_Leslie_Project` DN are already populated; do not request them again. Actual student eligibility, credentialed authentication and institutional CA approval remain separate pending checks. No background lookup identity or password is needed for this mode.

Runtime JSON is an allowlist: do not add passwords, lookup credentials, signing secrets, separate UPN/GUID identity fields or arbitrary Gunicorn settings. Any approved single-user search DN is itself personal information and belongs only in this private, Git-ignored configuration, never a committed example. The private generated `signing-key.txt` is an application secret, not anyone's AD password.

Enroll the separately verified student using the hidden GUID and invented-label prompts, then validate the isolated mapping:

```bash
"$LP_TEST_PY" -B scripts/manage_controlled_test.py enroll --run "$LP_TEST_RUN" --role learner
"$LP_TEST_PY" -B scripts/manage_controlled_test.py verify --run "$LP_TEST_RUN"
```

At the first prompt enter **the student's verified objectGUID**, not a name, UPN, SID or the operator's GUID. At the second enter `Test Learner A` or another invented label. No password is requested by enrollment. Record the reported internal account/learner IDs privately. This creates new progress only; never use `bind-existing` or a production database for this test.

Prepare the separate backend certificate using the [routing runbook](vm_deployment.md#controlled-browser-test-routing). Its key must be a private 0600 regular file owned by the operator, and the certificate file must contain public PEM certificates only. First run without `--serve` to validate locally without a listener or AD bind:

```bash
"$LP_TEST_PY" -B scripts/start_controlled_test.py --run "$LP_TEST_RUN" \
  --certfile "$PWD/work/controlled-work-study/$LP_TEST_RUN/tls/backend.pem" \
  --keyfile "$PWD/work/controlled-work-study/$LP_TEST_RUN/tls/backend.key"
```

After explicit startup/cutover authorization and completion of the routing prerequisites, the corresponding manual startup command is:

```bash
"$LP_TEST_PY" -B scripts/start_controlled_test.py --run "$LP_TEST_RUN" \
  --certfile "$PWD/work/controlled-work-study/$LP_TEST_RUN/tls/backend.pem" \
  --keyfile "$PWD/work/controlled-work-study/$LP_TEST_RUN/tls/backend.key" \
  --serve
```

The launcher reuses one-worker Gunicorn and sanitized logging, fixes the loopback listener and TLS minimum, and disables forwarded-scheme/proxy overrides. It loads the application signing key privately rather than placing it in a command argument. The implementation follows the official [custom application](https://gunicorn.org/custom/) and [SSL context settings](https://gunicorn.org/reference/settings/#ssl-context); local preflight checks key/certificate loading, not browser trust or reachability. It does not install a service or change Nginx. The student enters their own UPN/password only into the verified HTTPS sign-in page, uses invented answers, and signs in again after expiry. Closing this manual server does not delete its dataset.

For a separately designated mentor, repeat `enroll --role mentor` with that mentor's verified GUID, then grant only the intended learner using the existing offline CLI. Emergency revocation/disablement commands use the internal IDs reported during enrollment:

```bash
"$LP_TEST_PY" -B scripts/manage_real_data.py grant-mentor \
  --db "/opt/project/ITWorkStudyLaunchpad/work/controlled-work-study/$LP_TEST_RUN/learners.sqlite" \
  --account-id '<mentor-account-id>' --learner-id '<student-learner-id>'
"$LP_TEST_PY" -B scripts/manage_real_data.py revoke-sessions \
  --db "/opt/project/ITWorkStudyLaunchpad/work/controlled-work-study/$LP_TEST_RUN/learners.sqlite" \
  --account-id '<student-account-id>'
"$LP_TEST_PY" -B scripts/manage_real_data.py disable-account \
  --db "/opt/project/ITWorkStudyLaunchpad/work/controlled-work-study/$LP_TEST_RUN/learners.sqlite" \
  --account-id '<student-account-id>'
```

These are separate optional assignment/emergency actions, not commands to run as part of every startup. Do not grant access to all existing group members. Keep all files restricted and preserve them pending the agreed retention decision; this preparation adds no automatic deletion or migration.

## Standalone initial-login diagnostic

**Prepared 2026-10-09; no credentialed test has been run.** The user selected a one-attempt diagnostic using their own AD account before the full application test. No existing standalone CLI was found. [The diagnostic wrapper](../scripts/diagnose_ad_login.py) reuses the existing `configure_ad()` and `authenticate_ad()` adapter; it does not create the Launchpad app, start a listener, enroll an account, touch SQLite, create a session or call background revalidation. The earlier [full application helper](../scripts/controlled_ad_login.py) remains separate because it deliberately tests sessions and requires a lookup account.

The wrapper reads Pilot A's existing private `work/ad-login-test/pilot-a-identity.local.json`, verifies its ownership/permissions and canonical UPN/GUID, and uses the pinned public bundle at `work/ad-ca-review/launchpad-ad-ca.pem`. Identifiers are not displayed or added to command arguments. It fixes the DC to `CCCDC01.ccc.ccofc.edu:636` and the group to `CN=CCA_Leslie_Project,OU=CCA_Groups_Security_User,OU=CCA,DC=ccc,DC=ccofc,DC=edu`; URLs, different ports, referrals and plaintext fallback are not selectable.

| Input / requirement | Current status for this diagnostic |
| --- | --- |
| Pilot A UPN/GUID | Supplied and user-verified in ADUC; private local input is ready. No further learner identifier or enrollment is needed. |
| Explicit CA bundle | Staged bundle hash matches the successful hostname/chain-validated LDAPS transport check. Each diagnostic revalidates TLS before transmitting the password. The user requested this scoped diagnostic against that supplied bundle; institutional approval of the CA fingerprints remains separately pending and is not established by diagnostic success. |
| `--base-dn` | **Missing:** approved user search-base DN that contains Pilot A. Supply it explicitly; the group OU and UPN suffix do not establish an approved search base. |
| `--group-policy` | **Missing:** choose `direct` or `nested` for this diagnostic. `direct` requires the group on the user's direct membership; `nested` uses AD's transitive membership match. A diagnostic result does not approve Launchpad eligibility or set its eventual membership policy. |
| Lookup account | **Not required for this diagnostic.** No lookup credential is read or prompted; Pilot A is never used as the application's background identity. |
| Enrollment namespace / app storage | **Not required for this diagnostic.** A disposable in-memory UUID satisfies the adapter's issuer format and is discarded. It is not an enrollment namespace or persistent mapping. |
| Python environment | Existing validation environment `/tmp/launchpad-real-validation-6qhv4cbn/venv/bin/python` has the necessary dependencies. The project's `.venv` currently lacks `ldap3`/`pyasn1`; no packages were installed for this preparation. If the temporary validation environment is removed, stop and select an approved environment with `requirements-real.txt`. |

Replace both angle-bracket placeholders with confirmed values before using either command. An incomplete command must refuse before a password prompt. First perform local preflight only; without `--execute`, no password is collected and no directory connection is opened:

```bash
/tmp/launchpad-real-validation-6qhv4cbn/venv/bin/python -B /opt/project/ITWorkStudyLaunchpad/scripts/diagnose_ad_login.py \
  --base-dn '<approved-user-search-base-DN>' \
  --group-policy '<direct-or-nested>'
```

Once the two missing scope/membership inputs are supplied, the human operator runs this requested diagnostic once from a trusted interactive terminal:

```bash
/tmp/launchpad-real-validation-6qhv4cbn/venv/bin/python -B /opt/project/ITWorkStudyLaunchpad/scripts/diagnose_ad_login.py \
  --base-dn '<approved-user-search-base-DN>' \
  --group-policy '<direct-or-nested>' \
  --execute
```

Enter only Pilot A's password at the hidden terminal prompt. Do not enter it in chat, command arguments, environment variables or a file, or run from a recorded terminal, debugger, CI, shell tracing or redirected streams. The wrapper refuses a non-TTY or password-echo fallback, disables its diagnostic logging/core dumps, keeps the password only in process memory, and stops without retrying on failure. It has a 30-second outer execution limit after the prompt in addition to the adapter's connection/read/search timeouts. Only the first transport candidate may be attempted; no alternate-address retry follows a connection/TLS failure. Cleanup attempts LDAP unbind and closes any remaining socket, including failed-open/unbind-error paths. Process exit ends the diagnostic.

The adapter performs verified TLS, one learner bind and an enabled-user/group-filtered search on that same connection. Only `objectGUID` is requested; the wrapper compares the canonical returned GUID with Pilot A's private expected GUID before reporting success. A generic failure does not distinguish wrong password, permission/search-scope problems, missing membership, GUID mismatch or transport failure; it must not be recorded as proof of any one cause. A successful diagnostic verifies only the selected connection/authentication/GUID/group check against the supplied bundle. It does not verify enrollment, application sessions, background revocation, browser behavior, hosted access or production eligibility approval.

The standalone tool has no application login-throttle database. Its one-attempt limit is per invocation: **do not loop it, repeatedly test bad passwords or automatically rerun a failure.** Follow CCA's account-lockout rules and review any failure before another attempt. Retain only neutral outcome/date evidence, never credentials or directory response dumps. The application's persistent login limits, lookup-account requirement and background session checks are unchanged.

## Controlled login test preparation

This older procedure specifically tests the **production `revalidate` session policy** with Pilot A and a separate lookup identity. For the requested student website test without background lookup, use [controlled work-study mode](#controlled-work-study-website-test) above and the student's own identity; do not use this older helper/configuration for that mode.

**Preparation and learner designation only; enrollment and credentialed test execution remain unperformed.** No person has been enrolled, no test database has been initialized, no password has been collected and no credentialed directory connection has been attempted. The public bundle preservation above is complete. These three statuses are independent:

| Gate | Status |
| --- | --- |
| LDAPS transport against the supplied CA bundle | **Passed:** hostname and chain validation, TLS 1.3, exact endpoint and fingerprints recorded above |
| Institutional trust / use approval | **Pending:** centrally managed provenance and CCA approval of those fingerprints for this DC are not established |
| Actual AD authentication and Launchpad login/session authorization | **Pending:** no user or lookup bind; no live enrollment/eligibility/recheck outcome |

### Scope and lookup-account dependency

The proposed full application test is one human-operated, in-process Flask-client login with designated learner **A**, against the actual AD adapter and an explicitly new isolated dataset. It follows the standalone diagnostic above and exercises the application's login/CSRF/session handlers without opening a web listener, deploying a service, changing Nginx, using shared website keys or exposing an HTTP password form. `https://launchpad-controlled.invalid` is a test-client origin only; it is not DNS, hosting or proof of browser HTTPS. The [controlled helper](../scripts/controlled_ad_login.py) must be run from a trusted interactive terminal only after the missing decisions and separate execution authorization are recorded.

**Learner designation confirmed by the user, 2026-10-08; identity supplied 2026-10-09:** A will be the user's own existing AD account, enrolled only in the isolated test dataset with role `learner` and label `Pilot A`. The user reports verifying the exact UPN and `objectGUID` on their own ADUC user object. Both values passed offline application-format checks and are retained only in `work/ad-login-test/pilot-a-identity.local.json` (Git-ignored; parent 0700, file 0600). This is user-observed evidence, not an agent-performed directory query or authentication. No further learner identifier is missing. It does not authorize directory changes, assign a mentor/admin role, approve the group's Launchpad use or execute enrollment/login. The user's account must not be configured as the persistent background lookup identity.

**An approved lookup account is required for this production-revalidation application test.** `configure_real_security()` rejects `revalidate` AD startup without nonempty lookup username/password, a 1–300 second recheck interval and an existing validated throttle store. Initial sign-in binds with A's password; the lookup identity is used when the eligibility cache is empty or due. The prepared test recreates the application in-process with the same ephemeral signing key and copied cookie held only in memory, then requests A's page to require one fresh lookup. This checks the cold-cache path; it does not establish an actual hosted process-restart or timed-offboarding result.

Leave `LAUNCHPAD_AD_LOOKUP_USERNAME` blank until a separately approved lookup identity is supplied; do not fill it with the user's UPN. The helper rejects a matching learner/lookup UPN, including case variants, before GUID/password prompts or any bind. This local comparison cannot detect distinct aliases for the same directory object: the owner must independently confirm that the lookup account's `objectGUID` differs from A's and approve its restricted read/search scope. A successful eligibility lookup returns A's GUID; it does not prove the lookup binder's GUID. No session check is skipped if the separate account is unavailable.

The [standalone initial-login diagnostic](#standalone-initial-login-diagnostic) now provides the requested lower-level `configure_ad()` / `authenticate_ad()` check of one user's bind, enabled/group eligibility and GUID without a lookup account. It does **not** check enrollment, web login, sessions, read-only mentor access or the application's persistent login throttle. It is a separate diagnostic and does not satisfy the full application's lookup dependency. Do not alter the app to omit lookup credentials, reuse A's password for rechecks, or borrow the old assistant's credentials.

### Exact non-secret test configuration

The [controlled-test JSON example](../deploy/ad-login-test.example.json) is intentionally incomplete and cannot start a test. It contains no password or signing secret. After approval, an operator copies and fills it in the Git-ignored private run directory; do not source a deployment `.env` or populate a password field in JSON.

| Setting | Exact prepared value / missing input |
| --- | --- |
| `LAUNCHPAD_REAL_MODE` / `LAUNCHPAD_DEMO_MODE` / `LAUNCHPAD_PILOT_MODE` | JSON `true` / `false` / `false` |
| `LAUNCHPAD_AUTH_BACKEND` | `ad`; no OIDC fallback/registration |
| `LAUNCHPAD_TRUSTED_HOSTS` | `launchpad-controlled.invalid`, in-process requests only |
| `LAUNCHPAD_AD_HOST` / `LAUNCHPAD_AD_PORT` | `CCCDC01.ccc.ccofc.edu` / `636`; transport verified under the supplied bundle; institutional approval pending |
| `LAUNCHPAD_AD_CA_FILE` | `/opt/project/ITWorkStudyLaunchpad/work/ad-ca-review/launchpad-ad-ca.pem`; verify the recorded bundle hash |
| `LAUNCHPAD_AD_GROUP_DN` | `CN=CCA_Leslie_Project,OU=CCA_Groups_Security_User,OU=CCA,DC=ccc,DC=ccofc,DC=edu`; observed existence/DN do not approve Launchpad eligibility |
| `LAUNCHPAD_AD_DOMAIN` | Pilot A's UPN suffix is now confirmed by the user's ADUC observation and retained in the private input file; use it for the planned isolated configuration. This does not approve all institutional login conventions. A short input is treated as a UPN local part, not an arbitrary sAMAccountName. `DOMAIN\\user` is unsupported. |
| `LAUNCHPAD_AD_BASE_DN` | **Missing:** approved user search base; do not infer it from the group's OU or use a broad search by default |
| `LAUNCHPAD_AD_GROUP_POLICY` | **Missing:** owner choice of `direct` or `nested`, including approval to use this group for the test |
| `LAUNCHPAD_AD_IDENTITY_NAMESPACE` | **Missing:** one approved, nonzero canonical lowercase UUID retained for the isolated test's AD issuer; no automatic reuse/reinterpretation of OIDC IDs |
| `LAUNCHPAD_AD_LOOKUP_USERNAME` | **Missing:** separate approved read-only lookup UPN; never A's account or an alias of it. Availability, distinct directory identity and permissions have not been established |
| `LAUNCHPAD_AD_REVALIDATE_SECONDS` | Proposed `60`, configurable 1–300; owner must accept the test interval and outage behavior |
| `LAUNCHPAD_DATA_DIR` | `/opt/project/ITWorkStudyLaunchpad/work/ad-login-test/<approved-run-id>`; new private 0700 directory, not an existing learner-data path |
| `LAUNCHPAD_DB_PATH` | `<that-run-directory>/learners.sqlite`; explicitly provisioned new real-schema dataset only |
| `LAUNCHPAD_AD_STATE_PATH` | `<that-run-directory>/ad-security.sqlite`; explicitly provisioned separate new throttle store only |

The learner's exact UPN and canonical AD objectGUID are now supplied and validated, with their user-reported ADUC provenance retained in the private input file. That file is an operator reference for future enrollment/prompts, **not** the helper's strict runtime `--config` file; do not add learner identifiers to the committed example or pass this reference file as runtime configuration. Its status is `prepared_not_enrolled`, its progress policy permits only a new isolated dataset, and its lookup identity, test namespace and planned database path remain unset. The helper prompts privately for A's full UPN, expected canonical GUID and both passwords; the lookup UPN comes from the separate non-secret runtime configuration. It generates a random signing key in process memory. Passwords and the signing key never belong in either JSON file. No stored learner password, lookup password file, shell export or secret command argument is needed for this controlled test. The future deployment runbook's protected credential file is **not** used for this test.

### Verify learner A's identity — read-only preparation

**Current status, 2026-10-09:** the user has completed the required UPN/GUID observation in ADUC and supplied those values privately for local preparation. The instructions below are retained for later re-verification; no repeat lookup is needed simply to prepare these enrollment inputs. User DN, exact observation DC and time were not supplied and have not been invented. They are optional supporting provenance, not missing learner identity or prerequisites for the enrollment API.

On the user's CCA-managed Windows computer, open their known account in ADUC rather than choosing a display-name match. Read the full **User logon name** (including its suffix) on the Account tab. With **View → Advanced Features** enabled, inspect that same object's Attribute Editor for `userPrincipalName`, `distinguishedName` and `objectGUID`; close with Cancel and change no values. The user DN is distinct from the already verified group DN. Record the DC, observation time and method privately. This Windows read is not a Launchpad password test or proof of eligibility approval.

Use a canonical GUID string (`xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx`, lowercase, no braces). If ADUC displays binary/hex bytes rather than a GUID string, do not transcribe the bytes or guess their order. Where the ActiveDirectory PowerShell module is already available, this optional single-user read converts the typed `ObjectGUID` for you. It accepts the exact user DN from ADUC, avoids a name search or roster enumeration, and uses the existing Windows session without a password argument or prompt. Run from a normal filesystem location, not an AD provider drive. If the module or permission is unavailable, stop and ask the directory owner for these three attributes; do not install tools or supply alternate credentials for this preparation. See [Microsoft's Get-ADUser documentation](https://learn.microsoft.com/en-us/powershell/module/activedirectory/get-aduser?view=windowsserver2025-ps) for `-Identity`, `-Properties` and default credentials.

```powershell
Get-Command Get-ADUser -ErrorAction Stop | Out-Null
$launchpadUserDn = Read-Host 'Exact distinguishedName of your own user object from ADUC (not a password)'
$launchpadUser = Get-ADUser -Identity $launchpadUserDn -Server 'CCCDC01.ccc.ccofc.edu' -Properties userPrincipalName -ErrorAction Stop
[pscustomobject]@{
    DistinguishedName = $launchpadUser.DistinguishedName
    UserPrincipalName = $launchpadUser.UserPrincipalName
    ObjectGUID = $launchpadUser.ObjectGUID.ToString('D').ToLowerInvariant()
} | Format-List
$launchpadUser = $null
$launchpadUserDn = $null
```

These Windows instructions have not been executed here. Keep output in the restricted test-designation record; do not paste account identifiers into a public issue, portfolio, committed example or chat. No password is requested. The Windows lookup uses the management client's existing authentication; it does not exercise the VM's LDAPS adapter or establish the separate lookup account's availability.

Before enrollment, check that the UPN/GUID refer to the user's intended account, the GUID is nonzero, and the configured UPN suffix matches the observed UPN. A blank UPN, unexpected identity or mismatch is a stop condition, not a reason to derive a login from a name, email or S-number. The account's DN may inform an owner-approved search scope but does not automatically authorize an entire OU/domain search. Existing group membership remains user-observed; group-use approval and direct/nested policy remain pending.

The restricted designation record needs label `Pilot A`, verified UPN/GUID, role `learner`, evidence source and reporting date. A user DN or observed DC/time may be retained if available, but is not required for enrollment. Approved group policy, test namespace and run path are separate configuration decisions; leave unresolved values unset. Do not collect other members or passwords. The account mapping stores the test issuer plus GUID, role and synthetic label; UPN/user DN are not substituted for the immutable subject. Treat these test records as real account identifiers even though training answers will be synthetic.

### Designated accounts and enrollment plan — do not run now

The first run needs only learner **A**, now designated as the user's own AD account, with approved eligibility, independently verified canonical objectGUID, local role `learner` and synthetic display label `Pilot A`. Their IT employment and AD permissions grant no additional Launchpad role. The user's observed group membership does not supply a UPN/GUID, authorize testing automatically or enroll their account. The separate lookup identity is not enrolled as a learner or mentor and needs only the already documented read/search scope.

For later separately approved isolation tests, designate **B** as a distinct learner, **M** as a read-only mentor assigned only to A, and **U** as an eligible AD identity with no local enrollment. No existing group roster is imported. Denied/nonmember/disabled cases use owner-designated pre-existing test identities; this plan does not disable accounts or change membership. Do not create a live lockout by repeatedly submitting bad passwords.

After identity verification and explicit enrollment authorization, select an approved Python environment with `requirements-real.txt` and create a new private run directory. Confirm the staging parent is an owned real directory, not a symlink. Use one new approved namespace UUID for this isolated test and copy that exact value to the non-secret configuration and enrollment issuer; it is not the learner's objectGUID and must not reuse an OIDC identifier. These are future commands, not actions performed in this preparation; replace all placeholders and run one step at a time, stopping on any error. The run-directory creation deliberately refuses an existing run rather than reusing any data:

```bash
umask 077
mkdir -p -m 700 -- '/opt/project/ITWorkStudyLaunchpad/work/ad-login-test'
mkdir -m 700 -- '/opt/project/ITWorkStudyLaunchpad/work/ad-login-test/<approved-run-id>'
python -B scripts/manage_real_data.py initialize --db '/opt/project/ITWorkStudyLaunchpad/work/ad-login-test/<approved-run-id>/learners.sqlite'
python -B scripts/manage_real_data.py initialize-ad-state --path '/opt/project/ITWorkStudyLaunchpad/work/ad-login-test/<approved-run-id>/ad-security.sqlite'
python -B scripts/manage_real_data.py enroll --db '/opt/project/ITWorkStudyLaunchpad/work/ad-login-test/<approved-run-id>/learners.sqlite' --issuer 'urn:launchpad:ad:<approved-test-namespace-uuid>' --role learner
python -B scripts/manage_real_data.py verify --db '/opt/project/ITWorkStudyLaunchpad/work/ad-login-test/<approved-run-id>/learners.sqlite'
python -B scripts/manage_real_data.py verify-ad-state --path '/opt/project/ITWorkStudyLaunchpad/work/ad-login-test/<approved-run-id>/ad-security.sqlite'
```

Enrollment prompts for the verified GUID and synthetic display label, **not a password**. Use a real terminal with hidden input; stop if it warns that input cannot be hidden. Record the reported new internal account ID privately alongside the verified mapping. Never use `bind-existing`, a production/default database, display-name matching or an existing OIDC record. Only later enroll B/M under separate approval; M requires an explicit A-only assignment through the existing CLI. No enrollment command is run by the controlled helper.

Confirm the run directory is 0700 and both database files are 0600, owned by the executing operator. The existing Git ignore rule covers `work/ad-login-test/`; Git exclusion is not an access-control or retention policy. Only after these checks, prepare a new private `config.json` from the non-secret example, retaining missing settings as blank until verified. Both configured database paths must point into this one run directory; preserve all existing databases. Offline enrollment itself needs no password, directory bind or lookup account, but it does not make the full test runnable without the approved separate lookup identity. The private staging parent now contains only the prepared identity reference; no execution run directory, account mapping or database has been created.

### Password handling and exact first-run sequence

The owner approves the CA fingerprints, target/scope, A's identity/group policy, lookup account/permissions, lockout limits and one test window before execution. The helper's `--execute` flag is an operator acknowledgment, not proof of institutional approval. Do not run it from Codex tools, a recorded session, CI, a debugger, shell tracing, redirected stdin, an HTTP recorder or a browser HAR capture. Do not send passwords through this chat or its tools.

1. Confirm originals and staged bundle hashes, completed non-secret JSON, new isolated stores and A's explicit enrollment. Do not launch `app.py`/`start_real.py`, Gunicorn or a web server for this test.
2. A human runs the helper in a trusted terminal. It must refuse non-TTY/password-echo fallback, unsafe configuration/paths and missing isolated storage. Both lookup and learner passwords are entered with hidden prompts and held only in memory. No password environment variables, files, arguments or request/LDAP debug logs are used.
3. The helper generates an in-memory signing key, uses the real login/CSRF handlers and permits one learner credential submission. Before reading any protected learner page, it compares the authenticated server-session account to A's independently verified GUID and expected learner role; a mismatch revokes the new session and fails. It then checks A's own page and denied supervisor access, recreates the app for one lookup, and checks logout and old-cookie rejection. A 30-second outer execution deadline after prompts bounds DNS/LDAP work; timeout is failure. It prints only bounded step/status results, never credentials, cookies, response bodies, identity records or exception tracebacks. It stops at the first failure without retrying.
4. Save only the sanitized outcome, time, source/configuration version and neutral test label in the restricted test record. Exit the process after the attempt; no learner or lookup password is retained for reuse. Do not claim browser, real HTTPS ingress, timed revocation or hosted restart acceptance from this in-process result.

Future invocation, once authorized and configured:

```bash
python -B scripts/controlled_ad_login.py --config '/opt/project/ITWorkStudyLaunchpad/work/ad-login-test/<approved-run-id>/config.json' --execute
```

The helper uses an ephemeral signing key; a new invocation changes the throttle's keyed account namespace. **Do not repeatedly rerun it to bypass limits.** Keep login admission closed for at least 300 seconds between runs and follow any stricter CCA lockout/test-window rule. Persistent throttle storage is not reset or removed. A first-attempt failure is reviewed before another run; live negative/lockout testing requires its own approved plan.

### Expected outcomes — requirements, not live results

| Scenario | Expected implemented result | Planned evidence |
| --- | --- | --- |
| Anonymous protected read/write | 401; no learner data | Existing isolated tests; later scoped live test |
| Approved A, valid AD credentials/eligibility and active explicit enrollment | Login 302; own learner page 200 | First controlled helper |
| A requests supervisor view | 403 | First controlled helper |
| Learner and lookup UPN match, including case variants | Helper refuses before GUID/password prompts or directory calls; isolated stores unchanged | Synthetic regression; distinct-alias identity separation still needs independent directory verification |
| App recreated with A's existing cookie and empty eligibility cache | One approved lookup verifies the same GUID; own page 200 | First controlled helper; no hosted-restart claim |
| POST logout with CSRF; reuse old cookie | 302 then 401 | First controlled helper |
| Valid AD user without enrollment, wrong password, disabled/nonmember identity or initial directory failure | Generic 401; no automatic account/record | Existing isolated tests; owner-designated live negatives only later |
| Missing/foreign-origin CSRF | 400 before directory authentication | Existing isolated tests; no bad-password attempts needed |
| Forged learner/role fields, cross-learner access | Denied without ownership change; applicable forged writes 403 | Existing isolated tests; later A/B verification |
| M reviews assigned A / unassigned B / attempts training write | 200 / 404 / 403 | Existing isolated tests; later designated M/A/B verification |
| Due lookup denied/unavailable | 503 before training write; all A sessions revoked; subsequent replay 401 | Existing isolated tests; do not alter AD or break shared networking to simulate this now |
| Local application disablement | Immediate 401 despite a fresh AD cache | Existing isolated tests; any local test-account state change requires later authorization |
| Sixth canonical-account attempt within 300 seconds | 429; no sixth bind | Synthetic regression coverage; no real-account brute-force/lockout test |

Lookup-account availability remains unconfirmed: the old assistant uses submitted user credentials; its protected environment is unreadable, and no installed Launchpad credential configuration exists at the prepared path. Do not treat an inaccessible file as evidence of an approved account or absence of one. Pilot A's learner identity and UPN suffix are no longer missing. The other unresolved inputs are the approved search base/group-use and membership policy, test namespace/run configuration, CA approval and accepted test/lockout/revalidation policy. These are configuration and authorization dependencies, not additional personal identifiers. No password is needed to resolve those decisions.

**For this older production-revalidation procedure:** the standalone diagnostic still needs the user search base and direct/nested check; its later application revalidation test needs an approved distinct read-only lookup identity, owner and scope. Pilot A's identity preparation is complete. The newly requested student website test instead follows [controlled work-study mode](#controlled-work-study-website-test), which needs that student's identity/configuration and trusted browser HTTPS but no background lookup account. Institutional CA approval remains separately pending; no password is requested in chat.

## Evidence required before release

1. Directory owner approves host/trust/search boundaries, UPN convention, use of the ADUC-verified group for Launchpad and its direct/nested policy, identity namespace, lookup account and lifecycle interval/outage handling. Observed existence/DN/membership do not satisfy these approval and live-verification gates.
2. From the deployed non-root service, verify trusted TLS to the selected DC; reject wrong-host/untrusted/expired certificates and unavailable directory service without sending credentials through a fallback.
3. With designated test accounts, verify allowed login, wrong/blank password denial, disabled-account denial, nonmember denial and the selected nested-membership behavior. Check exact GUID enrollment and deny unenrolled identities.
4. Verify cross-learner reads/writes and privilege escalation remain denied; check assigned-only mentor access, old-cookie rejection, logout/replay, local disablement and group removal during an active session.
5. Exercise directory outage and recovery, login limits across workers/restart, persistent progress, coordinated off-VM restore and safe logs. Record actual observations without credentials or directory results.
6. Complete the remaining Firefox/second-browser, 375/768/1440px, keyboard/screen-reader, 200% zoom and intended-user checks. Local mocks or TLS fixtures do not establish these hosted results.

No repository implementation or isolated test result constitutes permission to bind to AD, install services, change shared routing or invite real learners.
