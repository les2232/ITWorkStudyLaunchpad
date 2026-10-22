# Regular-use release: plan before any live change

Prepared 2026-10-22 in the development worktree. **Nothing here has been deployed.** The live controlled test, its data, Nginx, certificates and services are unchanged. Each command below needs your explicit authorization at the time it is run.

## What this release changes

| Area | Change |
| --- | --- |
| Learner pages | Home, Learn, Progress and the learning path show the next step, why it matters, Not started / In progress / Completed, and a "What to do now" list after the path is finished. |
| Help requests | Learners see every open request, and the 20 most recent resolved ones, on **My Help Requests**. They can resolve and reopen them. "Resolved" means the learner no longer needs help; it is not mentor approval. Mentors see open requests from assigned learners only, read-only. Saving still sends nothing. |
| Sessions | New `LAUNCHPAD_AD_SESSION_POLICY=signin`. CCA password and group membership are checked at every sign-in. A session ends after 30 minutes without activity or `LAUNCHPAD_SESSION_MAX_HOURS` after sign-in (default 4, allowed 1–8). Local disable and sign-out take effect immediately. No lookup account is needed. Real answers are allowed. |
| Wording | Real mode no longer shows demo, prototype, synthetic or controlled-test text. A test now sweeps every learner and mentor page for it. Sign-in, the footer and the expiry page state the timeout and what is saved. |
| Written answers | Every page that saves free text warns against entering passwords, records, other people's private information or live tickets. Ask a Question says it is not saved. |
| Saved data | `stuck_reports.resolved_at` (nullable). Real schema version 1 → 2. Version-1 databases refuse to start until migrated to a **new** file. |

`revalidate` remains the stronger policy (directory rechecked every 1–300 seconds) once CCA provides a read-only lookup account. Under `signin`, AD disablement or removal from the group stops **new** sign-ins immediately, but an existing session continues until it expires (at most `LAUNCHPAD_SESSION_MAX_HOURS`) unless an operator revokes it with `manage_real_data.py revoke-sessions --account-id`.

## Decisions needed from you

