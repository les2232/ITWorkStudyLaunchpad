# IT Work Study Launchpad

IT Work Study Launchpad is an onboarding and training assistant for new IT work-study students, especially students with little or no prior IT background.

The system helps new student workers:
- Complete a pre-assessment
- Receive an adaptive training path
- Learn beginner IT concepts
- Complete Day 1 and Week 1 onboarding checklists
- Practice workflow and escalation scenarios
- Complete a post-assessment
- Generate mentor/supervisor summaries when stuck

## Product Philosophy

- Teach the mental model before the workflow.
- Use beginner-friendly, supportive language.
- Reinforce safe checks, clear documentation, and mentor escalation.
- Treat assessments as placement and growth tools, not pass/fail labels.
- Keep the assistant inside approved training content and safety boundaries.
- Do not include credentials, admin-only steps, sensitive internal procedures, real student data, or production integrations.

## MVP Focus

The first version focuses on:

1. Pre-assessment
2. Training path recommendation
3. IT Foundations content
4. Day 1 checklist
5. Week 1 checklist
6. Post-assessment
7. Supervisor summary output

## Current Status

Usable MVP prototype in progress.

Completed pieces:

- Project plan and chatbot behavior requirements
- Pre-assessment v1 and post-assessment v1
- Adaptive training paths
- Day 1 and Week 1 onboarding checklists
- Beginner IT foundation modules
- App-readable JSON manifests for modules, checklists, assessments, and training paths
- Flask web prototype
- Safe rule-based "Ask a Question" guidance
- "Report I'm Stuck" mentor-summary flow
- Basic supervisor overview
- Content validation and unit tests

Not included in this MVP:

- Full authentication or SSO
- Real student records
- Production database
- Teams or SharePoint integration
- Full chatbot or LLM integration
- Sensitive internal IT procedures
- Advanced analytics

## Setup

Use a local virtual environment:

```bash
python3 -m venv .venv
./.venv/bin/pip install -r requirements.txt
```

## Run Locally

```bash
./.venv/bin/flask --app app run --debug --host 0.0.0.0 --port 5000
```

Then open:

```text
http://127.0.0.1:5000
```

## Run Checks

After setup:

```bash
./.venv/bin/python scripts/check_all.py
```

The check command validates Markdown and JSON content, then runs the unit tests.

The tests cover:

- Assessment scoring
- Training path routing
- Content/checklist loading
- Safe guidance behavior
- Stuck summary generation

## Project Structure

```text
app.py                         Flask entrypoint
launchpad/                     App logic, content loading, scoring, guidance
templates/                     Jinja screens for the MVP prototype
static/                        CSS and lightweight client behavior
content/modules/               Human-readable training modules
content/checklists/            Day 1 and Week 1 checklist Markdown
content/assessments/           Human-readable assessment drafts
content/data/                  App-readable manifests and assessment data
docs/                          Planning and behavior requirements
scripts/check_all.py           One-command validation and tests
scripts/validate_content.py    Content and data validation
tests/                         Unit tests
```

## MVP Routes

- `/` home
- `/pre-assessment`
- `/assessment-results`
- `/training-path/<level>`
- `/modules`
- `/modules/<module>`
- `/day-1-checklist`
- `/week-1-checklist`
- `/ask`
- `/stuck`
- `/mentor-summary`
- `/post-assessment`
- `/supervisor`

## Known Next Steps

- Add a lightweight progress model if student progress needs to persist beyond browser-local checklist state.
- Add mentor review prompts and scenario practice pages.
- Improve free-response assessment review so mentors can score quality instead of relying on placeholder auto-credit.
- Add app route smoke tests once Flask is expected in every development environment.
- Separate glossary content into dedicated app-readable terms when the module list grows.
