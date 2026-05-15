from __future__ import annotations

from typing import Any

from .content import load_json


def list_scenarios() -> list[dict[str, Any]]:
    return load_json("scenarios.json")


def get_scenario(scenario_id: str) -> dict[str, Any] | None:
    for scenario in list_scenarios():
        if scenario["id"] == scenario_id:
            return scenario
    return None


def scenarios_for_path(path_slug: str) -> list[dict[str, Any]]:
    return [
        scenario
        for scenario in list_scenarios()
        if path_slug in scenario.get("readiness_levels", [])
    ]


def build_feedback(scenario: dict[str, Any], student_response: str) -> dict[str, Any]:
    response = " ".join(str(student_response or "").split())
    return {
        "scenario_id": scenario["id"],
        "scenario_title": scenario["title"],
        "student_response": response,
        "mentor_feedback": scenario["mentor_feedback"],
        "safe_actions": scenario["safe_actions"],
        "document": scenario["document"],
        "ask_mentor_when": scenario["ask_mentor_when"],
        "avoid": scenario["avoid"],
        "needs_mentor_review": True,
        "review_note": "This practice response is not auto-graded. A mentor should review whether the student recognized safe boundaries, documentation needs, and escalation points.",
    }
