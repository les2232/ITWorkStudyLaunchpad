import json
import re
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]

MODULES_DIR = PROJECT_ROOT / "content" / "modules"
ASSESSMENTS_DIR = PROJECT_ROOT / "content" / "assessments"
CHECKLISTS_DIR = PROJECT_ROOT / "content" / "checklists"
DATA_DIR = PROJECT_ROOT / "content" / "data"

REQUIRED_MODULE_HEADINGS = [
    "## Goal",
    "## Plain-Language Explanation",
    "## Why This Matters",
    "## Key Terms",
    "## Common Beginner Mistakes",
    "## When to Ask for Help",
    "## Quick Check",
    "## Strong Answers",
    "## Related Modules",
]

COMMON_IT_WORDS_REQUIRED_TERMS = [
    "### Domain",
    "### SCCM / Configuration Manager",
    "### Imaging",
    "### Ticket",
    "### Asset Tag",
    "### Escalation",
    "### Mentor / Buddy",
    "### Documentation",
]

REQUIRED_ASSESSMENT_HEADINGS = [
    "## Purpose",
    "## Scoring",
    "# Questions",
]

REQUIRED_CHECKLIST_MARKERS = [
    "## Purpose",
    "- [ ]",
]

REQUIRED_DATA_FILES = [
    "modules.json",
    "module_quizzes.json",
    "checklists.json",
    "training_paths.json",
    "scenarios.json",
    "pre_assessment_v1.json",
    "post_assessment_v1.json",
]

ROLE_ALIGNMENT_SCOPE = "role_alignment"
ROLE_ALIGNMENT_SECTION_LABEL = "role alignment"
ROLE_ALIGNMENT_SIGNALS = {
    "technical_troubleshooting_interest",
    "user_facing_support_interest",
    "process_documentation_strength",
    "ambiguity_readiness",
    "help_seeking_readiness",
    "structured_shadowing_need",
}
ROLE_ALIGNMENT_RECOMMENDATIONS = {
    "it_launchpad",
    "hybrid_it_user_support",
    "student_services_exploration",
    "structured_shadowing",
}
ROLE_ALIGNMENT_DIRECTIONS = {"interest", "strength", "readiness", "need"}
FORBIDDEN_ROLE_ALIGNMENT_WORDING = [
    ("not a good", "fit for it"),
    ("failed", "it placement"),
    ("better suited for admissions", "not technical"),
]

SCENARIO_TEXT_FIELDS = [
    "id",
    "title",
    "summary",
    "situation",
    "student_prompt",
    "mentor_feedback",
]
SCENARIO_LIST_FIELDS = [
    "readiness_levels",
    "module_slugs",
    "safe_actions",
    "document",
    "ask_mentor_when",
    "avoid",
]
GUIDED_SCENARIO_FIELDS = [
    "scenario_type",
    "activity_id",
    "required_inspections",
    "inspections",
    "actions",
    "resolution",
]
GUIDED_ACTION_KINDS = {"resolution", "premature", "unsafe"}
STABLE_ID_PATTERN = re.compile(r"[a-z][a-z0-9_]*")


def check_balanced_code_fences(text: str, path: Path) -> list[str]:
    fence_count = text.count("```")
    if fence_count % 2 != 0:
        return [f"{path}: unbalanced markdown code fences"]
    return []


def check_no_todos(text: str, path: Path) -> list[str]:
    if "TODO" in text:
        return [f"{path}: contains TODO"]
    return []


def check_required_headings(text: str, path: Path) -> list[str]:
    errors = []
    for heading in REQUIRED_MODULE_HEADINGS:
        if heading not in text:
            errors.append(f"{path}: missing required heading: {heading}")
    return errors


def check_common_it_words_terms(text: str, path: Path) -> list[str]:
    errors = []
    for term in COMMON_IT_WORDS_REQUIRED_TERMS:
        if term not in text:
            errors.append(f"{path}: missing required glossary term: {term}")
    return errors


def validate_modules() -> list[str]:
    errors = []

    if not MODULES_DIR.exists():
        return [f"Missing modules directory: {MODULES_DIR}"]

    module_files = sorted(MODULES_DIR.glob("*.md"))

    if not module_files:
        return [f"No module files found in {MODULES_DIR}"]

    for path in module_files:
        text = path.read_text(encoding="utf-8")

        errors.extend(check_balanced_code_fences(text, path))
        errors.extend(check_no_todos(text, path))
        errors.extend(check_required_headings(text, path))

        if path.name == "common_it_words.md":
            errors.extend(check_common_it_words_terms(text, path))

    return errors