1. **Backend certificate, by Oct 23, 4:13 PM MDT.** The controlled test's backend leaf (`launchpad-controlled.invalid`) expires **2026-10-23 22:13:39 UTC**; verified on Oct 22 from 127.0.0.1:8443. After that, Nginx's backend verification fails and students see an error page. Choose one:
   - **Close the controlled test before expiry.** Use the existing [closed-access step](vm_deployment.md#closed-access-rollback-and-exact-routing-reversal), which shows a 503 maintenance page. This is the recommended choice if the production cutover will not happen within days.
   - **Extend it seven days.** Create a new backend leaf in a new directory, following the dated renewal section in [VM verification](vm_verification.md). This is a manual, authorized step; the old activation and recovery scripts are not rerun automatically.

   The production service below uses a Unix socket and has **no backend certificate**, so this cycle ends at cutover.
2. **Public wildcard certificate:** `*.ccaurora.edu` expires **2026-10-28 23:59:59 UTC**. Confirm the renewal owner and installation date with Michael and Jordan. Every route on this VM depends on it.
3. **Session limit:** accept `signin` with a 4-hour maximum, or choose 1–8 hours. Optionally request the lookup account to use `revalidate`.
4. **Dataset:** a fresh production dataset (recommended), or carrying forward the controlled test's progress (Option B below).
5. **Policy items still open in the [learner data policy](learner_data_policy.md):** CCA approval of purpose, learner notice, retention, custodians and off-VM backup destination. These are operational approvals, not code.

## Database plan

**Option A — fresh production dataset (recommended).** No migration is needed. The new code creates schema version 2 directly. The controlled-test database stays exactly as it is: version 1, invented answers, kept for reference. Students start from an empty record, and their earlier test answers were invented anyway.

**Option B — carry forward the controlled test's records.** Use this only if you decide the test progress should continue. Everything runs on copies. The source file is never changed and remains the rollback copy.

- Linux terminal, step 1. Stop the controlled test (after closing access as described above): press Ctrl-C in its tmux window.
- Linux terminal, step 2. Make a consistent snapshot with the currently deployed code:

  ```bash
  cd /opt/project/ITWorkStudyLaunchpad && /tmp/launchpad-real-validation-6qhv4cbn/venv/bin/python -B scripts/manage_real_data.py backup --source /opt/project/ITWorkStudyLaunchpad/work/controlled-work-study/work-study-01/learners.sqlite --destination /opt/project/ITWorkStudyLaunchpad/work/controlled-work-study/work-study-01/learners-snapshot-20261022.sqlite
  ```

- Linux terminal, step 3. Migrate the snapshot to a NEW version-2 file with the release code:

  ```bash
  cd /home/lesliec/launchpad-dev && .venv/bin/python -B scripts/manage_real_data.py migrate --source /opt/project/ITWorkStudyLaunchpad/work/controlled-work-study/work-study-01/learners-snapshot-20261022.sqlite --destination /opt/project/ITWorkStudyLaunchpad/work/controlled-work-study/work-study-01/learners-v2.sqlite
  ```

- Linux terminal, step 4. Verify the new file:

  ```bash
  cd /home/lesliec/launchpad-dev && .venv/bin/python -B scripts/manage_real_data.py verify --db /opt/project/ITWorkStudyLaunchpad/work/controlled-work-study/work-study-01/learners-v2.sqlite
  ```

- Step 5. As root, the authorized operator copies the verified version-2 file into `/var/lib/launchpad/learners.sqlite` (owner `launchpad`, mode 0600) and runs `verify` again as `launchpad`.

  The copied accounts keep the controlled issuer namespace. They work in production only if production uses the same `LAUNCHPAD_AD_IDENTITY_NAMESPACE`.
- Step 6. Run `revoke-sessions` on the production copy so no test session carries over.

The migration copies every row unchanged. Every existing help request starts **Open**. The tests compare every original column, the accounts, the mentor assignments, sessions, audit rows and the dataset ID.

## Deployment sequence (after authorization)

This follows the existing [operator sequence](vm_deployment.md#operator-sequence-after-separate-deployment-authorization). Only the differences for this release are listed.

1. Decide on the backend certificate (decision 1) before Oct 23, 4:13 PM MDT.
2. Commit this worktree's changes on `dev/next-improvement` and review them. Build the release from that commit, not from `/opt/project/ITWorkStudyLaunchpad`, which holds the live controlled test and its uncommitted files.
3. Steps 1–4 of the runbook: approvals, archive, service identity, release and virtual environment. Run the full suite as non-root; it must report 438 tests OK and "Content validation passed."
4. Runbook step 5 with **Option A** (`initialize`, `verify`, `initialize-ad-state`, `verify-ad-state`), or with the Option B file. Then enroll each student and mentor (objectGUID entered at a private prompt), and grant only the approved mentor-to-learner assignments.
5. In `/etc/launchpad/launchpad.env`:
   - set `LAUNCHPAD_AD_SESSION_POLICY=signin` and `LAUNCHPAD_SESSION_MAX_HOURS=4`
   - leave both `LAUNCHPAD_AD_LOOKUP_*` values **empty**; startup refuses `signin` if they are set
   - set a new signing key, not the controlled test's
6. Runbook steps 6–8: start only `launchpad`, switch the `lesliec` route, and complete the VM verification.

   Add these release checks: one real student signs in, completes a module, saves a help request, signs out, signs in again and sees the step and the open request; their mentor sees the request read-only; a second learner cannot see it.

**Rollback:** close access with the maintenance page. Keep the new database. Never point the controlled-test code (schema version 1) at a version-2 file; it refuses to start. The Option B source remains unchanged.

## Verification done in development

- 438 automated tests and content validation, all passing. New tests cover the `signin` policy, startup refusals, idle and absolute expiry with accurate messages, immediate local disable and sign-out, the wording sweep across new, partway and completed learners plus mentor pages, the written-answer notice, and the full journey:

  sign in → Starting Point Check → module → activity → help request → sign out → sign in the next day in a new browser → saved progress and the open request are shown → resolve it

  The journey also confirms a second learner sees none of this.
- Migration check: a version-1 database created by the **unchanged live code** (synthetic, in the scratchpad) was refused by the new code, migrated to a new file and validated. The source file stayed byte-identical.
- Browser: headless Chromium against a loopback HTTPS server in real AD mode with the `signin` policy. Directory sign-in was simulated for invented accounts. 25 page views at 1280px and 390px covered sign-in, assessment, module, help request, sign-out, return, resolve and reopen by keyboard, Progress, Learn, path, and mentor overview and detail. There was no horizontal overflow, no unlabeled fields and no non-release wording; focus was visible. A password field that was cramped on the sign-in page was fixed.
- **Not verified:** real CCA LDAPS sign-in from this code; behavior behind the production Nginx/Unix-socket setup; screen readers, Firefox/Safari, 200% zoom and real phones.
