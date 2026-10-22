# Pilot-readiness checklist

## Current supervised usability exercise — synthetic data only

This exercise is for a work-study participant to evaluate the interface while acting as **DEMO Nova Byte**, an invented learner. It does not record the participant's identity, knowledge, training completion or workplace readiness. Use the guarded, loopback-only demo and operator-owned access instructions in the [README](../README.md). No AD login, institutional certificate, student server account or real learner database is involved. Controlled-test and production authentication remain separate and unchanged.

Use a newly prepared synthetic run and a fresh browser profile for each participant. Keep the facilitator present. The app must display **Demonstration mode — synthetic learner data only**. Do not use real names, student identifiers, actual work answers, tickets, credentials or institutional records. The three demo personas and Mentor View are intentionally shared synthetic examples; they do not demonstrate real-user permissions. Stop if real data appears or a task would require acting on another system.

### Student task card

Say: “We are testing the website, not you. Use the fictional Nova Byte profile and invented answers below. Nothing here becomes your training record. Please say what you expect to happen and what you are looking for. You may stop at any time.” Start on the homepage and present one task at a time without naming the button, route or menu to use:

1. Find where to begin.
2. Complete a sample assessment.
3. Open the recommended training.
4. Complete a lesson and quiz.
5. Find your progress and explain what to do next.

### Invented assessment answer card

These answers reproduce the existing `synthetic_beginner_responses()` fixture. They deliberately include incorrect choices to exercise recommendations; **incorrect choices are not instructions for real work**. Enter them as Nova's fictional responses, never as statements about the participant. Do not perform any technical action described in a question.

| Assessment question | Fictional response to enter |
| --- | --- |
| Have you worked in an IT, computer lab, help desk, repair, or tech support role before? | No |
| Which of these have you done before? Select all that apply. | None of these |
| What are you most nervous about in this role? | This fictional learner is new to IT support and will ask a mentor before acting. |
| How confident do you feel using computers in general? | 1 — Not confident |
| How confident do you feel troubleshooting basic computer problems? | 1 — Not confident |
| How confident do you feel asking for help when you are stuck? | 1 — Not confident |
| How confident do you feel reading step-by-step technical documentation? | 1 — Not confident |
| In a school or workplace IT environment, what is a domain? | A folder on the desktop |
| What does computer imaging mean? | Changing the desktop background |
| SCCM or Configuration Manager is generally used for what? | Sending email |
| What is a ticket? | A storage device |
| What is an asset tag? | A software update |
| A monitor says "No Signal." What should you check first? | Check power, display cable, monitor input/source, and whether the computer is on |
| A keyboard is not working. What is a beginner-safe first step? | Change domain settings |
| Which of these is usually beginner-safe? | Deleting old user folders |
| A computer is running slowly. What is the safest beginner response? | Ignore the issue because slow computers are normal |
| You are asked to help image a computer, but you are not sure which image or workflow to use. What should you do? | Stop and ask your mentor or the IT tech on duty |
| You see an unfamiliar error while helping with a computer. What should you do? | Ignore it |
| A user asks you a question and you do not know the answer. What should you do? | Avoid the user |
| What should good ticket notes or mentor summaries include? | Nothing unless the issue is serious |
| You are given a task, but one step is unclear. What would you most likely do? | Stop and ask a specific clarification question |
| A user is frustrated and says, "IT never fixes anything." What is the best beginner-safe response? | Stay calm, avoid blame, and tell them you will check with your mentor |
| Which type of work sounds most interesting to you? | Figuring out why a computer, monitor, printer, or account is not working |
| Which task would you feel most comfortable learning first? | Checking cables, asset tags, device names, and error messages |
| A mentor asks you to document what happened during a task. What would you include? | What I checked, what happened, and what I still need help with |
| Which situation sounds most stressful to you? | A computer problem where I do not know the answer yet |
| Which statement best describes you right now? | I want to learn technical troubleshooting, even if it feels challenging |

For the first lesson's **What Does IT Do? Knowledge Check**, use these invented practice answers:

| Quiz question | Fictional response to enter |
| --- | --- |
| Which answer best describes IT support work? | Helping people, systems, devices, and workflows work safely |
| A new work-study student should know their escalation path before trying unfamiliar tasks. | True |
| What is a good first response when a user reports a problem you have not seen before? | Document what they reported and ask a mentor for the next step |

### Facilitator guidance and answer key

Allow roughly 20–30 minutes, recording actual duration. Let the participant try without intervention. “What are you looking for?” and “What did you expect?” are neutral prompts. After a prolonged pause, offer help without supplying it automatically. Record every navigation hint, demonstration or takeover verbatim as assistance; do not count assisted completion as unassisted. Give the answer card without showing this answer key.

| Task | Facilitator-only expected route and evidence |
| --- | --- |
| 1 | Homepage **Start assessment** leads to the persona picker; **DEMO Nova Byte** / **Use Selected Learner** continues to the Starting Point Check. Observe whether the identity step is understandable. |
| 2 | Manual entry and submission of the card produces an **18%** practice starting point and **Beginner / Full IT Foundations** recommendation. Written answers remain mentor-review items. The score measures the fixture, not the person. |
| 3 | **Open Beginner Path** on the results page opens the recommended path; its current step leads to **What Does IT Do?**. Observe searching and scrolling before offering help. |
| 4 | Read the first lesson, **Mark Module Complete**, then **Check Your Understanding** and **Check My Answers**. The quiz card yields **3 / 3 correct (100%)**. Reading and quiz records are separate; the quiz does not add a second completed path step. |
| 5 | **Progress** shows **1 of 12** path steps recorded and **Common IT Words** as next unfinished step. **Detailed saved records** shows one completed module and one completed quiz. Ask the participant to explain this in their own words before confirming. |

If the participant uses **Submit Synthetic Beginner Answers**, record that the assessment shortcut was used. It tests submission/results navigation but does not establish usability of question entry or validation. Do not use it silently to claim all assessment tasks passed. Saved fixture progress should remain after reload; the facilitator can verify restart persistence after the participant tasks without scoring that operation as a student task.

### Observation record — blank until a person completes the exercise

Use only an anonymous session code, with no mapping to student identity in the repository. Record run directory identifier, revision plus relevant local changes, actual date/time and timezone, browser/version, viewport, zoom and input method. The fixture's July 2026 seed timestamps are not the exercise date. Keep notes local and synthetic; summarize de-identified observations in the [results record](pilot_results.md).

Session code: ______ · Run identifier: ______ · Revision/local changes: ______

Date/time/timezone: ______ · Browser/version: ______ · Viewport/zoom: ______ · Input method: ______

| Task | First action / wrong turns | Time | Unassisted / assisted / blocked | Assistance and participant wording | Usability issue / expected versus observed behavior |
| --- | --- | --- | --- | --- | --- |
| 1. Find where to begin | | | | | |
| 2. Complete sample assessment | | | | | |
| 3. Open recommended training | | | | | |
| 4. Complete lesson and quiz | | | | | |
| 5. Find progress / next action | | | | | |

Ask after the five tasks and leave responses blank until observed:

- How busy did the interface feel, **1 = very calm, 5 = very busy**? ______
- Which page felt busiest, and what made it feel that way? ______
- Was it clear where to begin and what to do next? ______
- What did you expect to save, and did the saved progress match that expectation? ______
- What would you remove or change first? ______

Keep source-review concerns, automated results and actual participant observations separate. Current concerns to watch are finding the recommendation below the lengthy assessment results, deciding where to go after quiz feedback, and discovering separate quiz counts under collapsed progress details. These are hypotheses until observed. A current-interface session can establish present task performance and perceived busyness; it cannot establish that the redesign improved either without comparable earlier-version evidence. This exercise does not verify institutional sign-in, real-user permissions, browser accessibility as a whole or production readiness.

## Historical synthetic regression checklist