def validate_assessments() -> list[str]:
    errors = []

    if not ASSESSMENTS_DIR.exists():
        return [f"Missing assessments directory: {ASSESSMENTS_DIR}"]

    assessment_files = sorted(ASSESSMENTS_DIR.glob("*.md"))

    if not assessment_files:
        return [f"No assessment files found in {ASSESSMENTS_DIR}"]

    for path in assessment_files:
        text = path.read_text(encoding="utf-8")
        for heading in REQUIRED_ASSESSMENT_HEADINGS:
            if heading not in text:
                errors.append(f"{path}: missing required assessment heading: {heading}")

    return errors


def validate_checklists() -> list[str]:
    errors = []

    if not CHECKLISTS_DIR.exists():
        return [f"Missing checklists directory: {CHECKLISTS_DIR}"]

    checklist_files = sorted(CHECKLISTS_DIR.glob("*.md"))

    if not checklist_files:
        return [f"No checklist files found in {CHECKLISTS_DIR}"]

    for path in checklist_files:
        text = path.read_text(encoding="utf-8")
        for marker in REQUIRED_CHECKLIST_MARKERS:
            if marker not in text:
                errors.append(f"{path}: missing required checklist marker: {marker}")

    return errors


def validate_data_files() -> list[str]:
    errors = []

    if not DATA_DIR.exists():
        return [f"Missing data directory: {DATA_DIR}"]

    for file_name in REQUIRED_DATA_FILES:
        path = DATA_DIR / file_name
        if not path.exists():
            errors.append(f"{path}: missing required data file")
            continue
        try:
            json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            errors.append(f"{path}: invalid JSON: {exc}")

    if errors:
        return errors

    training_paths = read_json("training_paths.json")
    scenarios = read_json("scenarios.json")
    errors.extend(validate_module_manifest())
    errors.extend(validate_module_quizzes())
    errors.extend(validate_checklist_manifest())
    errors.extend(validate_training_paths(training_paths, scenarios))
    errors.extend(validate_scenarios(scenarios, training_paths))
    errors.extend(validate_assessment_data("pre_assessment_v1.json"))
    errors.extend(validate_assessment_data("post_assessment_v1.json"))

    return errors


def validate_module_manifest() -> list[str]:
    errors = []
    modules = read_json("modules.json")
    seen_slugs = set()

    if not isinstance(modules, list) or not modules:
        return [f"{DATA_DIR / 'modules.json'}: expected a non-empty list"]

    for module in modules:
        errors.extend(require_fields(module, ["slug", "title", "path", "summary", "purpose"], "modules.json"))
        slug = module.get("slug")
        if slug in seen_slugs:
            errors.append(f"{DATA_DIR / 'modules.json'}: duplicate module slug: {slug}")
        seen_slugs.add(slug)
        path = PROJECT_ROOT / module.get("path", "")
        if not path.exists():
            errors.append(f"{DATA_DIR / 'modules.json'}: module path does not exist: {path}")

    return errors


