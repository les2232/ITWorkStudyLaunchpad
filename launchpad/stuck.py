from __future__ import annotations

from typing import Mapping


SUMMARY_FIELDS = [
    ("student", "Student"),
    ("topic", "Topic"),
    ("trying_to_do", "What the student was trying to do"),
    ("what_happened", "What happened"),
    ("already_checked", "Steps already tried"),
    ("current_blocker", "Current blocker"),
    ("related_item", "Relevant module/checklist item"),
]


def generate_stuck_summary(data: Mapping[str, str]) -> str:
    student = _clean(data.get("student")) or "Not provided"
    topic = _clean(data.get("topic")) or "Not provided"
    trying = _clean(data.get("trying_to_do")) or "Not provided"
    happened = _clean(data.get("what_happened")) or "Not provided"
    checked = _clean(data.get("already_checked")) or "Not provided"
    blocker = _clean(data.get("current_blocker")) or "Not provided"
    related = _clean(data.get("related_item")) or "Not provided"

    return "\n".join(
        [
            "Work-study student needs help.",
            "",
            f"Student: {student}",
            f"Topic: {topic}",
            f"Issue: The student was trying to {trying}.",
            f"What happened: {happened}",
            f"Steps already tried: {checked}",
            f"Current blocker: {blocker}",
            f"Relevant module/checklist item: {related}",
            "Suggested next action: Stop here, share this summary with a mentor or IT tech, and wait for the next approved step.",
        ]
    )


def _clean(value: str | None) -> str:
    return " ".join(str(value or "").split())
