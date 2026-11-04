# Public release review

## Verdict

**Conditionally suitable for a public portfolio after the actions below are reviewed.** The tracked tree contains general training content and synthetic examples. No real student record, database, environment file, credential, token, internal hostname, private IP, ticket number, device identifier, or exact `CCA` reference was found. Public release is not approval for real-student or production use.

## Safe-to-publish components

- Flask code, templates, and styling for the local prototype.
- General beginner IT modules, assessments, checklists, scenarios, and quizzes.
- Synthetic-data tests and validation scripts.
- Documentation that retains the prototype caveats.
- General SCCM/Configuration Manager, Teams, and SharePoint references; no internal integration details were found.

## Findings requiring action, verification, or approval

| Location | Finding | Recommended treatment |
| --- | --- | --- |
| Git commit metadata | Author names and `lescordova22@gmail.com` appear throughout history. | Confirm publication approval or sanitize history; do not rewrite without explicit approval. |
| `launchpad/web.py:54` | A development-only fallback secret makes sessions forgeable when no runtime secret is supplied. | Require a supplied secret before non-local use and do not claim production security. |
| `docs/project_plan.md`, `docs/chatbot_requirements.md` | Teams and SharePoint are future planning concepts. | Retain only if intended; do not imply implemented or approved integrations. |
| General curriculum | Department-approval language is generic, but ownership was not established by this review. | Verify the content is original or approved and contains no restricted institutional material. |
| Repository history | Current tracked content and metadata were reviewed, not every historical blob. | Run a dedicated history and secret scan before publication. |

## Files that must never be committed

Do not commit `.env`, databases (`instance/`, `*.sqlite`, `*.sqlite3`, `*.db`), browser/session data, unsanitized pilot evidence, credentials, keys, certificates, virtual environments, caches, logs, or test artifacts. Current ignore rules cover the local environment, Python caches, environment files, database extensions, and `instance/`; ignored local copies were present but untracked.

## Recommended actions

1. Approve or sanitize Git author identity and email.
2. Scan all historical objects for secrets and removed data.
3. Obtain content-owner approval for curriculum and planning documents.
4. Use only synthetic screenshots and remove local paths, cookies, names, URLs, timestamps, database details, and notifications.
5. Preserve synthetic-only and non-production limitations; never publish pilot databases or raw evidence.

## README, screenshots, and history

The README needed clearer audience and safety boundaries, architecture, loopback-only setup, validation/pilot links, and limitations; bounded changes are pending.

Sanitized screenshots are recommended for portfolio polish but are not required for safe source publication. Repository history still needs review because commit metadata exposes a personal identity/email and deleted historical content has not received a dedicated scan.