def validate_module_quizzes() -> list[str]:
    errors = []
    path = DATA_DIR / "module_quizzes.json"
    quizzes = read_json("module_quizzes.json")
    module_slugs = {module["slug"] for module in read_json("modules.json")}

    if not isinstance(quizzes, dict) or not quizzes:
        return [f"{path}: expected a non-empty object keyed by module slug"]

    quiz_slugs = set(quizzes)
    missing_quizzes = module_slugs - quiz_slugs
    if missing_quizzes:
        errors.append(f"{path}: missing quizzes for modules: {sorted(missing_quizzes)}")

    for module_slug, quiz in quizzes.items():
        if module_slug not in module_slugs:
            errors.append(f"{path}: quiz for unknown module slug: {module_slug}")
        if not isinstance(quiz, dict):
            errors.append(f"{path}: quiz for {module_slug} must be an object")
            continue

        errors.extend(require_fields(quiz, ["title", "summary", "questions"], "module_quizzes.json"))
        questions = quiz.get("questions", [])
        if not isinstance(questions, list):
            errors.append(f"{path}: {module_slug} questions must be a list")
            continue
        if not 3 <= len(questions) <= 5:
            errors.append(f"{path}: {module_slug} must have 3 to 5 questions")

        question_ids = set()
        for question in questions:
            if not isinstance(question, dict):
                errors.append(f"{path}: {module_slug} question must be an object")
                continue
            errors.extend(
                require_fields(
                    question,
                    ["id", "type", "prompt", "choices", "answer", "feedback"],
                    "module_quizzes.json",
                )
            )
            question_id = question.get("id")
            if question_id in question_ids:
                errors.append(f"{path}: {module_slug} duplicate question id: {question_id}")
            question_ids.add(question_id)

            question_type = question.get("type")
            if question_type not in {"multiple_choice", "true_false"}:
                errors.append(f"{path}: {module_slug} {question_id} unsupported type: {question_type}")

            choices = question.get("choices", [])
            if not isinstance(choices, list) or len(choices) < 2:
                errors.append(f"{path}: {module_slug} {question_id} must have at least two choices")
                continue

            choice_values = set()
            for choice in choices:
                if not isinstance(choice, dict):
                    errors.append(f"{path}: {module_slug} {question_id} choice must be an object")
                    continue
                errors.extend(require_fields(choice, ["value", "label"], "module_quizzes.json"))
                value = choice.get("value")
                if value in choice_values:
                    errors.append(f"{path}: {module_slug} {question_id} duplicate choice value: {value}")
                choice_values.add(value)

            if question.get("answer") not in choice_values:
                errors.append(f"{path}: {module_slug} {question_id} answer is not one of the choices")
            if question_type == "true_false" and choice_values != {"true", "false"}:
                errors.append(f"{path}: {module_slug} {question_id} true_false choices must be true and false")

    return errors


def validate_checklist_manifest() -> list[str]:
    errors = []
    checklists = read_json("checklists.json")
    seen_slugs = set()

    if not isinstance(checklists, list) or not checklists:
        return [f"{DATA_DIR / 'checklists.json'}: expected a non-empty list"]

    for checklist in checklists:
        errors.extend(require_fields(checklist, ["slug", "title", "path", "summary", "purpose"], "checklists.json"))
        slug = checklist.get("slug")
        if slug in seen_slugs:
            errors.append(f"{DATA_DIR / 'checklists.json'}: duplicate checklist slug: {slug}")
        seen_slugs.add(slug)
        path = PROJECT_ROOT / checklist.get("path", "")
        if not path.exists():
            errors.append(f"{DATA_DIR / 'checklists.json'}: checklist path does not exist: {path}")

    return errors


