# Optional CCA OIDC registration checklist

> Current VM preparation (2026-10-08): Plan a future approved cutover of `lesliec.ccaurora.edu/` from the archived older assistant to Launchpad; preserve `itsupport` unless separately retired. The candidate uses verified LDAPS with explicit GUID enrollment, pending directory/lookup-account and lifecycle approval. No live directory access, retirement, deployment or routing change has occurred. Use [VM deployment](vm_deployment.md), [AD authentication](ad_authentication.md), [sysadmin decisions](vm_sysadmin_handoff.md) and [current validation](vm_verification.md). Historical OIDC test results below do not establish AD or hosted acceptance.

Prepared 2026-10-07; scope clarified 2026-10-08. **Optional OIDC reference only. The selected AD candidate does not require an OIDC registration or callback.** Use this checklist only if CCA separately selects `LAUNCHPAD_AUTH_BACKEND=oidc`; product/tenant/protocol remain unconfirmed. The existing Authlib client is retained alongside AD, with distinct enrollment and lifecycle. SAML or automatic cross-backend account migration would require separate review.

## Non-secret details needed from CCA IT

A provider/team name is enough to start. Obtain the remaining technical values from that team before registration/configuration; use an approved internal channel if metadata is considered internal.

| Detail | Exact value needed / why |
| --- | --- |
| SSO service and registration owner | Provider/product, responsible team or contact role, approved tenant/realm, registration instructions and whether confidential OIDC web apps are supported. |
| Issuer / metadata | Exact HTTPS issuer including its path/trailing-slash convention, and discovery URL. The app currently derives discovery as `issuer.rstrip('/') + '/.well-known/openid-configuration'`; the returned `issuer` must match the configured string exactly. No separate discovery-URL environment setting exists. |
| Supported registration settings | Confirmation of authorization code, query-mode callback, PKCE `S256`, signed `RS256` ID tokens and `client_secret_basic`. Discovery must advertise S256/RS256; token authentication must include Basic if methods are advertised. |
| Endpoint origins / egress | Authorization endpoint's scheme, hostname and effective port must equal the issuer's origin. Supply discovery/token/JWKS endpoint locations or documentation for egress review. Different-origin authorization needs a reviewed adapter/CSP change, not a guessed setting. |
| Staging address | The selected future cutover address is `https://lesliec.ccaurora.edu/`; optional OIDC would register exactly `https://lesliec.ccaurora.edu/auth/callback`. No registration or cutover has occurred. Preserve `itsupport` unless separately retired. Confirm campus/VPN and callback reachability before authorizing any optional integration. |
| Client identifier | Non-secret application/client ID once created. Also give credential expiration/rotation policy and the secret-store owner, **not the credential itself**. |
| Assignment / access policy | Eligible designated test accounts, application-assignment policy, MFA/conditional access/guest rules and enrollment/offboarding owner. No subject roster is needed in chat; provider role/group claims do not grant app permissions. |
| Stable subject policy | Whether `sub` is public or pairwise, its stability for this registration, and the restricted procedure by which IT verifies the app-specific subject for enrollment. Do not send tokens or actual learner identifiers here. |
| Session / sign-out requirements | Whether application-only logout and eight-hour absolute/30-minute idle limits satisfy CCA policy. Name the offboarding owner and maximum accepted delay for local-session revocation after institutional disablement or directory-group removal. Identify requirements for global logout or automatic deprovisioning before promising support. |

Account identity uses the `(issuer, subject)` pair; email/name is not an ownership key. Pairwise subjects may differ between app registrations, so staging mappings cannot simply be reused for production. [OIDC claim stability and pairwise subjects](https://openid.net/specs/openid-connect-core-1_0.html#ClaimStability)

## Registration values to request

- [ ] Dedicated **staging confidential server-side web application**, owned by CCA with a documented registration/support owner.
- [ ] Authorization-code grant and `response_type=code`; query response delivered to a **GET** callback. Do not select `form_post`, implicit flow or a browser-only/public client.
- [ ] Only if OIDC is selected, register approved exact callback `https://lesliec.ccaurora.edu/auth/callback`, with no wildcard/query/fragment. Separate environments require separately reviewed registrations/configuration. AD mode does not use this callback.
- [ ] Scope **`openid` only**. The app does not need profile/email, directory API access or `offline_access`/refresh tokens.
- [ ] PKCE `S256`, ID-token signing `RS256`, token endpoint authentication `client_secret_basic`, and an ordinary signed ID token. Other methods or encrypted ID tokens need compatibility review.
- [ ] Discovery, issuer, endpoint-origin and certificate trust requirements checked against the actual provider. Do not weaken signature, audience, issuer, nonce, state or TLS checks to accommodate a mismatch.
- [ ] Restrict sign-in eligibility using CCA's approved application/MFA policy. Explicit local enrollment is an additional gate; successful organizational authentication alone must not create or claim a learner.
- [ ] Provider credential created directly into the approved secret-management process; no secret values, private keys, raw tokens or credential files in chat, Git, test reports or screenshots.
- [ ] Do **not** register `/auth/logout` as an IdP logout callback. It is the app's CSRF-protected POST action. Front-channel/back-channel logout and `post_logout_redirect_uri` are not implemented; leave these unset unless a separately reviewed integration is required.
- [ ] Named owners and procedure for credential rotation, institutional disablement/directory-group removal, local account and mentor-grant revocation, and incidents. Record the maximum accepted delay for local-session revocation and verify the coordinated offboarding procedure in staging.

These settings reflect [oidc.py](../launchpad/oidc.py) and [real_auth.py](../launchpad/real_auth.py), rather than every capability the library or provider might offer. Authlib supplies the [Flask OIDC client](https://docs.authlib.org/en/stable/oauth2/client/web/flask.html); authorization code with PKCE follows [OAuth security guidance](https://datatracker.ietf.org/doc/html/rfc9700#section-2.1.1).

## Session and account lifecycle acceptance

**This section describes OIDC mode only.** Application logout revokes its current local session, including copied-cookie replay; it does not end upstream SSO or every other browser session. A user may sign back in through an existing upstream session if still enrolled. Institutional disablement/group removal alone does not automatically invalidate existing OIDC-mode local sessions; the named owner must locally disable/revoke within the approved delay. Local mentor-assignment removal invalidates the mentor's sessions. The separate [AD candidate lifecycle](ad_authentication.md#session-lifecycle-and-removal) uses proposed periodic GUID lookup and is not a feature of this OIDC integration.

The OIDC backend has no automatic directory sync, just-in-time account creation, IdP role mapping or upstream logout endpoint. If required for this optional integration, treat the specific requirement as a decision and implementation gate. Upstream logout is a distinct protocol. [OIDC RP-initiated logout](https://openid.net/specs/openid-connect-rpinitiated-1_0.html)

Explicit enrollment uses the verified subject obtained through an approved restricted process. Do not enable open enrollment just to discover subjects, read a production token into a chat, or map existing rows by matching names/email. Refer to the [mapping/migration plan](learner_data_policy.md) and [operator runbook](real_user_operations.md).

## Verification before real learners

If OIDC is selected, adapt the [staging matrix](staging_verification.md) to its actual registration. In Firefox and another browser, include the full federated redirect chain, cookie retention, account selection, logout/back and unenrolled denial. SameSite/CSP and actual metadata cannot be accepted from Python HTTP tests alone. Prior OIDC fixtures do not prove CCA SSO, and they do not replace the selected AD candidate's directory checks.
