# IT Work Study Launchpad Project Plan

## Project Goal

IT Work Study Launchpad is an onboarding and support assistant for new IT work-study students, especially students with little or no prior IT background.

The system helps new student workers:

- Complete a pre-assessment
- Receive an adaptive training path
- Learn beginner IT concepts
- Complete Day 1 and Week 1 onboarding checklists
- Ask beginner questions privately through a helpful chatbot
- Practice workflow and escalation scenarios
- Generate mentor/supervisor summaries when stuck
- Complete a post-assessment to measure growth and beginner readiness

The project should feel like a guided onboarding and training system, not just a chatbot.

---

## Core Problem

New IT work-study students often feel lost because they may not understand:

- What a domain is
- What SCCM / Configuration Manager is
- What computer imaging means
- What tickets are for
- How to document work and prepare mentor summaries
- What tasks are beginner-safe
- When to stop and ask for help
- How IT workflows actually work

Some students may feel embarrassed asking basic questions, especially when they are new to IT. The Launchpad should give them a safe first place to learn, ask, and prepare better questions for mentors.

---

## Primary Users

### New IT Work-Study Students

They need:

- Clear onboarding steps
- Beginner-friendly explanations
- A safe place to ask questions
- Help understanding IT terms and workflows
- Guidance on when to escalate
- Confidence during their first shifts

### Mentors / IT Techs / IT Directors

They need:

- More consistent onboarding
- Fewer repeated beginner questions
- Visibility into student progress
- Knowledge of student confidence and gaps
- Cleaner escalation summaries
- Evidence of growth from pre- to post-assessment

---

## MVP Scope

### Must Have

1. Pre-assessment
2. Training path recommendation
3. IT Foundations modules
4. Day 1 checklist
5. Week 1 checklist
6. Helpful chatbot requirements
7. Report I'm Stuck flow
8. Mentor/supervisor summary templates
9. Post-assessment
10. Basic supervisor view requirements

### Should Have

1. Confidence tracking
2. Scenario-based practice
3. IT glossary
4. Draft ticket note writing practice
5. Beginner-safe troubleshooting guidance

### Not Yet

1. Full Teams integration
2. Full SharePoint integration
3. Authentication / SSO
4. Real student data
5. Sensitive internal procedures
6. Full imaging step-by-step procedures
7. HR/payroll/legal advice
8. Advanced analytics

---

## Version 1 Philosophy

The first version should teach the mental model before the workflow.

A new student should understand:

- What the task is
- Why it matters
- What they are allowed to do
- What they should not do
- When to ask a mentor
- What to document

The system should repeatedly reinforce:

> Do beginner-safe checks. Document what happened. Do not guess. Ask your mentor or supervisor when unsure.

---

## Project Phases

## Phase 0: Project Setup

### Goal

Create a clean repository structure and baseline documentation.

### Deliverables

- `README.md`
- `.gitignore`
- `docs/project_plan.md`
- `docs/chatbot_requirements.md`
- `content/assessments/pre_assessment_v1.md`

### Status

Complete.

---

## Phase 1: Assessment System

### Goal

Create a pre-assessment and post-assessment that measure student knowledge, confidence, and growth.

### Deliverables

- `content/assessments/pre_assessment_v1.md`
- `content/assessments/post_assessment_v1.md`
- Scoring categories
- Readiness levels
- Training path recommendation logic
- Pre/post growth report template

### Status

In progress. The pre-assessment and post-assessment drafts exist. The next refinement is turning scoring and growth reporting into app-ready data structures.

### Pre-Assessment Categories

- Background / Experience
- Confidence
- IT Vocabulary
- Beginner Troubleshooting
- Workflow and Escalation

### Post-Assessment Categories

- Vocabulary improvement
- Hardware workflow
- Imaging understanding
- Draft ticket note quality
- Escalation judgment
- Confidence reflection

---

## Phase 2: Adaptive Training Paths

### Goal

Define what training path each student receives after the pre-assessment.

### Deliverable

- `docs/training_paths.md`

### Status

Draft complete.

### Training Paths

1. Beginner
2. Developing
3. Ready to Shadow
4. Advanced Beginner

Each path should include:

- Required modules
- Review modules
- Checklist items
- Scenario practice
- Mentor check-in expectations

---

## Phase 3: IT Foundations Content

### Goal

Create beginner-friendly modules for students with little or no IT background.

### Deliverables

- `content/modules/common_it_words.md`
- `content/modules/what_does_it_do.md`
- `content/modules/domain_basics.md`
- `content/modules/configuration_manager_overview.md`
- `content/modules/imaging_overview.md`
- `content/modules/ticket_basics.md`
- `content/modules/asset_tag_basics.md`
- `content/modules/hardware_basics.md`
- `content/modules/how_to_ask_for_help.md`
- `content/modules/escalation_rules.md`

### Status

Initial module set complete. Next refinement should focus on scenario practice, mentor review prompts, and consistency passes.