def validate_training_paths(
    data: dict | None = None, scenarios: list[dict] | None = None
) -> list[str]:
    errors = []
    if data is None:
        data = read_json("training_paths.json")
    if scenarios is None:
        scenarios = read_json("scenarios.json")
    scenario_by_id = {scenario.get("id"): scenario for scenario in scenarios if isinstance(scenario, dict)}
    module_slugs = {module["slug"] for module in read_json("modules.json")}
    checklist_slugs = {checklist["slug"] for checklist in read_json("checklists.json")}
    seen_slugs = set()
    seen_activity_ids = set()

    levels = data.get("levels", [])
    if not levels:
        errors.append(f"{DATA_DIR / 'training_paths.json'}: missing levels")

    for level in levels:
        errors.extend(require_fields(level, ["slug", "label", "min_score", "max_score", "recommended_path", "required_items"], "training_paths.json"))
        slug = level.get("slug")
        if slug in seen_slugs:
            errors.append(f"{DATA_DIR / 'training_paths.json'}: duplicate level slug: {slug}")
        seen_slugs.add(slug)

        for item in level.get("required_items", []):
            item_type = item.get("type")
            item_slug = item.get("slug")
            if item_type == "module" and item_slug not in module_slugs:
                errors.append(f"{DATA_DIR / 'training_paths.json'}: unknown module slug: {item_slug}")
            if item_type == "checklist" and item_slug not in checklist_slugs:
                errors.append(f"{DATA_DIR / 'training_paths.json'}: unknown checklist slug: {item_slug}")
            if item_type == "activity":
                errors.extend(require_fields(item, ["id", "label", "purpose"], "training_paths.json"))
                activity_id = item.get("id")
                if isinstance(activity_id, str) and not re.fullmatch(r"[a-z][a-z0-9_]*", activity_id):
                    errors.append(f"{DATA_DIR / 'training_paths.json'}: invalid activity id: {activity_id}")
                if activity_id in seen_activity_ids:
                    errors.append(f"{DATA_DIR / 'training_paths.json'}: duplicate activity id: {activity_id}")
                if isinstance(activity_id, str) and activity_id:
                    seen_activity_ids.add(activity_id)
                if "review_topics" in item:
                    topics = item["review_topics"]
                    if not isinstance(topics, list) or not topics or any(
                        not isinstance(topic, str) or not topic.strip() for topic in topics
                    ):
                        errors.append(
                            f"{DATA_DIR / 'training_paths.json'}: invalid review_topics for activity {activity_id}"
                        )
                if "completion_guidance" in item:
                    guidance = item["completion_guidance"]
                    if not isinstance(guidance, str) or not guidance.strip():
                        errors.append(
                            f"{DATA_DIR / 'training_paths.json'}: invalid completion_guidance for activity {activity_id}"
                        )
                if "scenario_id" in item:
                    scenario_id = item.get("scenario_id")
                    if not isinstance(scenario_id, str) or not re.fullmatch(
                        r"[a-z][a-z0-9_]*", scenario_id
                    ):
                        errors.append(
                            f"{DATA_DIR / 'training_paths.json'}: invalid scenario id: {scenario_id}"
                        )
                    elif scenario_id not in scenario_by_id:
                        errors.append(
                            f"{DATA_DIR / 'training_paths.json'}: unknown scenario id: {scenario_id}"
                        )
                    elif scenario_by_id[scenario_id].get("activity_id") != activity_id:
                        errors.append(
                            f"{DATA_DIR / 'training_paths.json'}: scenario {scenario_id} does not control activity {activity_id}"
                        )
            elif "scenario_id" in item:
                errors.append(
                    f"{DATA_DIR / 'training_paths.json'}: scenario_id is only valid on activity items"
                )
            if item_type == "assessment":
                errors.extend(require_fields(item, ["label", "purpose"], "training_paths.json"))
            if item_type not in {"module", "checklist", "activity", "assessment"}:
                errors.append(f"{DATA_DIR / 'training_paths.json'}: unknown required item type: {item_type}")

    return errors


def validate_scenarios(
    data: list[dict] | None = None, training_paths: dict | None = None
) -> list[str]:
    errors = []
    path = DATA_DIR / "scenarios.json"
    if data is None:
        data = read_json("scenarios.json")
    if training_paths is None:
        training_paths = read_json("training_paths.json")

    if not isinstance(data, list) or not data:
        return [f"{path}: expected a non-empty list"]

    module_slugs = {module["slug"] for module in read_json("modules.json")}
    levels = training_paths.get("levels", []) if isinstance(training_paths, dict) else []
    level_slugs = {
        level.get("slug")
        for level in levels
        if isinstance(level, dict) and isinstance(level.get("slug"), str)
    }
    seen_scenario_ids = set()
    seen_inspection_ids = set()
    seen_action_ids = set()

    for scenario in data:
        if not isinstance(scenario, dict):
            errors.append(f"{path}: scenario must be an object")
            continue

        errors.extend(
            require_fields(
                scenario,
                SCENARIO_TEXT_FIELDS + SCENARIO_LIST_FIELDS,
                "scenarios.json",
            )
        )
        scenario_id = scenario.get("id")
        scenario_label = scenario_id if isinstance(scenario_id, str) else "<missing id>"

        if not is_stable_id(scenario_id):
            errors.append(f"{path}: invalid scenario id: {scenario_id}")
        elif scenario_id in seen_scenario_ids:
            errors.append(f"{path}: duplicate scenario id: {scenario_id}")
        else:
            seen_scenario_ids.add(scenario_id)

        for field in SCENARIO_TEXT_FIELDS:
            value = scenario.get(field)
            if not isinstance(value, str) or not value.strip():
                errors.append(
                    f"{path}: scenario {scenario_label} field {field} must be non-empty text"
                )

        list_values = {
            field: validate_nonempty_string_list(scenario, field, scenario_label)
            for field in SCENARIO_LIST_FIELDS
        }
        for field, field_errors in list_values.items():
            errors.extend(field_errors[0])

        readiness_levels = list_values["readiness_levels"][1]
        unknown_levels = set(readiness_levels) - level_slugs
        if unknown_levels:
            errors.append(
                f"{path}: scenario {scenario_label} has unknown readiness levels: {sorted(unknown_levels)}"
            )

        scenario_modules = list_values["module_slugs"][1]
        unknown_modules = set(scenario_modules) - module_slugs
        if unknown_modules:
            errors.append(
                f"{path}: scenario {scenario_label} has unknown module slugs: {sorted(unknown_modules)}"
            )

        scenario_type = scenario.get("scenario_type", "text_response")
        if scenario_type not in {"text_response", "guided_troubleshooting"}:
            errors.append(
                f"{path}: scenario {scenario_label} has unsupported scenario_type: {scenario_type}"
            )
            continue
        if scenario_type != "guided_troubleshooting":
            continue

        errors.extend(
            validate_guided_scenario(
                scenario,
                levels,
                readiness_levels,
                seen_inspection_ids,
                seen_action_ids,
            )
        )

    return errors


