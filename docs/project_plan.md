# IT Work Study Launchpad Project Plan

## Project Goal

IT Work Study Launchpad is an onboarding and support assistant for new IT work-study students, especially students with little or no prior IT background.

The system helps new student workers:

- Complete a pre-assessment
- Receive an adaptive training path
- Learn beginner IT concepts
- Complete short module knowledge checks
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
4. Module knowledge checks
5. Day 1 checklist
6. Week 1 checklist
7. Helpful chatbot requirements
8. Report I'm Stuck flow
9. Mentor/supervisor summary templates
10. Post-assessment
11. Basic supervisor view requirements

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

MVP complete for demo. The pre-assessment and post-assessment exist as Markdown drafts and app-readable JSON. Scoring supports auto-scored category breakdowns, readiness levels, training path recommendations, and separate mentor-review free-response items.

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

MVP complete for demo. App-readable training path data supports score-based routing, linked path steps, scenario practice recommendations, post-assessment discovery, and knowledge gap recommendations.

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
- `content/data/module_quizzes.json`

### Status

MVP complete for demo. Module manifest data allows the web prototype to load modules programmatically, and each module has a short, low-stakes knowledge check in app-readable JSON.

### Module Format

Each module should include:

- Goal
- Plain-language explanation
- Why this matters
- What you need to know
- Common beginner mistakes
- When to ask for help
- Quick check
- Short low-stakes knowledge check

---

## Phase 4: Checklists

### Goal

Create Day 1 and Week 1 onboarding checklists.

### Deliverables

- `content/checklists/day_1_checklist.md`
- `content/checklists/week_1_checklist.md`

### Status

MVP complete for demo. Checklist manifest data allows the web prototype to load Day 1 and Week 1 checklists programmatically, and local demo progress can save checked items.

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
- Safe rule-based Ask a Question prototype

### Status

MVP complete for demo. Chatbot requirements exist, and the prototype includes a safe rule-based Ask a Question page. A full chatbot, separate glossary data, and broader assistant behavior documentation remain future work.

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
- Module knowledge check
- Scenario practice
- Saved local progress

### Status

MVP complete for local demo. A Flask prototype now includes the initial MVP screens, structured content loading, pre/post assessment scoring, training path recommendation, module knowledge checks, safe guidance, stuck summary generation, saved local demo progress, and a basic supervisor overview. It does not store real student records or provide authentication.

---

## Phase 7: Content Validation

### Goal

Add simple scripts to keep content consistent as the project grows.

### Deliverables

- `scripts/validate_content.py`
- `scripts/check_all.py`

### Status

MVP complete for demo. Validation checks required Markdown structure, required JSON data files, manifest fields, path existence, module quiz data, assessment question fields, and assessment point totals. `scripts/check_all.py` runs validation and unit tests.

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

- Future integration plan

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

- [x] README exists
- [x] Project plan exists
- [x] Chatbot requirements exist
- [x] Pre-assessment draft exists
- [x] Initial commits are clean

### Milestone 2: Assessment System

- [x] Pre-assessment finalized for MVP
- [x] Training path logic documented
- [x] Post-assessment drafted
- [x] Auto-scored and mentor-review scoring clarified

### Milestone 3: Training Content

- [x] Common IT Words
- [x] Domain Basics
- [x] SCCM / Configuration Manager Overview
- [x] Imaging Overview
- [x] Ticket Basics
- [x] Hardware Basics
- [x] Escalation Rules
- [x] Module knowledge checks

### Milestone 4: Onboarding Flow

- [x] Day 1 checklist
- [x] Week 1 checklist
- [x] Scenario practice
- [x] Report I'm Stuck flow
- [x] Mentor summary templates

### Milestone 5: Prototype

- [x] Basic web app
- [x] Pre-assessment page
- [x] Training path result
- [x] Module viewer
- [x] Checklist tracker
- [x] Module knowledge checks
- [x] Ask a question page
- [x] Supervisor view
