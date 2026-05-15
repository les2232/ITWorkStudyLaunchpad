from __future__ import annotations

from typing import Any

from .content import load_json


ROLE_ALIGNMENT_SCOPE = "role_alignment"


def load_assessment(assessment_id: str) -> dict[str, Any]:
    return load_json(f"{assessment_id}.json")


def all_questions(assessment: dict[str, Any]) -> list[dict[str, Any]]:
    questions: list[dict[str, Any]] = []
    for section in assessment.get("sections", []):
        for question in section.get("questions", []):
            item = dict(question)
            if section.get("score_scope") and "score_scope" not in item:
                item["score_scope"] = section["score_scope"]
            item.setdefault("section_title", section.get("title", ""))
            questions.append(item)
    return questions


def score_assessment(assessment: dict[str, Any], responses: dict[str, Any]) -> dict[str, Any]:
    category_scores: dict[str, dict[str, float]] = {}
    question_results = []
    mentor_review_items = []
    role_questions = []

    for question in all_questions(assessment):
        if is_role_alignment_question(question):
            role_questions.append(question)
            continue

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

    result = {
        "assessment_id": assessment["id"],
        "score": round(percentage),
        "earned": _clean_number(total_earned),
        "possible": _clean_number(total_possible),
        "mentor_review_points_possible": _clean_number(mentor_review_possible),
        "mentor_review_items": mentor_review_items,
        "categories": categories,
        "questions": question_results,
    }

    role_alignment = score_role_alignment(assessment, responses, role_questions)
    if role_alignment:
        result["role_alignment"] = role_alignment

    return result


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


def is_role_alignment_question(question: dict[str, Any]) -> bool:
    return question.get("score_scope") == ROLE_ALIGNMENT_SCOPE


def role_alignment_questions(assessment: dict[str, Any]) -> list[dict[str, Any]]:
    return [question for question in all_questions(assessment) if is_role_alignment_question(question)]


def score_role_alignment(
    assessment: dict[str, Any],
    responses: dict[str, Any],
    questions: list[dict[str, Any]] | None = None,
) -> dict[str, Any] | None:
    questions = questions if questions is not None else role_alignment_questions(assessment)
    if not questions:
        return None

    config = assessment.get("role_alignment", {})
    signal_metadata = _role_signal_metadata(config, questions)
    signal_scores = {slug: 0.0 for slug in signal_metadata}
    signal_possible = {slug: 0.0 for slug in signal_metadata}
    question_results = []
    answered_count = 0

    for question in questions:
        options = question.get("options", [])
        selected_value = str(responses.get(question["id"]) or "")
        selected_option = next((option for option in options if option.get("value") == selected_value), None)

        for slug in signal_metadata:
            max_value = max(float(option.get("signals", {}).get(slug, 0)) for option in options) if options else 0
            signal_possible[slug] += max_value

        if selected_option is None:
            continue

        answered_count += 1
        selected_signals = selected_option.get("signals", {})
        for slug, value in selected_signals.items():
            signal_scores.setdefault(slug, 0.0)
            signal_possible.setdefault(slug, 0.0)
            signal_scores[slug] += float(value)

        question_results.append(
            {
                "id": question["id"],
                "prompt": question["prompt"],
                "selected_value": selected_value,
                "selected_label": selected_option.get("label", ""),
                "alignment_tags": selected_option.get("alignment_tags", []),
                "signals": selected_signals,
            }
        )

    if answered_count == 0:
        return None

    signals = []
    for slug, metadata in signal_metadata.items():
        possible = signal_possible.get(slug, 0.0)
        score = signal_scores.get(slug, 0.0)
        percent = round((score / possible) * 100) if possible else 0
        signals.append(
            {
                "slug": slug,
                "label": metadata["label"],
                "description": metadata.get("description", ""),
                "score": _clean_number(score),
                "possible": _clean_number(possible),
                "percent": percent,
                "level": _role_signal_level(metadata.get("direction", "strength"), percent),
            }
        )

    recommendation = _classify_role_alignment(signals, config)

    return {
        "title": config.get("title", "Work Style and Role Alignment"),
        "answered_questions": answered_count,
        "signals": signals,
        "recommended_alignment": recommendation,
        "question_results": question_results,
        "mentor_note": (
            "Use this as a planning signal alongside the technical readiness path, "
            "not as a pass/fail placement decision."
        ),
    }


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


def _role_signal_metadata(config: dict[str, Any], questions: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    metadata = {
        signal["slug"]: signal
        for signal in config.get("signals", [])
        if signal.get("slug") and signal.get("label")
    }

    for question in questions:
        for option in question.get("options", []):
            for slug in option.get("signals", {}):
                metadata.setdefault(
                    slug,
                    {
                        "slug": slug,
                        "label": slug.replace("_", " ").title(),
                        "direction": "strength",
                        "description": "",
                    },
                )

    return metadata


def _role_signal_level(direction: str, percent: int) -> str:
    if direction == "need":
        if percent >= 60:
            return "Higher"
        if percent >= 30:
            return "Moderate"
        return "Lower"

    if direction == "readiness":
        if percent >= 67:
            return "Strong"
        if percent >= 34:
            return "Developing"
        return "Support needed"

    if percent >= 67:
        return "Strong signal"
    if percent >= 34:
        return "Moderate signal"
    return "Lower signal"


def _classify_role_alignment(signals: list[dict[str, Any]], config: dict[str, Any]) -> dict[str, Any]:
    percentages = {signal["slug"]: signal["percent"] for signal in signals}
    tech = percentages.get("technical_troubleshooting_interest", 0)
    user_support = percentages.get("user_facing_support_interest", 0)
    process = percentages.get("process_documentation_strength", 0)
    ambiguity = percentages.get("ambiguity_readiness", 0)
    help_seeking = percentages.get("help_seeking_readiness", 0)
    shadowing = percentages.get("structured_shadowing_need", 0)

    people_process = max(user_support, process)
    safe_beginner_habits = min(ambiguity, help_seeking)

    if shadowing >= 50 or (ambiguity < 35 and help_seeking < 35):
        slug = "structured_shadowing"
    elif tech >= 60 and safe_beginner_habits >= 50 and tech >= people_process:
        slug = "it_launchpad"
    elif tech >= 30 and people_process >= 45:
        slug = "hybrid_it_user_support"
    elif people_process >= 50 and tech < 60:
        slug = "student_services_exploration"
    elif tech >= 50:
        slug = "it_launchpad" if safe_beginner_habits >= 50 else "hybrid_it_user_support"
    else:
        slug = "structured_shadowing"

    return _role_recommendation(config, slug)


def _role_recommendation(config: dict[str, Any], slug: str) -> dict[str, Any]:
    recommendations = {item["slug"]: item for item in config.get("recommendations", []) if item.get("slug")}
    fallback = {
        "slug": "structured_shadowing",
        "label": "Structured Shadowing",
        "summary": (
            "Student may benefit from observing IT, Admissions, and Advising workflows before final placement. "
            "Focus on confidence, communication, and task preference discovery."
        ),
        "next_steps": [
            "Schedule short observations across available support environments.",
            "Review confidence, communication, and task preferences after shadowing.",
        ],
    }
    return recommendations.get(slug, recommendations.get("structured_shadowing", fallback))