def validate_nonempty_string_list(
    item: dict, field: str, item_label: str
) -> tuple[list[str], list[str]]:
    errors = []
    path = DATA_DIR / "scenarios.json"
    value = item.get(field)
    if not isinstance(value, list) or not value:
        errors.append(f"{path}: scenario {item_label} field {field} must be a non-empty list")
        return errors, []

    valid_values = []
    seen_values = set()
    for entry in value:
        if not isinstance(entry, str) or not entry.strip():
            errors.append(
                f"{path}: scenario {item_label} field {field} must contain non-empty text"
            )
            continue
        if entry in seen_values:
            errors.append(
                f"{path}: scenario {item_label} field {field} contains duplicate value: {entry}"
            )
            continue
        seen_values.add(entry)
        valid_values.append(entry)

    return errors, valid_values


def validate_guided_scenario(
    scenario: dict,
    levels: list[dict],
    readiness_levels: list[str],
    seen_inspection_ids: set,
    seen_action_ids: set,
) -> list[str]:
    errors = []
    path = DATA_DIR / "scenarios.json"
    scenario_id = scenario.get("id", "<missing id>")
    errors.extend(require_fields(scenario, GUIDED_SCENARIO_FIELDS, "scenarios.json"))

    activity_id = scenario.get("activity_id")
    if not is_stable_id(activity_id):
        errors.append(f"{path}: scenario {scenario_id} has invalid activity_id: {activity_id}")

    required_errors, required_inspections = validate_nonempty_string_list(
        scenario, "required_inspections", str(scenario_id)
    )
    errors.extend(required_errors)
    for inspection_id in required_inspections:
        if not is_stable_id(inspection_id):
            errors.append(
                f"{path}: scenario {scenario_id} has invalid required inspection id: {inspection_id}"
            )

    inspection_ids = set()
    inspections = scenario.get("inspections")
    if not isinstance(inspections, list) or not inspections:
        errors.append(f"{path}: scenario {scenario_id} inspections must be a non-empty list")
    else:
        for inspection in inspections:
            if not isinstance(inspection, dict):
                errors.append(f"{path}: scenario {scenario_id} inspection must be an object")
                continue
            errors.extend(
                require_fields(inspection, ["id", "label", "feedback"], "scenarios.json")
            )
            inspection_id = inspection.get("id")
            if not is_stable_id(inspection_id):
                errors.append(
                    f"{path}: scenario {scenario_id} has invalid inspection id: {inspection_id}"
                )
            elif inspection_id in seen_inspection_ids:
                errors.append(f"{path}: duplicate inspection id: {inspection_id}")
            else:
                seen_inspection_ids.add(inspection_id)
                inspection_ids.add(inspection_id)
            errors.extend(
                validate_text_fields(
                    inspection, ["label", "feedback"], f"scenario {scenario_id} inspection {inspection_id}"
                )
            )

    missing_inspections = set(required_inspections) - inspection_ids
    if missing_inspections:
        errors.append(
            f"{path}: scenario {scenario_id} required inspections are not defined: {sorted(missing_inspections)}"
        )
    unused_inspections = inspection_ids - set(required_inspections)
    if unused_inspections:
        errors.append(
            f"{path}: scenario {scenario_id} inspections are not required: {sorted(unused_inspections)}"
        )

    action_ids = set()
    action_kinds = {}
    actions = scenario.get("actions")
    if not isinstance(actions, list) or not actions:
        errors.append(f"{path}: scenario {scenario_id} actions must be a non-empty list")
    else:
        for action in actions:
            if not isinstance(action, dict):
                errors.append(f"{path}: scenario {scenario_id} action must be an object")
                continue
            errors.extend(
                require_fields(action, ["id", "label", "kind", "feedback"], "scenarios.json")
            )
            action_id = action.get("id")
            if not is_stable_id(action_id):
                errors.append(f"{path}: scenario {scenario_id} has invalid action id: {action_id}")
            elif action_id in seen_action_ids:
                errors.append(f"{path}: duplicate action id: {action_id}")
            else:
                seen_action_ids.add(action_id)
                action_ids.add(action_id)
                action_kinds[action_id] = action.get("kind")
            errors.extend(
                validate_text_fields(
                    action, ["label", "feedback"], f"scenario {scenario_id} action {action_id}"
                )
            )
            if action.get("kind") not in GUIDED_ACTION_KINDS:
                errors.append(
                    f"{path}: scenario {scenario_id} action {action_id} has invalid kind: {action.get('kind')}"
                )

    present_kinds = set(action_kinds.values())
    for required_kind in GUIDED_ACTION_KINDS:
        if required_kind not in present_kinds:
            errors.append(
                f"{path}: scenario {scenario_id} must define a {required_kind} action"
            )
    if sum(kind == "resolution" for kind in action_kinds.values()) != 1:
        errors.append(f"{path}: scenario {scenario_id} must define exactly one resolution action")

    resolution = scenario.get("resolution")
    if not isinstance(resolution, dict):
        errors.append(f"{path}: scenario {scenario_id} resolution must be an object")
    else:
        errors.extend(
            require_fields(resolution, ["action_id", "confirmation"], "scenarios.json")
        )
        errors.extend(
            validate_text_fields(
                resolution,
                ["confirmation"],
                f"scenario {scenario_id} resolution",
            )
        )
        resolution_action_id = resolution.get("action_id")
        if not is_stable_id(resolution_action_id):
            errors.append(
                f"{path}: scenario {scenario_id} has invalid resolution action_id: {resolution_action_id}"
            )
        elif resolution_action_id not in action_ids:
            errors.append(
                f"{path}: scenario {scenario_id} resolution references unknown action: {resolution_action_id}"
            )
        elif action_kinds.get(resolution_action_id) != "resolution":
            errors.append(
                f"{path}: scenario {scenario_id} resolution action must have kind resolution: {resolution_action_id}"
            )

    errors.extend(
        validate_guided_scenario_linkage(
            scenario_id, activity_id, readiness_levels, levels
        )
    )
    return errors