The material below preserves the earlier developer-mode checklist and its broader regression scenarios. For the current supervised exercise, follow the protocol above and current README launch instructions; do not substitute its free-name or database-reset examples for the guarded demo workflow.

> This checklist covers synthetic usability exercises. The current release targets real learners and must also pass the [real-user readiness gates](pilot_readiness.md) and [operations checklist](real_user_operations.md). A shared invitation or successful exercise is not authorization for real records.

This detailed regression checklist uses ordinary **local developer mode** with a disposable database. Its invented-name and malformed-data exercises are not instructions for changing a hosted pilot database. For the guarded invited pilot, use the three fixed synthetic personas and the [deployment runbook](pilot_deployment.md); see [current readiness evidence](pilot_readiness.md) for pending launch gates.

## Pilot purpose and boundaries

Use this checklist to decide whether the Launchpad is ready for a small, facilitated demonstration with synthetic students. The pilot checks navigation, supportive language, local progress persistence, mentor handoffs, and safe recovery from invalid data.

- Use synthetic names and invented answers only, such as `Pilot New`, `Pilot Returning`, and `Pilot Complete`.
- Use a dedicated local SQLite database and a non-production browser profile.
- Keep a mentor or supervisor present. The Launchpad supports onboarding; it does not approve independent work.
- Do not enter student IDs, legal names, credentials, tickets, device identifiers, internal URLs, or production procedures.
- Do not treat auto-scored results as hiring, placement, discipline, or independent-work decisions.
- Do not connect this prototype to production identity, student-record, ticketing, messaging, or device-management systems.

## Prerequisites

- [ ] Work from the intended reviewed revision with a clean baseline.
- [ ] Install dependencies in `.venv` from `requirements.txt`.
- [ ] Run `python3 scripts/check_all.py`; all tests and content validation must pass.
- [ ] Set a temporary database path, for example `LAUNCHPAD_DB_PATH=/tmp/launchpad-pilot.sqlite`.
- [ ] Set a non-default `LAUNCHPAD_SECRET_KEY` for the demo process.
- [ ] Confirm the database path is not the normal `instance/launchpad.sqlite` before resetting data.
- [ ] Use a fresh browser profile or clear the pilot browser's cookies before the first scenario.
- [ ] Have an authorized mentor available to review free responses, scenario attempts, and stop/escalation decisions.
- [ ] Record the app revision, browser, Python version, facilitator, and audit date.

## New student scenario

1. Open `/student` in a fresh browser session.
2. Enter `Pilot New`; confirm the page says not to enter real student records.
3. Confirm the next action is the Starting Point Check.
4. Submit `/pre-assessment` with invented beginner answers and at least one invented free response.
5. Review the score, recommended path, knowledge gaps, and separate mentor-review language.
6. Open the recommended path and its first unfinished item.
7. Complete one module, submit its low-stakes knowledge check, and save several Day 1 checklist items.
8. Submit one practice scenario with a safe pause-and-escalate response.
9. Open `/student` and confirm counts and the continuation action reflect the first unfinished required step.
10. Open `/supervisor` and confirm the synthetic student, saved counts, selected learner’s saved starting-point signal, and scenario practice appear.

Expected results:

- The student is never described as passing or failing.
- Free responses remain explicitly subject to mentor review.
- Module, quiz, and checklist progress is associated with `Pilot New`.
- Continuation points to the earliest unfinished required item in path order.
- Supervisor information shows saved SQLite progress and the selected learner’s saved assessment answers, help summaries and written scenario drafts.

## Returning student scenario

1. Close and reopen the page or create a second test client against the same pilot database.
2. Open `/student`, enter `Pilot Returning`, and complete a starting check plus part of the recommended path.
3. Start a fresh browser session, return to `/student`, and enter the same display name with different letter casing.
4. Confirm the existing synthetic record is reused and saved progress returns.
5. Complete the displayed next step, then return to `/student`.
6. Confirm continuation advances exactly one or more completed requirements and does not skip an unfinished requirement.
7. Mark an activity complete from its training path, verify continuation advances, reopen it, and verify continuation returns to it.

