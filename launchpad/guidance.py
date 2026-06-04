from __future__ import annotations


def answer_question(question: str) -> dict[str, object]:
    text = " ".join(question.lower().split())

    if not text:
        return _response(
            "Ask a beginner IT question",
            [
                "Type the term, workflow, or situation you want help understanding.",
                "If you are actively stuck, use I'm Stuck so you can create a mentor-ready summary.",
            ],
        )

    if any(word in text for word in ["embarrassed", "dumb", "stupid", "basic question"]):
        return _response(
            "It is okay to ask",
            [
                "You are not expected to know everything on Day 1. Beginner questions are part of learning IT safely.",
                "A good mentor question could be: I am still learning this part. Can you explain how this fits into our workflow?",
            ],
            related_module="how_to_ask_for_help",
        )

    if "domain" in text:
        return _response(
            "Domain",
            [
                "A domain is a managed environment the organization uses for accounts, computers, and access.",
                "As a new work-study student, you do not manage the domain. You only need the mental model so logins, permissions, and managed computers make more sense.",
            ],
            related_module="domain_basics",
        )

    if "sccm" in text or "configuration manager" in text:
        return _response(
            "Configuration Manager",
            [
                "Configuration Manager, often still called SCCM, is used by many IT departments to manage computers, deploy software, run updates, and support imaging.",
                "This app can explain what it is for, but it will not provide admin-only procedures or task-sequence steps.",
            ],
            related_module="configuration_manager_overview",
        )

    if "asset tag" in text or "asset" in text:
        return _response(
            "Asset Tags",
            [
                "An asset tag is a label or ID used to track equipment so IT knows which device is which.",
                "Do not remove, replace, change, or guess an asset tag. If it is missing or unreadable, document that and ask your mentor.",
            ],
            related_module="asset_tag_basics",
        )

    if "ticket" in text or "work order" in text or "draft note" in text:
        return _response(
            "Tickets and Draft Notes",
            [
                "A ticket is a record of an issue, request, task, or support interaction.",
                "As a new student, focus on draft notes for mentor review: issue, what you checked, what happened, and what still needs to happen.",
                "Do not create, edit, close, or update tickets/work orders until you are trained and authorized.",
            ],
            related_module="ticket_basics",
        )

    if "monitor" in text or "no signal" in text:
        return _response(
            "Monitor Check",
            [
                "If your department allows beginner checks, collect simple facts: does the monitor have power, is the display cable connected, is the computer on, and is the input/source correct?",
                "Do not reimage, change system settings, or guess. If the issue remains or anything is unfamiliar, document what you saw and ask your mentor.",
            ],
            related_module="hardware_basics",
        )

    if "keyboard" in text or "mouse" in text:
        return _response(
            "Keyboard or Mouse Check",
            [
                "If approved, a beginner-safe check may include confirming the connection or trying a known-working keyboard or mouse.",
                "Document exactly what you checked and what happened. Ask your mentor before changing settings or opening equipment.",
            ],
            related_module="hardware_basics",
        )

    if "imaging" in text or "image" in text:
        if any(word in text for word in ["which", "error", "failed", "task sequence", "workflow", "stuck"]):
            return _escalate(
                "Imaging needs mentor confirmation",
                "Imaging choices and unfamiliar imaging errors should be escalated. Stop, write down the asset tag or device name, the exact message, and what step you were on."
            )
        return _response(
            "Computer Imaging",
            [
                "Computer imaging means preparing a computer with the required operating system, software, settings, and configuration.",
                "The safe beginner mental model is to understand what imaging is for, not to choose images or run internal procedures on your own.",
            ],
            related_module="imaging_overview",
        )

    if any(word in text for word in ["password", "mfa", "permission", "admin", "delete", "sensitive", "user files", "bypass", "access issue", "cannot log in"]):
        return _escalate(
            "Ask a mentor before continuing",
            "This sounds like it may involve access, permissions, MFA, admin rights, sensitive data, or user files. Those are not beginner-only tasks."
        )

    if "escalate" in text or "stuck" in text or "unsure" in text:
        return _escalate(
            "Asking for help is appropriate",
            "If you are unsure, stop and ask. Write down the issue, what you checked, the result, and what help you need."
        )

    return _escalate(
        "No approved procedure found",
        "I do not have an approved procedure for that yet. Please ask your mentor or the IT tech on duty before continuing."
    )


def _response(title: str, paragraphs: list[str], related_module: str | None = None) -> dict[str, object]:
    return {
        "title": title,
        "paragraphs": paragraphs,
        "should_escalate": False,
        "related_module": related_module,
    }


def _escalate(title: str, detail: str) -> dict[str, object]:
    return {
        "title": title,
        "paragraphs": [
            detail,
            "I can help you turn this into a mentor summary. Use I'm Stuck if you want a clean message to share.",
        ],
        "should_escalate": True,
        "related_module": "escalation_rules",
    }