def validate_guided_scenario_linkage(
    scenario_id: str, activity_id: str, readiness_levels: list[str], levels: list[dict]
) -> list[str]:
    errors = []
    path = DATA_DIR / "scenarios.json"
    matching_items = []
    for level in levels:
        if not isinstance(level, dict):
            continue
        for item in level.get("required_items", []):
            if (
                isinstance(item, dict)
                and item.get("type") == "activity"
                and item.get("id") == activity_id
            ):
                matching_items.append((level.get("slug"), item))

    if len(matching_items) != 1:
        errors.append(
            f"{path}: scenario {scenario_id} activity {activity_id} must appear exactly once in training paths"
        )
        return errors

    level_slug, item = matching_items[0]
    if item.get("scenario_id") != scenario_id:
        errors.append(
            f"{path}: scenario {scenario_id} activity {activity_id} must reference its scenario_id"
        )
    if level_slug not in readiness_levels:
        errors.append(
            f"{path}: scenario {scenario_id} linked path {level_slug} is not listed in readiness_levels"
        )
    return errors


def validate_text_fields(item: dict, fields: list[str], item_label: str) -> list[str]:
    errors = []
    path = DATA_DIR / "scenarios.json"
    for field in fields:
        value = item.get(field)
        if not isinstance(value, str) or not value.strip():
            errors.append(f"{path}: {item_label} field {field} must be non-empty text")
    return errors


def is_stable_id(value) -> bool:
    return isinstance(value, str) and STABLE_ID_PATTERN.fullmatch(value) is not None


