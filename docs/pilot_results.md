# Synthetic pilot results

## Supervised usability preparation 2026-10-09

**Current scope: synthetic usability only.** Real AD login, controlled-test deployment and shared wildcard-certificate remediation are deferred. This does not resolve their release blockers or change either authenticated mode. A work-study participant will role-play an invented learner; no actual learner identity, credentials or training performance are collected. A human usability session has **not** been observed yet.

Candidate: current uncommitted working tree based on `619667f`, including the focused interface simplification and new `scripts/start_usability_demo.py`. This is not a claim that the old commit alone contains these changes. Execution environment: CCA VM `ccadlnxweb09`, existing non-root operator `lesliec`, project `/opt/project/ITWorkStudyLaunchpad`; no access to the operator computer/browser is available here. Date is October 9, 2026, America/Denver; fixed July seed timestamps belong to the demo fixture, not this test.

| Check | Status and evidence |
| --- | --- |
| Reuse and isolation | Existing guarded demo mode, exactly three invented personas and a fresh operator-private directory. It rejects missing/unmarked/real-mode data and unknown learner names before app startup. Real/controlled/pilot authentication and inherited database settings cannot select the usability dataset. No AD connection, shared key, enrollment or production record is used. |
| Participant preparation | `/tmp/launchpad-usability-20261009.3Sow3g/demo.sqlite`, directory 0700/database 0600 with its own private signing key. **DEMO Nova Byte** still has zero assessment/module/quiz records; Riley and Quinn retain only the supplied synthetic seed. Smoke-test writes use other disposable datasets. `/tmp` is not durable storage and may be cleaned. |
| Actual demo startup | The exact README command was started briefly with the existing project `.venv`; `ss` showed only **127.0.0.1:8765**. Anonymous `/`, `/pre-assessment` and `/student` returned 200 with the synthetic banner. A foreign Host returned 400. The process was stopped with Ctrl-C; no listener was left running. No live Nginx/service/certificate change occurred. |
| Saved synthetic workflow | A separate disposable launcher subprocess exercises persona selection, invented assessment 18%/Beginner, first lesson `what_does_it_do`, recorded reading and quiz 100%, then Progress/next action. It restarts the actual launcher and verifies saved results and browser selection return. The subprocess makes any outbound socket or LDAP connection fail immediately. This is automated HTTP behavior, not rendered-browser or human evidence. |
| Automated validation | **352 tests passed**, no reported skips, plus content validation through the existing full validation environment. Eleven new demo tests preserve the prior 341 checks and cover storage/mode isolation, private-file/key refusal, loopback-only startup, no-listener preflight, safe logs and the complete synthetic HTTP/restart workflow. Actual participant preflight/anonymous startup also passed using the project `.venv`; no dependencies were installed. Runbook syntax, local links/anchors and whitespace checks passed. |
| Student browser/tunnel | Exact authenticated operator SSH-forward command is prepared in the README. It has not been executed from the operator's computer here. SSH host identity and campus/VPN reachability must work normally; no student server account, wildcard certificate or certificate bypass is needed. |
| Rendered UI and perceived busyness | **Not yet observed.** No Firefox/Chromium/Chrome executable or browser automation tool was available for this pass. No claim of visual, keyboard, screen-reader, zoom or responsive acceptance is made. |