### Module Format

Each module should include:

- Goal
- Plain-language explanation
- Why this matters
- What you need to know
- Common beginner mistakes
- When to ask for help
- Quick check

---

## Phase 4: Checklists

### Goal

Create Day 1 and Week 1 onboarding checklists.

### Deliverables

- `content/checklists/day_1_checklist.md`
- `content/checklists/week_1_checklist.md`

### Status

Initial checklist drafts complete.

### Day 1 Checklist Should Include

- Computer login
- Email/Outlook
- Teams
- Ticketing system
- Inventory system
- Timekeeping system
- Timesheet instructions
- Supervisor/mentor identification
- Department expectations
- Confidentiality
- How to ask for help
- Shadowing
- Short quiz
- First-day check-in

### Week 1 Checklist Should Include

- Draft ticket note basics
- Hardware basics
- Imaging overview
- Equipment movement/delivery
- Classroom/lab checks
- Inventory tagging overview
- Escalation rules
- Scenario practice
- Supervisor/mentor meeting
- Readiness approval

---

## Phase 5: Chatbot Behavior Design

### Goal

Define how the chatbot should support students safely.

### Deliverables

- `docs/chatbot_requirements.md`
- `docs/escalation_policy.md`
- `docs/assistant_behavior.md`
- `content/glossary/it_terms.md`

### Status

In progress. Chatbot requirements exist. Escalation policy, assistant behavior guidance, and glossary remain to be separated into dedicated files.

### Chatbot Should Help With

- Explaining beginner IT terms
- Explaining onboarding tasks
- Walking through beginner-safe troubleshooting
- Helping students draft ticket notes or mentor summaries
- Helping students decide whether to escalate
- Generating mentor summaries
- Encouraging students who feel embarrassed to ask questions

### Chatbot Must Not

- Invent procedures
- Give restricted admin instructions
- Share credentials
- Provide sensitive internal steps
- Tell inexperienced students to create, edit, close, or update tickets/work orders before training and approval
- Replace mentor approval
- Answer HR/legal/payroll questions beyond approved onboarding content

---

## Phase 6: App Prototype

### Goal

Build a simple web prototype after the content structure is stable.

### Possible Stack

- Flask or FastAPI
- Jinja templates or simple frontend
- SQLite
- Markdown content files

### Initial Screens

- Home
- Pre-assessment
- Assessment result
- Training path
- Checklist
- Module reader
- Ask a question
- Report I'm stuck
- Supervisor summary
- Post-assessment

---

## Phase 7: Content Validation

### Goal

Add simple scripts to keep content consistent as the project grows.

### Deliverables

- `scripts/validate_content.py`
- `scripts/check_all.py`

### Status

In progress.

### Validation Should Check

- Required headings exist in modules
- Assessments include answers and explanations
- Checklists include clear items
- No unresolved placeholder markers in release-ready files
- No sensitive placeholders are accidentally included

---

## Phase 8: Teams and SharePoint Planning

### Goal

Plan future integration without distracting from the MVP.

### Deliverable

- `docs/teams_sharepoint_integration_plan.md`

### Future Use

| Tool | Purpose |
|---|---|
| Teams | Main access point, mentor contact, notifications |
| SharePoint | Approved training docs |
| SharePoint Lists | Progress, check-ins, escalations |
| Web App | Main interface |

---

## Working Rules

1. Content first, app second.
2. Keep commits small and focused.
3. Do not include sensitive procedures.
4. Do not include credentials, internal secrets, or restricted admin steps.
5. Every training file should explain what the concept is, why it matters, and when to ask for help.
6. The chatbot should answer only from approved content.
7. When unsure, the system should help the student ask a mentor clearly.
8. The goal is support and readiness, not punishment or gatekeeping.

---

## Milestones

### Milestone 1: Planning Foundation

- [ ] README exists
- [ ] Project plan exists
- [ ] Chatbot requirements exist
- [ ] Pre-assessment draft exists
- [ ] Initial commits are clean

### Milestone 2: Assessment System

- [ ] Pre-assessment finalized
- [ ] Training path logic documented
- [ ] Post-assessment drafted
- [ ] Growth report template drafted

### Milestone 3: Training Content

- [ ] Common IT Words
- [ ] Domain Basics
- [ ] SCCM / Configuration Manager Overview
- [ ] Imaging Overview
- [ ] Ticket Basics
- [ ] Hardware Basics
- [ ] Escalation Rules

### Milestone 4: Onboarding Flow

- [ ] Day 1 checklist
- [ ] Week 1 checklist
- [ ] First-day check-in
- [ ] Report I'm Stuck flow
- [ ] Mentor summary templates

### Milestone 5: Prototype

- [ ] Basic web app
- [ ] Pre-assessment page
- [ ] Training path result
- [ ] Module viewer
- [ ] Checklist tracker
- [ ] Ask a question page
- [ ] Supervisor view
