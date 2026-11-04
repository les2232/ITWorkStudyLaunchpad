# Visual design candidate — October 12, 2026

Implemented for review, **not activated on the controlled-test website**. The live
backend reads templates and static files from its checkout, so editing those
files in place could change Yasmin's test without a restart. The candidate is a
source-only copy under `work/visual-review/20261012-portal/candidate/`.

Follow-up: the [native-login Origin investigation](login_origin_investigation.md)
has a separately tested security-header fix, activated with operator approval on
October 12 at 21:31:56 UTC. This visual candidate and its gallery remain unchanged;
the authentication fix was activated independently of visual approval.

The root checkout changes for this task are this document and a narrowly scoped
Git ignore rule for `/work/visual-review/`. Existing unrelated changes were left
alone. No live application source, configuration, enrollment, database,
certificate, directory setting, or service was changed.

## Review the implementation

- [Before/after gallery](../work/visual-review/20261012-portal/review.html): all six
  requested pages at 375, 768, and 1440 pixels; select Chromium or Firefox for
  the candidate. Open the HTML locally in a browser, or follow the PNG links.
- [Mobile login comparison](../work/visual-review/20261012-portal/screenshots/login-mobile-comparison.png)
- [Desktop dashboard comparison](../work/visual-review/20261012-portal/screenshots/dashboard-comparison.png)
- [Presentation patch](../work/visual-review/20261012-portal/design-review.patch)

The patch changes only `templates/base.html`, `templates/login.html`,
`templates/home.html`, `templates/student.html`, and a new `static/portal.css`.
Assessment, lesson, and quiz layouts inherit the shared presentation styles;
their activity templates and curriculum are unchanged. No JavaScript, Python,
routes, form field names, scoring, completion, persistence, or permissions were
changed. No new application dependency is required.

## What the screenshots established

The original login password field was an unstyled 21px-high control beside a
much wider username field. On mobile, notices and introductory content pushed
the entire form below the first screen. Authenticated pages had tall navigation,
a separate logout row, repeated bold instructions, and competing bordered boxes.
Questions and lesson sections had redundant visual divisions.

The candidate provides:

- A compact shared header with stable Learn, Practice, Progress, and Help links.
- A centered login form with matching 48px-high fields and one sign-in action.
- A quieter controlled-test notice. The 15-minute absolute lifetime and unsaved
  work warning remain visible; longer session policy remains in native details.
- A single prominent next action, with recorded progress beside it on desktop
  and directly below it on smaller screens.
- Consistent typography, spacing, buttons, focus outlines, and form controls.
- Fewer nested boxes around questions, readable lesson width, and detailed
  records available through the existing disclosures.

In Chromium at 375px, the dashboard content starts at y=254px instead of
y=389px. The candidate login shows both fields and Sign in within the initial
900px-high viewport. The mobile quiz shows its first question within that
viewport. These are rendered observations, not evidence of improved task
performance or intended-user preference.