Use the [current task cards and blank observation sheet](pilot_checklist.md#current-supervised-usability-exercise--synthetic-data-only). Give the tasks one at a time, record elapsed time, first action/wrong turns, exact assistance and outcome, and ask a 1–5 calm-to-busy rating after completion. Do not label scripted requests as a student successfully completing a task.

| Requested participant evidence | Current record |
| --- | --- |
| Find where to begin | Not observed; time/assistance unrecorded |
| Complete a sample assessment | Not observed; manual entry versus synthetic shortcut must be recorded |
| Open recommended training | Not observed; time/assistance unrecorded |
| Complete lesson and quiz | Not observed; time/assistance unrecorded |
| Find progress and explain next action | Not observed; participant explanation unrecorded |
| Overall busyness and busiest page | Not observed; rating and quote blank |

Source-review watchpoints, **not confirmed student usability defects**:

1. Recommendation visibility: `templates/assessment_results.html` places the recommended path below score/review/alignment material. Observe scrolling, missed links and assistance before deciding whether this obstructs task 3.
2. Quiz continuation: `templates/module_quiz.html` shows feedback followed by the full quiz form and offers “Back to module” rather than a dedicated next-step action. Observe mistaken resubmission or uncertainty after task 4.
3. Progress interpretation: `templates/student.html` puts separate module/quiz counts inside collapsed “Detailed saved records”; the path counts reading requirements separately. Ask the student to explain what saved before supplying an explanation.

No interface redesign was made in response to these hypotheses. A single session with the current version can establish present usability, not that the simplification improved performance or reduced mentoring time. Compare equivalent scenarios/baselines before making that claim. Keep summaries anonymous and use invented answers only; do not turn demo scores into participant evaluations. See [launch/access/stop instructions](../README.md#supervised-synthetic-usability-test).

## Historical results below

> Historical synthetic-prototype results. Capability/limitation statements below describe that earlier evaluation, not the current real-user candidate. For current identity, storage and release status, use the [readiness report](pilot_readiness.md) and [CCA staging proposal](staging_proposal.md). These earlier results do not establish hosted or browser acceptance.

## Test record and boundary

- Revision tested: `619667f` (`Show onboarding status on homepage`)
- **Confirmed:** `python3 scripts/check_all.py` passed with 56 tests and content validation.
- **Confirmed:** 9 homepage-focused tests passed with the project virtual environment.
- **Confirmed:** `git diff --check` passed before the homepage commit.

This record covers a local, facilitated pilot using invented identities and answers only. It excludes real students, production systems, credentials, tickets, device identifiers, and internal procedures. The application is not approved for real-student or production use.

## Scenario evidence

| Scenario | Expected result | Status | Observed evidence |
| --- | --- | --- | --- |
| New synthetic student | Save a demo name, receive a path, and begin tracked onboarding. | **Facilitator-reported** | Reported as behaving correctly; no screenshot or structured observation was available. |
| Returning synthetic student | Reuse the synthetic record and resume at the first unfinished step. | **Facilitator-reported** | Reported as behaving correctly; no screenshot or structured observation was available. |
| Completed synthetic student | Show completion, review action, and latest supervisor progress check. | **Not yet manually verified** | Completion behavior has automated coverage only. |
| Malformed session recovery | Clear invalid identity and recover anonymously. | **Automated-test coverage only** | Route regression test passes. |
| Supervisor progress-check visibility | Show session and persisted synthetic results with caveats. | **Automated-test coverage only** | Route and storage regression tests pass. |
| Invalid progress and routes | Reject invalid state without advancing progress. | **Automated-test coverage only** | Automated suite covers invalid routes, activity state, saved scores, and redirects. |
| Stuck report and handoff | Produce a bounded mentor summary. | **Automated-test coverage only** | Guidance, summary, route, and persistence tests pass. |

No scenario is **Blocked**. Unverified scenarios must not be represented as passed.

## Defects corrected

- Malformed session student IDs could error instead of recovering anonymously; normalization, cleanup, and coverage were added.
- Supervisor output omitted latest synthetic progress-check information in some contexts; session and persisted visibility plus coverage were added.
- Homepage actions did not reflect anonymous, new, returning, and completed states; state-aware actions and completed-path coverage were added separately.

## Evidence still missing

- Screenshots or timestamped notes supporting the new- and returning-student reports.
- Manual completed-student evidence.
- Completed recovery, stuck-report, accessibility, and supervisor-handoff checklist records.
- Browser, Python version, facilitator, pilot database identifier, audit timestamp, and mentor confirmation for a complete facilitated run.

## Known limitations and stop conditions

There is no authentication, authorization, role separation, production identity, approved retention/audit design, accessibility certification, privacy review, or security review. Display names are demo conveniences; SQLite is not a student-record system; some supervisor details are session-only; completion is self-reported; and rule-based guidance cannot know local procedures.

Stop if real or institutional data is entered, progress is attributed incorrectly, a safety requirement is skipped, restricted action is recommended, validation fails, or session and persisted data cannot be distinguished. Preserve synthetic evidence and follow `docs/pilot_checklist.md`.

## Final status

**Ready for a facilitated synthetic-data pilot; not approved for real-student use.**

Real-student use requires approved identity, authorization, student-record, retention, incident, privacy, security, accessibility, support, and supervision controls plus evidence-backed synthetic pilot completion.
