from __future__ import annotations

from typing import Any

from .content import load_json


GUIDED_TROUBLESHOOTING = "guided_troubleshooting"


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


def is_guided_scenario(scenario: dict[str, Any]) -> bool:
    return scenario.get("scenario_type") == GUIDED_TROUBLESHOOTING


def guided_inspections(scenario: dict[str, Any]) -> list[dict[str, str]]:
    inspections_by_id = {
        inspection.get("id"): inspection
        for inspection in scenario.get("inspections", [])
        if isinstance(inspection, dict) and isinstance(inspection.get("id"), str)
    }
    return [
        inspections_by_id[inspection_id]
        for inspection_id in scenario.get("required_inspections", [])
        if inspection_id in inspections_by_id
    ]


def scenario_controlled_activity_ids() -> set[str]:
    return {
        scenario["activity_id"]
        for scenario in list_scenarios()
        if is_guided_scenario(scenario) and isinstance(scenario.get("activity_id"), str)
    }


def initial_guided_state() -> dict[str, Any]:
    return {
        "inspected": [],
        "resolved": False,
        "feedback": (
            "Start by inspecting the workstation. Gather the visible facts before choosing a fix."
        ),
        "feedback_tone": "info",
        "last_action": None,
    }


def normalize_guided_state(scenario: dict[str, Any], state: Any) -> dict[str, Any]:
    normalized = initial_guided_state()
    if not isinstance(state, dict):
        return normalized

    required = scenario.get("required_inspections", [])
    inspected = state.get("inspected", [])
    if isinstance(inspected, list):
        inspected_values = {value for value in inspected if isinstance(value, str)}
        normalized["inspected"] = [
            inspection_id for inspection_id in required if inspection_id in inspected_values
        ]

    action_ids = {
        action.get("id")
        for action in scenario.get("actions", [])
        if isinstance(action, dict) and isinstance(action.get("id"), str)
    }
    last_action = state.get("last_action")
    if last_action in action_ids or last_action in required:
        normalized["last_action"] = last_action

    feedback = state.get("feedback")
    if isinstance(feedback, str) and feedback.strip():
        normalized["feedback"] = " ".join(feedback.split())[:500]
    if state.get("feedback_tone") in {"info", "safe", "success"}:
        normalized["feedback_tone"] = state["feedback_tone"]

    resolution = scenario.get("resolution", {})
    resolution_action = resolution.get("action_id") if isinstance(resolution, dict) else None
    has_all_inspections = all(
        inspection_id in normalized["inspected"] for inspection_id in required
    )
    normalized["resolved"] = bool(
        state.get("resolved")
        and has_all_inspections
        and normalized["last_action"] == resolution_action
    )
    if normalized["resolved"]:
        normalized["feedback_tone"] = "success"
    return normalized


def apply_guided_action(
    scenario: dict[str, Any],
    state: Any,
    action_id: str,
) -> dict[str, Any] | None:
    if not is_guided_scenario(scenario) or not isinstance(action_id, str):
        return None

    next_state = normalize_guided_state(scenario, state)
    inspections = {
        inspection["id"]: inspection
        for inspection in guided_inspections(scenario)
    }
    if action_id in inspections:
        if action_id not in next_state["inspected"]:
            next_state["inspected"].append(action_id)
        next_state["last_action"] = action_id
        next_state["feedback"] = inspections[action_id]["feedback"]
        next_state["feedback_tone"] = "info"
        next_state["resolved"] = False
        return next_state

    actions = {
        action.get("id"): action
        for action in scenario.get("actions", [])
        if isinstance(action, dict) and isinstance(action.get("id"), str)
    }
    action = actions.get(action_id)
    if action is None:
        return None

    next_state["last_action"] = action_id
    if action.get("kind") != "resolution":
        next_state["feedback"] = action["feedback"]
        next_state["feedback_tone"] = "safe"
        next_state["resolved"] = False
        return next_state

    missing = [
        inspection["label"]
        for inspection in guided_inspections(scenario)
        if inspection["id"] not in next_state["inspected"]
    ]
    if missing:
        next_state["feedback"] = (
            "Pause before reconnecting the cable. Inspect these items first: "
            + ", ".join(missing)
            + "."
        )
        next_state["feedback_tone"] = "safe"
        next_state["resolved"] = False
        return next_state

    resolution = scenario.get("resolution", {})
    if action_id != resolution.get("action_id"):
        return None
    next_state["resolved"] = True
    next_state["feedback"] = resolution["confirmation"]
    next_state["feedback_tone"] = "success"
    return next_state


def guided_scenario_can_finish(scenario: dict[str, Any], state: Any) -> bool:
    normalized = normalize_guided_state(scenario, state)
    required = scenario.get("required_inspections", [])
    resolution = scenario.get("resolution", {})
    return bool(
        normalized["resolved"]
        and all(item in normalized["inspected"] for item in required)
        and normalized["last_action"] == resolution.get("action_id")
    )


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
