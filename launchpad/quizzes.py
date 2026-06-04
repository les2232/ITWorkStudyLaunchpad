from __future__ import annotations

from typing import Any

from .content import load_json


def list_module_quizzes() -> dict[str, dict[str, Any]]:
    data = load_json("module_quizzes.json")
    return {slug: with_module_slug(slug, quiz) for slug, quiz in data.items()}


def get_module_quiz(module_slug: str) -> dict[str, Any] | None:
    return list_module_quizzes().get(module_slug)


def collect_quiz_responses(quiz: dict[str, Any], form: Any) -> dict[str, str]:
    return {question["id"]: str(form.get(question["id"], "")) for question in quiz.get("questions", [])}


def score_module_quiz(quiz: dict[str, Any], responses: dict[str, str]) -> dict[str, Any]:
    answers = []
    earned = 0

    for question in quiz.get("questions", []):
        selected_value = str(responses.get(question["id"], ""))
        correct_value = str(question.get("answer", ""))
        is_correct = selected_value == correct_value
        if is_correct:
            earned += 1

        answers.append(
            {
                "id": question["id"],
                "prompt": question["prompt"],
                "selected": selected_value,
                "selected_label": choice_label(question, selected_value),
                "correct_answer": correct_value,
                "correct_label": choice_label(question, correct_value),
                "is_correct": is_correct,
                "feedback": question.get("feedback", ""),
            }
        )

    possible = len(quiz.get("questions", []))
    score = round((earned / possible) * 100) if possible else 0
    return {
        "module_slug": quiz["module_slug"],
        "score": score,
        "earned": earned,
        "possible": possible,
        "answers": answers,
    }


def choice_label(question: dict[str, Any], value: str) -> str:
    for choice in question.get("choices", []):
        if str(choice.get("value", "")) == value:
            return str(choice.get("label", ""))
    return ""


def with_module_slug(slug: str, quiz: dict[str, Any]) -> dict[str, Any]:
    item = dict(quiz)
    item["module_slug"] = slug
    return item
