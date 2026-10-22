# Native login Origin rejection — October 12, 2026

The browser-reproduced rejection has a confirmed cause and a tested fix.
**The operator-authorized activation completed on October 12 at 21:31:56 UTC.**
The fix was applied independently of the visual candidate; its
[review gallery](../work/visual-review/20261012-portal/review.html) remains staged
and available for approval. Yasmin's historical October 9 HTTP 400 cause remains
unproven. Investigation results below describe the pre-activation state; the
final section records the executed activation and remaining human test.

## Confirmed cause

Launchpad's real-user response hook sends `Referrer-Policy: no-referrer`.
Under the [Fetch Standard's Origin-header algorithm](https://fetch.spec.whatwg.org/#append-a-request-origin-header),
that policy makes a native HTML form POST send `Origin: null`. The browser is
following its security policy; this does not indicate an AD password error.

Launchpad validates CSRF first, then rejects a non-HTTPS or foreign Origin.
Literal `null` fails that check. Both Chromium 156.0.8078.4 and Firefox 157.0
reproduced **400 / `origin_rejected` before any directory call**, using a freshly
loaded real login form, cookie, and CSRF token. This also reproduces when starting
at `/`, where the anonymous 401 response renders the login form.

The earlier preview's JavaScript `fetch()` bootstrap used a different request
mode from native form navigation, so its successful POST did not establish
normal browser sign-in. This investigation instead used native button clicks
and real HTTPS sockets, including browser-managed redirects, without response
interception or a fetch bootstrap.

## Preview versus deployed configuration

Anonymous read-only requests and allowlisted configuration inspection found:

| Boundary | Evidence |
| --- | --- |
| Public HTTPS `/auth/login` | 200; certificate chain and hostname validated; TLS 1.3. No redirect. |
| Loopback backend HTTPS `/auth/login` | 200 with explicit backend trust and hostname validation; TLS 1.3. Same security policy and form contract as public response. |
| HTTP `/auth/login` | 308 to the same canonical HTTPS hostname/path. No authentication was submitted over HTTP. |
| Public anonymous `/` | 401 rendering the login form, matching the tested entry flow. |
| Browser headers | Public and backend both send `no-referrer`, `Cache-Control: no-store`, and CSP `form-action 'self'`. The form has no referrer-meta override. |
| Form | `POST /auth/login`, fields `csrf_token`, `username`, and `password`; no unexpected action, alternate hostname, or field renaming. Field values were not recorded. |
| Cookies | Secure, HttpOnly, host-only Path=/, SameSite=Lax. Values were not recorded or copied. |
| Nginx | Enabled configuration proxies to verified loopback HTTPS, sets the canonical Host and HTTPS scheme, and clears alternate forwarded host/path claims. No Origin or Referrer-Policy rewrite. |
| Backend scheme | The controlled launcher disables forwarded-scheme overrides; its TLS socket establishes the request scheme. |
| Configuration | Allowlisted on-disk values select AD, `controlled_test`, and the canonical trusted hostname. This is configuration evidence, not a dump of the process environment. Observed responses agree with it. |

These observations show that the deployed login serves the policy that causes
the isolated failure. They do not prove what headers, cookies, or rejection
reason were present in Yasmin's historical request. No live POST, AD bind,
learner-record read, or service/configuration change was performed.

[Sanitized deployment evidence](../work/login-origin-review/20261012/evidence/deployed-origin-comparison.json)

## Implemented fix

The independent candidate is under
`work/login-origin-review/20261012/candidate/`. Its [three-file patch](../work/login-origin-review/20261012/login-origin-fix.patch)
changes one application header and adds four focused regression tests:

```python
"Referrer-Policy": "no-referrer" if request.endpoint == "auth_callback" else "same-origin",
```

[`same-origin`](https://w3c.github.io/webappsec-referrer-policy/#referrer-policy-same-origin)
preserves the origin needed by native same-origin form submissions and still
omits referrers to other origins. It permits URL paths/query strings in referrers
within the application. OIDC callback responses therefore retain `no-referrer`
on success and failure so their code/state query strings cannot become internal
resource referrers.

The origin and CSRF guards are unchanged. This does not allow `Origin: null`,
change CORS, trust forwarded hosts, alter cookie flags, relax rate limits, or
change passwords, identity mapping, permissions, scoring, sessions, or storage.
The policy covers all real-user form documents, including anonymous 401 pages
and authenticated forms, rather than just the login route.

The older shared-invitation synthetic pilot has an analogous `no-referrer`
policy. It is outside this controlled real-user fix and was left unchanged;
these results are not an assertion that every legacy pilot mode is fixed.

## Validation

| Test | Before | Fixed candidate |
| --- | --- | --- |
| Native login, Chromium and Firefox | Origin=null; 400; zero directory calls | Same origin; 302; native redirect to authenticated home; own progress 200 |
| Native foreign-origin login with valid CSRF and cookie | Not needed for cause isolation | 400 / origin_rejected; zero added directory calls in both browsers |
| Native same-origin login without CSRF | Existing tests retained | 400 / csrf_token_count; zero added directory calls in both browsers |
| Literal null, foreign HTTPS, HTTP downgrade, wrong-port Origin with valid CSRF | Existing guard retained | All reject before directory/rate-state/learner-state changes in focused tests |
| Missing and incorrect CSRF | Existing guard retained | Rejected; fresh valid form still works |
| Native lesson submission and reload | Not claimed | 302; saved synthetic completion state survives reload in both browsers |
| Native logout | Not claimed | 302 to login; subsequent private read 401 in both browsers |
| TLS hostname negative control | Wrong hostname rejected | Wrong hostname rejected in both browsers; no validation bypass |
| OIDC callback privacy | no-referrer | no-referrer on success, invalid callback, and unenrolled account; code/state not echoed |

The cross-origin browser test uses a second HTTPS port on localhost. This is
same-site but a different origin, so the browser can send its existing cookie.
A valid synthetic CSRF token is supplied deliberately to prove that the Origin
guard independently rejects the request. No token or cookie values enter the
evidence files.

Four new test methods were added without removing or weakening existing tests.
The new header regression checks failed against the original code. After the
fix: **98 focused tests passed; all 392 suite tests and content validation
passed**. Both the authentication patch and untouched visual patch pass
`git apply --check` against the current checkout. Whitespace checks pass.

- [Before Chromium](../work/login-origin-review/20261012/evidence/before-chromium-native-browser.json)
  / [before Firefox](../work/login-origin-review/20261012/evidence/before-firefox-native-browser.json)
- [Fixed Chromium](../work/login-origin-review/20261012/evidence/candidate-chromium-native-browser.json)
  / [fixed Firefox](../work/login-origin-review/20261012/evidence/candidate-firefox-native-browser.json)
- [Pre-fix regression failures](../work/login-origin-review/20261012/evidence/regression-before-fix.txt)
  / [focused checks](../work/login-origin-review/20261012/evidence/regression-focused.txt)
  / [complete suite](../work/login-origin-review/20261012/evidence/regression-full.txt)
- [Source isolation](../work/login-origin-review/20261012/evidence/source-isolation.json)

The browser server and driver are retained under the same review's `tools/`.
They load the actual before/fixed source and existing disposable controlled-test
fixtures, mock only directory identity/startup boundaries, and reject accidental
LDAP connections. Data and certificates are newly generated under `/tmp`.
Certificate validation remains enabled: a disposable public CA is trusted only
inside fresh temporary browser storage. System trust, normal user trust, CCA
certificates, and deployed configuration are untouched. Temporary browser
profiles and fixture data are cleaned up after testing. Browser tooling was
extracted under `/tmp`; no application dependency or system package was installed.

## Authorized activation completed — 21:31:56 UTC

The operator authorized applying this reviewed fix during a pause in testing.
Before interruption, read-only checks found zero active server sessions, no
backend connections, and no website requests in the preceding two minutes.
The patch exactly matched the tested before/candidate difference. The three
applied files then matched the candidate byte-for-byte. All **392 tests and
content validation passed from the actual repository**, and offline startup
preflight passed using the existing run.

Only controlled master 498817 and its worker 498819 were stopped gracefully.
The documented startup command created **master 506100 / worker 506101**, using
the same run, key and backend certificate. The worker-ready source fingerprint
matches the applied code, and the listener remains only `127.0.0.1:8443`.
Nginx and unrelated services were not restarted or reconfigured.

Post-restart verification passed:

- Public and loopback HTTPS both validate certificate chain and hostname and
  return login 200 with `Referrer-Policy: same-origin`. HTTP still redirects 308
  to the canonical HTTPS URL. Secure/HttpOnly/host-only/SameSite cookie flags,
  CSP, no-store, frame protection and content-type protection remain intact.
- `/auth/callback` returns **404 with `no-referrer`**: this route exists but is
  intentionally disabled in the active AD mode. Actual OIDC callback behavior
  remains covered by the isolated success/failure regression tests, not a live
  OIDC authentication claim.
- Valid-CSRF POSTs with literal null and foreign origins return 400 with
  `origin_rejected`. Missing CSRF returns 400 with `csrf_token_count`.
- A same-origin POST containing only CSRF, with both credential fields omitted,
  reaches the expected 401 `login_fields_invalid` branch before rate admission
  or directory authentication. Actual Chromium 156 and Firefox 157 also pass
  this native form check over verified public HTTPS. No username or password
  was filled or submitted, and no cookie/token values were recorded.
- All **39 inventoried files** retain their original contents, ownership and
  modes: signing key, run configuration, enrollment/progress and admission
  databases, existing run/TLS files, live templates/static assets and readable
  Nginx configuration. Nginx process identities/start times are unchanged.
  There are still zero server-session rows. Only sanitized diagnostic logs
  received expected verification entries.
- The visual gallery checksum is unchanged and the visual patch remains
  applicable. The redesign has not been activated.

Evidence and retained prior source are private under
`work/login-origin-review/20261012/activation-20261012T212841Z/`:
[activation result](../work/login-origin-review/20261012/activation-20261012T212841Z/activation-result.json),
[live browser results](../work/login-origin-review/20261012/activation-20261012T212841Z/live-browser-smoke.json),
and [applied suite](../work/login-origin-review/20261012/activation-20261012T212841Z/applied-suite.txt).
Rollback was prepared but not needed. Do not reapply the authentication patch
or rerun the activation helper after this successful activation.

**Next: one supervised sign-in by Yasmin in a new private browser window at
`https://lesliec.ccaurora.edu/auth/login`.** She enters her own W-number or full
CCA UPN and password herself, uses invented training answers, and signs out
afterward. The existing 15-minute absolute lifetime remains in effect. If
rejected, stop and record only the time/timezone and visible outcome so the
sanitized diagnostics can be correlated; do not repeat password attempts.

No institutional password or live directory authentication was tested during
activation. The historical October 9 cause remains unproven, and CCA sign-in is
not declared working until the supervised attempt confirms it. Any future
rollback must restore only the retained source and restart the controlled
master; never restore older learner data for this header change.