Expected results:

- Case-insensitive reuse does not create a duplicate synthetic student.
- Saved written scenario drafts and help summaries return after selecting the same learner in a fresh session; another learner’s details do not appear.
- Durable module, quiz, checklist, activity, assessment, and help-request counts remain available where implemented.
- Reopening a requirement makes the path incomplete again.

## Completed student scenario

1. Use `Pilot Complete` and submit a synthetic starting check that selects the Advanced Beginner path.
2. Complete every required checklist item, activity, and module in the displayed order.
3. Before the progress check, confirm `/student` identifies `Progress Check` as the next step.
4. Submit `/post-assessment` with invented responses.
5. Confirm the page displays an auto-scored practice result, readiness language, and separate mentor-review items.
6. Open `/student`; confirm it reports the recommended path complete and offers path review rather than another continuation action.
7. Open `/supervisor`; confirm both the selected learner’s progress-check signal and the saved latest progress check are visible.

Expected results:

- A saved post-assessment satisfies the path requirement without implying authorization for independent work.
- The completed state asks for mentor review before new or independent work.
- The supervisor can see the synthetic student's latest saved progress-check score/readiness.

## “Report I’m Stuck” and supervisor handoff

1. While signed in as a synthetic student, open `/stuck` (Help → Prepare a help request).
2. Enter an invented topic, intended task, observed behavior, approved checks already tried, blocker, and related training item.
3. Submit and read the generated mentor summary.
4. Confirm it describes the issue, attempted safe checks, requested help, and a clear stop point without inventing technical steps.
5. Open `/supervisor` in the same browser session.
6. Confirm the student's synthetic name, topic, and summary appear under Recent Help Requests and the saved help-request count increases.

Expected results:

- Empty required browser form fields are blocked by browser validation. In hosted pilot mode, crafted requests with missing required fields must also receive HTTP 400 without saving records; local developer mode retains its partial-response scoring fixtures.
- The summary never exposes credentials or recommends restricted actions.
- The interface labels the handoff as local demo data, not a production student record.

## Invalid and recovery scenarios

- [ ] Request an unknown module, checklist, scenario, training path, activity, and quiz; expect HTTP 404.
- [ ] Submit an activity update with an unknown activity ID; expect HTTP 404 and no saved row.
- [ ] Submit an activity update without `completed=0` or `completed=1`; expect HTTP 400 and no state change.
- [ ] Insert or simulate a stale activity ID; confirm it is ignored and cannot satisfy a current requirement.
- [ ] Use a missing, malformed, boolean, or out-of-range saved starting score; expect `/student` to offer the Starting Point Check.
- [ ] Use a missing or deleted student record in the session; expect anonymous recovery and cleared student identity.
- [ ] Use a malformed session student ID; expect anonymous recovery rather than a server error.
- [ ] Request `/assessment-results` without a saved or session starting check; expect redirection to `/pre-assessment`.
- [ ] Supply an external or protocol-relative `next` value to `/student`; expect redirection to the home page, not the external target.
- [ ] Repeat completion submissions; expect idempotent state rather than duplicate progress rows.

## Student feedback questions

Ask after the student scenarios:

1. Was it clear what to do first and what to do next?
2. Did any wording feel like a test, judgment, or employment decision?
3. Could you tell which steps required a mentor or local approval?
4. Was the difference between a knowledge check and a mentor-reviewed response clear?
5. Did Saved Progress return you to the step you expected?
6. When you reopened a step, did the changed status make sense?
7. Did “I’m Stuck” help you explain the blocker without guessing?
8. Was any page hard to scan, navigate, or use with keyboard-only controls?
9. What information did you expect to persist but did not?
10. What would make you more comfortable asking for help early?

## Mentor/supervisor feedback questions