def validate_assessment_data(file_name: str) -> list[str]:
    errors = []
    data = read_json(file_name)
    errors.extend(require_fields(data, ["id", "title", "purpose", "total_points", "sections"], file_name))

    question_ids = set()
    point_total = 0.0
    for section in data.get("sections", []):
        errors.extend(require_fields(section, ["title", "questions"], file_name))
        for question in section.get("questions", []):
            errors.extend(require_fields(question, ["id", "prompt", "type", "category", "points"], file_name))
            is_role_question = is_role_alignment_question(section, question)
            question_id = question.get("id")
            if question_id in question_ids:
                errors.append(f"{DATA_DIR / file_name}: duplicate question id: {question_id}")
            question_ids.add(question_id)
            point_total += float(question.get("points", 0))
            question_type = question.get("type")
            if question_type in {"multiple_choice", "select_all"} and not question.get("options"):
                errors.append(f"{DATA_DIR / file_name}: {question_id} missing options")
            if (
                question_type == "multiple_choice"
                and not is_role_question
                and "correct_answer" not in question
                and "score_map" not in question
            ):
                errors.append(f"{DATA_DIR / file_name}: {question_id} missing correct_answer or score_map")
            if question_type == "rating" and "score_map" not in question:
                errors.append(f"{DATA_DIR / file_name}: {question_id} missing score_map")

    expected_total = float(data.get("total_points", 0))
    if round(point_total, 2) != round(expected_total, 2):
        errors.append(f"{DATA_DIR / file_name}: question points total {point_total} but expected {expected_total}")

    if file_name == "pre_assessment_v1.json":
        errors.extend(validate_role_alignment_data(data, file_name))

    return errors


def is_role_alignment_question(section: dict, question: dict) -> bool:
    return question.get("score_scope", section.get("score_scope")) == ROLE_ALIGNMENT_SCOPE


def validate_role_alignment_data(data: dict, file_name: str) -> list[str]:
    errors = []
    path = DATA_DIR / file_name
    config = data.get("role_alignment")

    if not isinstance(config, dict):
        return [f"{path}: missing role_alignment metadata"]

    errors.extend(require_fields(config, ["title", "purpose", "signals", "recommendations"], file_name))
    errors.extend(validate_role_alignment_signals(config, file_name))
    errors.extend(validate_role_alignment_recommendations(config, file_name))

    role_text = json.dumps(config).lower()
    for phrase_parts in FORBIDDEN_ROLE_ALIGNMENT_WORDING:
        if all(part in role_text for part in phrase_parts):
            errors.append(f"{path}: role alignment wording contains discouraged phrasing: {' / '.join(phrase_parts)}")

    sections = [section for section in data.get("sections", []) if section.get("score_scope") == ROLE_ALIGNMENT_SCOPE]
    if len(sections) != 1:
        errors.append(f"{path}: expected exactly one {ROLE_ALIGNMENT_SECTION_LABEL} section")
        return errors

    section = sections[0]
    role_category = section.get("title", ROLE_ALIGNMENT_SECTION_LABEL)
    questions = section.get("questions", [])
    if len(questions) < 7:
        errors.append(f"{path}: expected at least 7 role alignment questions")

    covered_signals = set()
    for question in questions:
        question_id = question.get("id", "<missing id>")
        errors.extend(
            require_fields(
                question,
                ["id", "prompt", "type", "category", "points", "alignment_traits", "options"],
                file_name,
            )
        )

        if question.get("type") != "multiple_choice":
            errors.append(f"{path}: {question_id} role alignment question must be multiple_choice")
        if float(question.get("points", 0)) != 0:
            errors.append(f"{path}: {question_id} role alignment question must use 0 points")
        if question.get("category") != role_category:
            errors.append(f"{path}: {question_id} role alignment category must be {role_category}")

        traits = set(question.get("alignment_traits", []))
        unknown_traits = traits - ROLE_ALIGNMENT_SIGNALS
        if unknown_traits:
            errors.append(f"{path}: {question_id} unknown alignment traits: {sorted(unknown_traits)}")

        option_values = set()
        for option in question.get("options", []):
            errors.extend(require_fields(option, ["value", "label", "signals", "alignment_tags"], file_name))
            value = option.get("value")
            if value in option_values:
                errors.append(f"{path}: {question_id} duplicate option value: {value}")
            option_values.add(value)
            if value not in {"A", "B", "C", "D"}:
                errors.append(f"{path}: {question_id} unexpected role alignment option value: {value}")

            if not isinstance(option.get("alignment_tags"), list) or not option.get("alignment_tags"):
                errors.append(f"{path}: {question_id} option {value} missing alignment_tags")

            signals = option.get("signals", {})
            if not isinstance(signals, dict) or not signals:
                errors.append(f"{path}: {question_id} option {value} missing signals")
                continue

            for signal, amount in signals.items():
                if signal not in ROLE_ALIGNMENT_SIGNALS:
                    errors.append(f"{path}: {question_id} option {value} unknown signal: {signal}")
                if signal not in traits:
                    errors.append(f"{path}: {question_id} option {value} signal not declared in alignment_traits: {signal}")
                if not isinstance(amount, (int, float)) or isinstance(amount, bool) or amount < 0:
                    errors.append(f"{path}: {question_id} option {value} signal must be a non-negative number: {signal}")
                if amount > 0:
                    covered_signals.add(signal)

    missing_signals = ROLE_ALIGNMENT_SIGNALS - covered_signals
    if missing_signals:
        errors.append(f"{path}: role alignment signals not covered by any option: {sorted(missing_signals)}")

    return errors


