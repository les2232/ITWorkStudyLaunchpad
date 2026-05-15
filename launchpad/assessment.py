from __future__ import annotations

from typing import Any

from .content import load_json


def load_assessment(assessment_id: str) -> dict[str, Any]:
    return load_json(f"{assessment_id}.json")


def all_questions(assessment: dict[str, Any]) -> list[dict[str, Any]]:
    questions: list[dict[str, Any]] = []
    for section in assessment.get("sections", []):
        questions.extend(section.get("questions", []))
    return questions


def score_assessment(assessment: dict[str, Any], responses: dict[str, Any]) -> dict[str, Any]:
    category_scores: dict[str, dict[str, float]] = {}
    question_results = []
    mentor_review_items = []

    for question in all_questions(assessment):
        category = question["category"]
        response = responses.get(question["id"])
        possible = float(question["points"])
        category_scores.setdefault(category, {"earned": 0.0, "possible": 0.0, "review_possible": 0.0})

        if is_mentor_review_question(question):
            category_scores[category]["review_possible"] += possible
            review_item = build_mentor_review_item(question, response)
            mentor_review_items.append(review_item)
            question_results.append(review_item)
            continue

        earned = score_question(question, response)
        category_scores[category]["earned"] += earned
        category_scores[category]["possible"] += possible
        question_results.append(
            {
                "id": question["id"],
                "prompt": question["prompt"],
                "earned": earned,
                "possible": possible,
                "explanation": question.get("explanation"),
                "mentor_review_needed": False,
            }
        )

    total_earned = sum(score["earned"] for score in category_scores.values())
    total_possible = sum(score["possible"] for score in category_scores.values())
    mentor_review_possible = sum(score["review_possible"] for score in category_scores.values())
    percentage = (total_earned / total_possible) * 100 if total_possible else 0

    categories = []
    for name, score in category_scores.items():
        possible = score["possible"]
        percent = (score["earned"] / possible) * 100 if possible else 0
        categories.append(
            {
                "name": name,
                "earned": _clean_number(score["earned"]),
                "possible": _clean_number(possible),
                "review_possible": _clean_number(score["review_possible"]),
                "percent": round(percent),
            }
        )

    return {
        "assessment_id": assessment["id"],
        "score": round(percentage),
        "earned": _clean_number(total_earned),
        "possible": _clean_number(total_possible),
        "mentor_review_points_possible": _clean_number(mentor_review_possible),
        "mentor_review_items": mentor_review_items,
        "categories": categories,
        "questions": question_results,
    }


def score_question(question: dict[str, Any], response: Any) -> float:
    question_type = question["type"]

    if question_type in {"multiple_choice", "rating"}:
        answer = str(response or "")
        if "score_map" in question:
            return float(question["score_map"].get(answer, 0))
        return float(question["points"]) if answer == question.get("correct_answer") else 0.0

    if question_type == "select_all":
        selected = set(response or [])
        scoring = question.get("scoring", {})
        none_value = scoring.get("none_value")
        if none_value and none_value in selected:
            relevant_count = 0
        else:
            relevant_count = len(selected)
        for rule in scoring.get("count_rules", []):
            minimum = rule.get("min", 0)
            maximum = rule.get("max")
            if relevant_count >= minimum and (maximum is None or relevant_count <= maximum):
                return float(rule["points"])
        return 0.0

    if question_type == "free_response":
        return 0.0

    return 0.0


def is_mentor_review_question(question: dict[str, Any]) -> bool:
    return question.get("mentor_review_needed") is True or question.get("type") == "free_response"


def build_mentor_review_item(question: dict[str, Any], response: Any) -> dict[str, Any]:
    return {
        "id": question["id"],
        "prompt": question["prompt"],
        "category": question["category"],
        "earned": None,
        "possible": _clean_number(float(question["points"])),
        "response": str(response or "").strip(),
        "mentor_review_needed": True,
        "review_rubric": question.get("review_rubric", default_review_rubric()),
        "mentor_use": question.get("mentor_use"),
    }


def default_review_rubric() -> list[str]:
    return [
        "Understands safe beginner boundaries.",
        "Knows when to escalate.",
        "Explains the issue clearly.",
        "Uses beginner-safe documentation language.",
    ]


def get_training_path(score: int) -> dict[str, Any]:
    paths = load_json("training_paths.json")
    for level in paths["levels"]:
        if level["min_score"] <= score <= level["max_score"]:
            return level
    return paths["levels"][-1]


def get_post_readiness(assessment: dict[str, Any], score: int) -> dict[str, Any] | None:
    for level in assessment.get("readiness_levels", []):
        if level["min_score"] <= score <= level["max_score"]:
            return level
    return None


def knowledge_gaps(result: dict[str, Any], threshold: int = 70) -> list[dict[str, Any]]:
    paths = load_json("training_paths.json")
    categories_by_name = {category["name"]: category for category in result["categories"]}
    gaps = []

    for route in paths.get("knowledge_gap_routing", []):
        category = categories_by_name.get(route["category"])
        if category and category["percent"] < threshold:
            gaps.append(
                {
                    "area": route["area"],
                    "percent": category["percent"],
                    "recommended_modules": route["recommended_modules"],
                }
            )

    return gaps


def collect_form_responses(assessment: dict[str, Any], form: Any) -> dict[str, Any]:
    responses = {}
    for question in all_questions(assessment):
        if question["type"] == "select_all":
            responses[question["id"]] = form.getlist(question["id"])
        else:
            responses[question["id"]] = form.get(question["id"], "")
    return responses


def _clean_number(value: float) -> int | float:
    if float(value).is_integer():
        return int(value)
    return round(value, 2)