Colors follow CCA's [2026 Visual Brand Standards, page 12](https://ccaurora.edu/wp-content/uploads/2026/08/VisualBrandStandards_2026.pdf),
linked by [Strategic Communications](https://ccaurora.edu/strategic-communications/):
red `#9A111F`, ink `#231F20`, slate `#66686A`, silver `#D1D2D4`, with the documented
Arial fallback. Silver is decorative rather than the sole form boundary. No
unverified logo, external font, or image asset was introduced.

## Validation

| Check | Result and limit |
| --- | --- |
| Existing complete suite | **388 tests passed**, unchanged; content validation passed. Authentication, CSRF, authorization, sessions, scoring, completion, and persistence checks remain intact. |
| Patch and whitespace | `git apply --check` and `git diff --check` passed. Patch was not applied to the live checkout. |
| Before rendering | Chromium 156.0.8078.4: six requested pages at all three widths, 18 page/width captures. |
| Candidate rendering | Chromium 156.0.8078.4 and Firefox 157.0: 36 page/width combinations, all 200, no horizontal overflow or JavaScript page errors. Full-page and viewport screenshots retained. |
| Accessibility automation | axe-core: zero violations across those 36 combinations for WCAG 2 A/AA, 2.1 AA, and best-practice checks, including rendered text contrast. Expanded progress records also checked. This is not a conformance certification. |
| Keyboard | Both engines: Tab focus and skip link visible; skip link reaches main; username/password/button reachable; native disclosures open with Enter; radio arrows and checkbox Space work. Dark 3px focus outlines retained. |
| Enlarged layout | Both engines: six pages at 720x450 CSS pixels and 2x device scale, approximating a 1440x900 display at 200% zoom. No horizontal overflow or page errors. **Native browser UI zoom remains unverified.** |
| Live isolation | All 151 files in the task's source baseline remained unchanged. Live master 498817 and worker 498819 retained their October 12 20:44:54 UTC start time. No live requests or credentialed authentication were needed for visual QA. |

Evidence is retained in the ignored review directory:

- [Complete test summary](../work/visual-review/20261012-portal/evidence/candidate-full-suite-summary.txt)
- [Chromium rendering](../work/visual-review/20261012-portal/evidence/after-chromium-render.json)
- [Firefox rendering](../work/visual-review/20261012-portal/evidence/after-firefox-render.json)
- [Accessibility and keyboard checks](../work/visual-review/20261012-portal/evidence/candidate-accessibility-keyboard.json)
- [Settled focus checks](../work/visual-review/20261012-portal/evidence/candidate-focus-followup.json)
- [Chromium enlarged reflow](../work/visual-review/20261012-portal/evidence/after-chromium-zoom-reflow.json)
- [Firefox enlarged reflow](../work/visual-review/20261012-portal/evidence/after-firefox-zoom-reflow.json)
- [Source isolation](../work/visual-review/20261012-portal/evidence/source-isolation.json)

The preview uses existing controlled-test fixtures, disposable `/tmp` databases,
invented learner identities and answers, and a guarded directory boundary.
Playwright renders real application responses at an intercepted invented origin,
`https://launchpad.example`; it does not validate deployed HTTPS or actual AD.
Temporary browser tooling is under `/tmp/launchpad-visual-browser-20261012/`;
no application requirements or system package installation was changed.

## Separate native-form compatibility finding

An actual Chromium login form submission in the baseline returned **400,
`origin_rejected`**, before the directory boundary. The existing
`Referrer-Policy: no-referrer` caused the native navigation POST to send
`Origin: null`. In an isolated in-memory header experiment, `same-origin`
produced the expected origin and a 302 with the same synthetic fixture.
[Mozilla documents this Origin behavior](https://developer.mozilla.org/en-US/docs/Web/HTTP/Reference/Headers/Referrer-Policy#effect_on_the_origin_header).

The visual patch does not change that header or weaken origin, CSRF, cookie,
TLS, or rate-limit checks. Authenticated screenshots use an explicitly
documented same-origin fetch of the existing form's synthetic inputs to establish
a rendering session. They are **not successful native login workflow tests**.

[Isolated evidence](../work/visual-review/20261012-portal/evidence/native-form-origin-investigation.json)
supports a separate, focused security-header compatibility investigation. It
does **not** establish Yasmin's historical 400 cause, and the historical incident
must remain unresolved until corroborating evidence or a supervised retry does
so. Native learner form submissions need end-to-end verification before release.

## Remaining review and activation boundary

Screen-reader announcements with actual assistive technology, native browser
200% zoom, actual institutional sign-in, and intended-student usability feedback
remain unverified. The shared header was behavior-tested for mentor permissions;
this capture set focuses on the six requested learner pages.

Review this candidate while the current controlled test continues. Do not copy
its templates/CSS over the live checkout during an active test. When activation
is separately scheduled, first confirm that no test is active, retain the four
current templates, and rerun this read-only check from the repository root:

```sh
git apply --check work/visual-review/20261012-portal/design-review.patch
```

If the source has changed, reconcile the candidate before applying it. The
patch is ready for a later controlled application; it has not been applied here.
After an approved switch, verify the six pages, native sign-in and submissions,
and the existing progress state. A Python change is not needed for this visual
patch, but template caches require a planned backend restart for a consistent
release. Keep the signing key, configuration, enrollment, and database unchanged.
Rollback restores the retained presentation files and removes only the newly
introduced stylesheet reference/file; it never restores an older learner DB.

For the eventual supervised usability session, record whether the student can
find the assessment, reach recommended training, finish a lesson and quiz, and
explain their next step. Record assistance and perceived clutter without saving
credentials or real training answers in review artifacts. No such user session
was claimed in this visual review.