def validate_role_alignment_signals(config: dict, file_name: str) -> list[str]:
    errors = []
    path = DATA_DIR / file_name
    seen_slugs = set()

    for signal in config.get("signals", []):
        errors.extend(require_fields(signal, ["slug", "label", "direction", "description"], file_name))
        slug = signal.get("slug")
        if slug in seen_slugs:
            errors.append(f"{path}: duplicate role alignment signal: {slug}")
        seen_slugs.add(slug)
        if slug not in ROLE_ALIGNMENT_SIGNALS:
            errors.append(f"{path}: unknown role alignment signal: {slug}")
        if signal.get("direction") not in ROLE_ALIGNMENT_DIRECTIONS:
            errors.append(f"{path}: invalid role alignment direction for {slug}: {signal.get('direction')}")

    missing_signals = ROLE_ALIGNMENT_SIGNALS - seen_slugs
    if missing_signals:
        errors.append(f"{path}: missing role alignment signal metadata: {sorted(missing_signals)}")

    return errors


def validate_role_alignment_recommendations(config: dict, file_name: str) -> list[str]:
    errors = []
    path = DATA_DIR / file_name
    seen_slugs = set()

    for recommendation in config.get("recommendations", []):
        errors.extend(require_fields(recommendation, ["slug", "label", "summary", "next_steps"], file_name))
        slug = recommendation.get("slug")
        if slug in seen_slugs:
            errors.append(f"{path}: duplicate role alignment recommendation: {slug}")
        seen_slugs.add(slug)
        if slug not in ROLE_ALIGNMENT_RECOMMENDATIONS:
            errors.append(f"{path}: unknown role alignment recommendation: {slug}")

    missing_recommendations = ROLE_ALIGNMENT_RECOMMENDATIONS - seen_slugs
    if missing_recommendations:
        errors.append(f"{path}: missing role alignment recommendations: {sorted(missing_recommendations)}")

    return errors


def validate_markdown_files() -> list[str]:
    errors = []

    for path in sorted(PROJECT_ROOT.rglob("*.md")):
        text = path.read_text(encoding="utf-8")
        errors.extend(check_balanced_code_fences(text, path))
        errors.extend(check_no_todos(text, path))

    return errors


def read_json(file_name: str):
    return json.loads((DATA_DIR / file_name).read_text(encoding="utf-8"))


def require_fields(item: dict, fields: list[str], file_name: str) -> list[str]:
    errors = []
    for field in fields:
        if field not in item or item[field] is None:
            errors.append(f"{DATA_DIR / file_name}: missing required field: {field}")
            continue
        if isinstance(item[field], str) and item[field].strip() == "":
            errors.append(f"{DATA_DIR / file_name}: missing required field: {field}")
        if isinstance(item[field], list) and not item[field]:
            errors.append(f"{DATA_DIR / file_name}: missing required field: {field}")
    return errors


def main() -> int:
    errors = []
    errors.extend(validate_markdown_files())
    errors.extend(validate_modules())
    errors.extend(validate_assessments())
    errors.extend(validate_checklists())
    errors.extend(validate_data_files())

    if errors:
        print("Content validation failed:\n")
        for error in errors:
            print(f"- {error}")
        return 1

    print("Content validation passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