1. Does the recommended path provide a useful starting conversation without replacing judgment?
2. Are safety boundaries and approval points visible enough?
3. Can you distinguish persisted progress from current-browser session signals?
4. Are free-response and scenario-practice items clearly non-scored and ready for review?
5. Does the stuck summary contain enough context to coach the student safely?
6. Does the latest progress check appear with appropriate caveats?
7. Are completion counts meaningful, or could they be mistaken for demonstrated competence?
8. Which local procedures must be explained outside the Launchpad before a student acts?
9. What accessibility, privacy, or record-retention review is still required?
10. What evidence would you require before approving a limited real-student pilot?

## Known limitations

- No authentication, authorization, SSO, or separation between student and supervisor views.
- Display-name matching is the only local identity mechanism; names are not safe unique identifiers.
- This synthetic exercise uses demo persistence. The current real-user candidate separately implements access-event records, backup/restore tooling and a single-instance boundary; CCA retention policy and hosted recovery remain unresolved. Use the [staging checklist](staging_verification.md) for real-user acceptance.
- Some supervisor details—assessment review items, scenario attempts, and displayed stuck summaries—depend on the current signed browser session, while counts and core progress are stored locally.
- Scenario attempts are not persisted in SQLite.
- Completion is self-reported and does not prove competence, mentor observation, or authorization.
- The rule-based Ask flow is not a full chatbot and cannot know local procedures.
- No production integrations, notifications, analytics, accessibility certification, security review, or privacy review are included.
- The prototype contains general training content only and must not be used for credentials, restricted work, or sensitive internal procedures.

## Demo-data reset instructions

Use a dedicated pilot database so reset cannot remove unrelated local demo work.

1. Stop the Flask process.
2. Print and verify `LAUNCHPAD_DB_PATH`; it must be the dedicated pilot file, such as `/tmp/launchpad-pilot.sqlite`, not an unresolved variable, directory, or shared database.
3. Move the verified database file to a timestamped quarantine filename rather than deleting it immediately.
4. Clear cookies/site data for the pilot browser profile to remove signed session-only assessment, scenario, stuck-summary, and synthetic identity data.
5. Restart the app with the same dedicated `LAUNCHPAD_DB_PATH`; startup creates a new empty schema.
6. Open `/student` and `/supervisor`; confirm no synthetic identity or saved demo progress remains.
7. Remove the quarantined database only after confirming the reset and any required audit notes are complete.

Never reset `instance/launchpad.sqlite` unless its ownership and contents have been explicitly verified and the reset is authorized.

## Stop conditions and rollback steps

Stop the pilot immediately if:

- real personal, academic, employment, credential, ticket, device, or internal-system data is entered;
- any user can view data they were not explicitly meant to see;
- the app recommends a restricted, destructive, credentialed, or unsupervised action;
- progress is attributed to the wrong synthetic student, lost unexpectedly, or skips an unfinished safety requirement;
- the starting or progress check is treated as a hiring, disciplinary, placement, or independent-work decision;
- a 5xx response, database corruption, repeated state inconsistency, or validation failure occurs;
- the facilitator cannot distinguish persistent records from current-session information;
- a mentor is unavailable for a step that requires local guidance or approval.

Rollback:

1. Stop the application and preserve the failing synthetic database and browser/session details for diagnosis.
2. Record the revision, route, synthetic persona, exact inputs, expected result, actual result, and time.
3. Revert to the last validated revision or restart with the previously quarantined known-good demo database; do not overwrite evidence.
4. Run focused regression tests, `python3 scripts/check_all.py`, and `git diff --check` before resuming.
5. Repeat the failed synthetic scenario from a clean browser profile and fresh dedicated database.
6. Do not resume the affected supervised exercise until the stop condition is corrected, reviewed and its relevant checks pass. Real training remains subject to the separate real-user readiness gates.

## Pilot exit decision

A synthetic pilot is ready only when every applicable scenario passes, all stop conditions remain false, automated checks pass, and a mentor confirms that the language and local boundaries are appropriate. A work-study participant may evaluate the supervised synthetic interface above without creating a real learner identity or training record. Saving actual student training progress additionally requires authentication and role-based access, an approved student-record and retention design, privacy/security/accessibility review, named support and incident owners, and documented mentor supervision and consent procedures.
