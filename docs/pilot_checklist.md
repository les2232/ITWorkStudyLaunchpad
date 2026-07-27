# Pilot-readiness checklist

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
10. Open `/supervisor` and confirm the synthetic student, saved counts, current-session starting-point signal, and scenario practice appear.

Expected results:

- The student is never described as passing or failing.
- Free responses remain explicitly subject to mentor review.
- Module, quiz, and checklist progress is associated with `Pilot New`.
- Continuation points to the earliest unfinished required item in path order.
- Supervisor information clearly distinguishes saved SQLite progress from browser-session details.

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
- Browser-session-only scenario and help-request details do not falsely appear as durable records after a new session.
- Durable module, quiz, checklist, activity, assessment, and help-request counts remain available where implemented.
- Reopening a requirement makes the path incomplete again.

## Completed student scenario

1. Use `Pilot Complete` and submit a synthetic starting check that selects the Advanced Beginner path.
2. Complete every required checklist item, activity, and module in the displayed order.
3. Before the progress check, confirm `/student` identifies `Progress Check` as the next step.
4. Submit `/post-assessment` with invented responses.
5. Confirm the page displays an auto-scored practice result, readiness language, and separate mentor-review items.
6. Open `/student`; confirm it reports the recommended path complete and offers path review rather than another continuation action.
7. Open `/supervisor`; confirm both the current-session progress-check signal and the saved latest progress check are visible.

Expected results:

- A saved post-assessment satisfies the path requirement without implying authorization for independent work.
- The completed state asks for mentor review before new or independent work.
- The supervisor can see the synthetic student's latest saved progress-check score/readiness.

## “Report I’m Stuck” and supervisor handoff

1. While signed in as a synthetic student, open `/stuck` (`Stuck` in navigation).
2. Enter an invented topic, intended task, observed behavior, approved checks already tried, blocker, and related training item.
3. Submit and read the generated mentor summary.
4. Confirm it describes the issue, attempted safe checks, requested help, and a clear stop point without inventing technical steps.
5. Open `/supervisor` in the same browser session.
6. Confirm the student's synthetic name, topic, and summary appear under Recent Help Requests and the saved help-request count increases.

Expected results:

- Empty required browser form fields are blocked by browser validation; server output remains safe if a crafted request omits fields.
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
- Local SQLite is demo persistence, not a production student-record system; there is no retention policy, audit log, backup workflow, or concurrency design.
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
6. Do not involve real work-study students until the stop condition is corrected, reviewed, and the full checklist passes.

## Pilot exit decision

A synthetic pilot is ready only when every applicable scenario passes, all stop conditions remain false, automated checks pass, and a mentor confirms that the language and local boundaries are appropriate. Involving real students additionally requires authentication and role-based access, an approved student-record and retention design, privacy/security/accessibility review, named support and incident owners, and documented mentor supervision and consent procedures.
