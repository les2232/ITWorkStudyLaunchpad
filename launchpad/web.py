from __future__ import annotations

import json
import os
import secrets
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from flask import Flask, abort, current_app, redirect, render_template, request, session, url_for

from .assessment import (
    all_questions,
    assessment_growth,
    collect_form_responses,
    get_post_readiness,
    get_training_path,
    knowledge_gaps,
    load_assessment,
    score_assessment,
)
from .content import (
    extract_checklist_items,
    get_checklist,
    get_module,
    list_checklists,
    list_modules,
    load_json,
    read_checklist_markdown,
    read_module_markdown,
    render_markdown,
)
from .demo import (
    DEMO_LEARNER_NAMES,
    DEMO_NOVA_NAME,
    DemoDataError,
    synthetic_beginner_responses,
    validate_demo_database,
)
from .accounts import assigned_learner_ids
from .real_auth import configure_real_security, install_real_auth, current_account, require_learner_account, require_staff_account
from .real_data import assert_non_real_database, validate_real_database
from .guidance import answer_question
from .pilot import configure_pilot, csrf_token
from .quizzes import collect_quiz_responses, get_module_quiz, score_module_quiz
from .scenarios import (
    apply_guided_action,
    build_feedback,
    get_scenario,
    guided_inspections,
    guided_scenario_can_finish,
    initial_guided_state,
    is_guided_scenario,
    list_scenarios,
    normalize_guided_state,
    scenario_controlled_activity_ids,
    scenarios_for_path,
)
from .storage import (
    DEFAULT_DB_PATH,
    activity_progress,
    checklist_progress,
    create_or_find_student,
    get_student,
    help_requests_for_student,
    init_db,
    latest_assessment_result,
    latest_module_quiz_result,
    mark_module_complete,
    module_is_complete,
    open_stuck_reports,
    save_assessment_result,
    save_checklist_progress,
    save_module_quiz_result,
    save_stuck_report,
    save_scenario_attempt,
    recent_stuck_reports,
    recent_scenario_attempts,
    student_progress,
    set_activity_complete,
    set_stuck_report_resolved,
    student_progress_summary,
)
from .stuck import generate_stuck_summary
from .checklist_answers import (
    DAY_ONE_QUESTIONS, MAX_ANSWER_LENGTH, ChecklistAnswerError,
    load_checklist_answers, save_checklist_submission,
    split_day_one_reflection, submitted_day_one_answers,
)


def create_app(config: dict[str, Any] | None = None) -> Flask:
    default_secret_key = "dev-only-launchpad-secret"
    app = Flask(__name__, template_folder="../templates", static_folder="../static")
    app.add_template_filter(_campus_time, "campus_time")
    app.config["SECRET_KEY"] = os.environ.get("LAUNCHPAD_SECRET_KEY", default_secret_key)
    app.config["LAUNCHPAD_DB_PATH"] = os.environ.get("LAUNCHPAD_DB_PATH", str(DEFAULT_DB_PATH))
    app.config["LAUNCHPAD_DEMO_MODE"] = os.environ.get(
        "LAUNCHPAD_DEMO_MODE", ""
    ).strip().lower() in {"1", "true", "yes"}
    if config:
        app.config.update(config)
    configure_pilot(app)
    configure_real_security(app)
    if app.config["LAUNCHPAD_REAL_MODE"]:
        validate_real_database(app.config["LAUNCHPAD_DB_PATH"])
        install_real_auth(app)
    elif app.config["LAUNCHPAD_DEMO_MODE"]:
        demo_dataset = validate_demo_database(app.config["LAUNCHPAD_DB_PATH"])
        secret_key = app.config.get("SECRET_KEY")
        if (
            not isinstance(secret_key, str)
            or not secret_key.strip()
            or secret_key == default_secret_key
        ):
            raise DemoDataError(
                "demo mode requires an explicit LAUNCHPAD_SECRET_KEY"
            )
        app.config["LAUNCHPAD_DEMO_SESSION_GENERATION"] = demo_dataset[
            "session_generation"
        ]
    # Additive schema initialization only after a guarded dataset is validated.
    if not app.config["LAUNCHPAD_REAL_MODE"]:
        assert_non_real_database(app.config["LAUNCHPAD_DB_PATH"])
        init_db(app.config["LAUNCHPAD_DB_PATH"])

    @app.before_request
    def isolate_demo_browser_session() -> None:
        # Free text belongs in SQLite, never in the signed, client-readable cookie.
        for key in ("pre_assessment_result", "post_assessment_result", "scenario_attempts", "stuck_reports"):
            session.pop(key, None)
        if not current_app.config["LAUNCHPAD_DEMO_MODE"]:
            return
        generation = current_app.config["LAUNCHPAD_DEMO_SESSION_GENERATION"]
        if session.get("demo_dataset_generation") != generation:
            session.clear()
            session["demo_dataset_generation"] = generation

    @app.context_processor
    def inject_navigation() -> dict[str, Any]:
        return {
            "modules": list_modules(),
            "checklists": list_checklists(),
            "scenarios": list_scenarios(),
            "current_student": _current_student(),
            "demo_mode": current_app.config["LAUNCHPAD_DEMO_MODE"],
            "pilot_mode": current_app.config["LAUNCHPAD_PILOT_MODE"],
            "real_mode": current_app.config["LAUNCHPAD_REAL_MODE"],
            "current_account": current_account(),
            "csrf_required": current_app.config["LAUNCHPAD_PILOT_MODE"] or current_app.config["LAUNCHPAD_REAL_MODE"],
            "csrf_token": csrf_token,
            "demo_learner_names": DEMO_LEARNER_NAMES,
        }

    @app.get("/")
    def home():
        if current_app.config["LAUNCHPAD_REAL_MODE"] and current_account()["role"] != "learner":
            return redirect(url_for("supervisor"))
        student = _current_student()
        progress = _student_progress(student["id"]) if student else None
        recommended_path = _saved_training_path(progress)
        continuation = _path_continuation(student["id"], recommended_path) if student and recommended_path else None
        return render_template(
            "home.html",
            module_count=len(list_modules()),
            checklist_count=len(list_checklists()),
            scenario_count=len(list_scenarios()),
            checklist_counts=_checklist_counts(),
            paths=load_json("training_paths.json")["levels"],
            recommended_path=recommended_path,
            continuation=continuation,
            path_progress=_path_presentation(student["id"], recommended_path) if student and recommended_path else None,
            help_overview=_help_request_overview(student),
        )

    @app.get("/learn")
    def learn():
        student = _current_student()
        progress = _student_progress(student["id"]) if student else None
        recommended_path = _saved_training_path(progress)
        return render_template(
            "learn.html",
            paths=load_json("training_paths.json")["levels"],
            recommended_path=recommended_path,
            continuation=_path_continuation(student["id"], recommended_path) if student and recommended_path else None,
            path_progress=_path_presentation(student["id"], recommended_path) if student and recommended_path else None,
        )

    @app.get("/help")
    def help():
        return render_template("help.html", help_overview=_help_request_overview(_current_student()))

    @app.route("/student", methods=["GET", "POST"])
    def student_identity():
        if request.method == "POST":
            student = _ensure_student(request.form.get("display_name", ""))
            next_url = _safe_next_url(request.args.get("next"))
            session["student_id"] = student["id"]
            session["student_display_name"] = student["display_name"]
            return redirect(next_url)
        student = _current_student()
        progress = _student_progress(student["id"]) if student else None
        recommended_path = _saved_training_path(progress)
        continuation = _path_continuation(student["id"], recommended_path) if student and recommended_path else None
        return render_template(
            "student.html",
            next_url=_safe_next_url(request.args.get("next")),
            progress=progress,
            recommended_path=recommended_path,
            continuation=continuation,
            path_progress=_path_presentation(student["id"], recommended_path) if student and recommended_path else None,
            help_overview=_help_request_overview(student),
        )

    @app.route("/pre-assessment", methods=["GET", "POST"])
    def pre_assessment():
        assessment = load_assessment("pre_assessment_v1")
        if request.method == "POST":
            preset = request.form.get("synthetic_preset")
            if preset:
                preset_student = _current_student()
                if (
                    preset != "beginner"
                    or not current_app.config["LAUNCHPAD_DEMO_MODE"]
                    or preset_student is None
                    or preset_student["display_name"] != DEMO_NOVA_NAME
                ):
                    abort(400)
                responses = synthetic_beginner_responses()
            else:
                responses = collect_form_responses(assessment, request.form)
            result = score_assessment(assessment, responses)
            path = get_training_path(result["score"])
            result["path_slug"] = path["slug"]
            result["path_label"] = path["label"]
            result["recommended_path"] = path["recommended_path"]
            result["knowledge_gaps"] = knowledge_gaps(result)
            student = _ensure_student()
            save_assessment_result(
                student["id"],
                assessment["id"],
                "pre",
                result,
                responses,
                _db_path(),
            )
            return redirect(url_for("assessment_results"))
        return render_template(
            "assessment.html",
            assessment=assessment,
            action=url_for("pre_assessment"),
            demo_preset_available=(
                current_app.config["LAUNCHPAD_DEMO_MODE"]
                and (student := _current_student()) is not None
                and student["display_name"] == DEMO_NOVA_NAME
            ),
        )

    @app.get("/assessment-results")
    def assessment_results():
        result = _latest_pre_assessment_result()
        if not result:
            return redirect(url_for("pre_assessment"))
        path = get_training_path(result["score"])
        return render_template("assessment_results.html", result=result, path=path, modules_by_slug=_modules_by_slug())

    @app.get("/training-path/<slug>")
    def training_path(slug: str):
        path = _training_path_by_slug(slug)
        if path is None:
            abort(404)
        student = _current_student()
        return render_template(
            "training_path.html",
            path=path,
            modules_by_slug=_modules_by_slug(),
            checklists_by_slug=_checklists_by_slug(),
            recommended_scenarios=scenarios_for_path(slug),
            checklist_counts=_checklist_counts(),
            activity_states=activity_progress(student["id"], _db_path()) if student else {},
            path_progress=_path_presentation(student["id"] if student else None, path),
        )

    @app.post("/training-path/<slug>/activities/<activity_id>")
    def update_path_activity(slug: str, activity_id: str):
        path = _training_path_by_slug(slug)
        if path is None:
            abort(404)
        configured_item = next(
            (
                item
                for item in path.get("required_items", [])
                if isinstance(item, dict)
                and item.get("type") == "activity"
                and item.get("id") == activity_id
            ),
            None,
        )
        if configured_item is None:
            abort(404)
        if configured_item.get("scenario_id") or activity_id in scenario_controlled_activity_ids():
            abort(400)
        completed_value = request.form.get("completed")
        if completed_value not in {"0", "1"}:
            abort(400)
        student = _ensure_student()
        if not set_activity_complete(student["id"], activity_id, completed_value == "1", _db_path()):
            abort(400)
        return redirect(url_for("training_path", slug=slug, _anchor=f"activity-{activity_id}"))

    @app.get("/modules")
    def module_index():
        return render_template("modules.html", modules=list_modules())

    @app.route("/modules/<slug>", methods=["GET", "POST"])
    def module_reader(slug: str):
        module = get_module(slug)
        if module is None:
            abort(404)
        if request.method == "POST":
            student = _ensure_student()
            mark_module_complete(student["id"], slug, request.form.get("completed") == "1", _db_path())
            return redirect(url_for("module_reader", slug=slug))
        markdown = read_module_markdown(slug)
        student = _current_student()
        completed = module_is_complete(student["id"], slug, _db_path()) if student else False
        quiz = get_module_quiz(slug)
        latest_quiz_result = latest_module_quiz_result(student["id"], slug, _db_path()) if student and quiz else None
        return render_template(
            "module.html",
            item=module,
            body=render_markdown(markdown),
            kind="module",
            completed=completed,
            quiz=quiz,
            latest_quiz_result=latest_quiz_result,
        )

    @app.route("/modules/<slug>/quiz", methods=["GET", "POST"])
    def module_quiz(slug: str):
        module = get_module(slug)
        if module is None:
            abort(404)
        quiz = get_module_quiz(slug)
        if quiz is None:
            abort(404)

        result = None
        if request.method == "POST":
            responses = collect_quiz_responses(quiz, request.form)
            result = score_module_quiz(quiz, responses)
            student = _ensure_student()
            save_module_quiz_result(student["id"], slug, result, _db_path())

        student = _current_student()
        latest_quiz_result = latest_module_quiz_result(student["id"], slug, _db_path()) if student else None
        return render_template(
            "module_quiz.html",
            item=module,
            quiz=quiz,
            result=result,
            latest_quiz_result=latest_quiz_result,
        )

    @app.route("/checklists/<slug>", methods=["GET", "POST"])
    def checklist_reader(slug: str):
        checklist = get_checklist(slug)
        if checklist is None:
            abort(404)
        markdown = read_checklist_markdown(slug)
        items = extract_checklist_items(markdown)
        student = _ensure_student() if request.method == "POST" else _current_student()
        if request.method == "POST" and student is None:
            abort(403)
        checked_items = checklist_progress(student["id"], slug, _db_path()) if student else {}
        answer_state = (
            load_checklist_answers(student["id"], slug, _db_path())
            if student and slug == "day_1" else {"answers": {}, "updated_at": None}
        )
        answer_error = None
        status = 200
        if request.method == "POST":
            completed_items = set(request.form.getlist("completed_items"))
            submitted = submitted_day_one_answers(request.form) if slug == "day_1" else {}
            try:
                save_checklist_submission(
                    student["id"], slug, [str(i) for i in range(len(items))],
                    completed_items, submitted, _db_path(),
                )
            except ChecklistAnswerError as exc:
                answer_error = str(exc)
                status = 400
                answer_state["answers"].update(submitted)
                checked_items = {str(i): str(i) in completed_items for i in range(len(items))}
            else:
                return redirect(url_for("checklist_reader", slug=slug))
        body = render_markdown(markdown, checked_items)
        before_answers, after_answers = split_day_one_reflection(body) if slug == "day_1" else (body, "")
        return render_template(
            "checklist.html",
            item=checklist,
            body=body,
            body_before_answers=before_answers,
            body_after_answers=after_answers,
            items=items,
            checked_count=sum(1 for checked in checked_items.values() if checked),
            reflection_questions=DAY_ONE_QUESTIONS,
            reflection_answers=answer_state["answers"],
            answers_saved_at=answer_state["updated_at"],
            max_answer_length=MAX_ANSWER_LENGTH,
            answer_error=answer_error,
        ), status

    @app.get("/day-1-checklist")
    def day_1_checklist():
        return redirect(url_for("checklist_reader", slug="day_1"))

    @app.get("/week-1-checklist")
    def week_1_checklist():
        return redirect(url_for("checklist_reader", slug="week_1"))

    @app.get("/scenarios")
    def scenario_index():
        return render_template("scenarios.html", scenarios=list_scenarios(), modules_by_slug=_modules_by_slug())

    @app.route("/scenarios/<scenario_id>", methods=["GET", "POST"])
    def scenario_detail(scenario_id: str):
        scenario = get_scenario(scenario_id)
        if scenario is None:
            abort(404)

        if is_guided_scenario(scenario):
            if request.method == "POST":
                abort(405)
            student = _current_student()
            state = initial_guided_state()
            completed = False
            if student:
                state = _guided_scenario_state(student["id"], scenario)
                completed = _guided_scenario_is_complete(student["id"], scenario)
            inspections = guided_inspections(scenario)
            return render_template(
                "scenario_lab.html",
                scenario=scenario,
                state=state,
                completed=completed,
                required_inspections=inspections,
                missing_inspections=[
                    item for item in inspections if item["id"] not in state["inspected"]
                ],
            )

        feedback = None
        student_response = ""
        if request.method == "POST":
            student_response = request.form.get("student_response", "")
            feedback = build_feedback(scenario, student_response)
            student = _ensure_student()
            save_scenario_attempt(
                student["id"], scenario["id"], scenario["title"],
                feedback["student_response"], _db_path(),
            )

        return render_template(
            "scenario_detail.html",
            scenario=scenario,
            feedback=feedback,
            student_response=student_response,
            modules_by_slug=_modules_by_slug(),
        )

    @app.post("/scenarios/<scenario_id>/actions")
    def scenario_action(scenario_id: str):
        scenario = get_scenario(scenario_id)
        if scenario is None or not is_guided_scenario(scenario):
            abort(404)
        student = _current_student()
        if student is None:
            return redirect(
                url_for(
                    "student_identity",
                    next=url_for("scenario_detail", scenario_id=scenario_id),
                )
            )
        if _guided_scenario_is_complete(student["id"], scenario):
            return redirect(url_for("scenario_detail", scenario_id=scenario_id))

        next_state = apply_guided_action(
            scenario,
            _guided_scenario_state(student["id"], scenario),
            request.form.get("action_id", ""),
        )
        if next_state is None:
            abort(400)
        _save_guided_scenario_state(student["id"], scenario, next_state)
        return redirect(
            url_for("scenario_detail", scenario_id=scenario_id, _anchor="scenario-feedback")
        )

    @app.post("/scenarios/<scenario_id>/complete")
    def complete_scenario(scenario_id: str):
        scenario = get_scenario(scenario_id)
        if scenario is None or not is_guided_scenario(scenario):
            abort(404)
        student = _current_student()
        if student is None:
            return redirect(
                url_for(
                    "student_identity",
                    next=url_for("scenario_detail", scenario_id=scenario_id),
                )
            )
        if _guided_scenario_is_complete(student["id"], scenario):
            return redirect(url_for("scenario_detail", scenario_id=scenario_id))

        state = _guided_scenario_state(student["id"], scenario)
        if not guided_scenario_can_finish(scenario, state):
            abort(400)
        if not set_activity_complete(
            student["id"], scenario["activity_id"], True, _db_path()
        ):
            abort(400)
        return redirect(url_for("scenario_detail", scenario_id=scenario_id))

    @app.route("/ask", methods=["GET", "POST"])
    def ask():
        answer = None
        question = ""
        if request.method == "POST":
            question = request.form.get("question", "")
            answer = answer_question(question)
        return render_template("ask.html", question=question, answer=answer)

    @app.route("/stuck", methods=["GET", "POST"])
    def stuck():
        summary = None
        if request.method == "POST":
            submitted = request.form
            if current_app.config["LAUNCHPAD_REAL_MODE"]:
                student = _ensure_student()
                submitted = {**request.form, "student": student["display_name"]}
            else:
                submitted_name = " ".join(str(request.form.get("student", "")).split())
                if current_app.config["LAUNCHPAD_DEMO_MODE"]:
                    student = _current_student()
                    if student is None or submitted_name != student["display_name"]:
                        abort(400)
                else:
                    student = _ensure_student(submitted_name)
            summary = generate_stuck_summary(submitted)
            save_stuck_report(student["id"], submitted, summary, _db_path())
        return render_template("stuck.html", summary=summary)

    @app.get("/help-requests")
    def help_requests():
        student = _current_student()
        return render_template(
            "help_requests.html",
            help_list=help_requests_for_student(student["id"], _db_path()) if student else None,
        )

    @app.post("/help-requests/<int:report_id>/status")
    def update_help_request_status(report_id: int):
        status = request.form.getlist("status")
        if status not in (["open"], ["resolved"]):
            abort(400)
        student = _ensure_student() if current_app.config["LAUNCHPAD_REAL_MODE"] else _current_student()
        # Another learner's request and a missing one look the same: not found.
        if student is None or not set_stuck_report_resolved(student["id"], report_id, status == ["resolved"], _db_path()):
            abort(404)
        return redirect(url_for("help_requests", _anchor=f"help-request-{report_id}"))

    @app.get("/mentor-summary")
    def mentor_summary():
        return render_template("mentor_summary.html")

    @app.route("/post-assessment", methods=["GET", "POST"])
    def post_assessment():
        assessment = load_assessment("post_assessment_v1")
        result = None
        readiness = None
        if request.method == "POST":
            responses = collect_form_responses(assessment, request.form)
            result = score_assessment(assessment, responses)
            readiness = get_post_readiness(assessment, result["score"])
            result["readiness_label"] = readiness["label"] if readiness else None
            student = _ensure_student()
            save_assessment_result(
                student["id"],
                assessment["id"],
                "post",
                result,
                responses,
                _db_path(),
            )
        return render_template(
            "assessment.html",
            assessment=assessment,
            action=url_for("post_assessment"),
            result=result,
            readiness=readiness,
        )

    @app.get("/supervisor")
    def supervisor():
        return render_supervisor()

    @app.get("/supervisor/learners/<int:learner_id>")
    def supervisor_learner(learner_id: int):
        if not current_app.config["LAUNCHPAD_REAL_MODE"]:
            abort(404)
        return render_supervisor(learner_id)

    def render_supervisor(learner_id: int | None = None):
        paths = load_json("training_paths.json")["levels"]
        if current_app.config["LAUNCHPAD_REAL_MODE"]:
            account = require_staff_account()
            assigned = assigned_learner_ids(account["id"], _db_path())
            if learner_id is not None and learner_id not in assigned:
                abort(404)
            student = get_student(learner_id, _db_path()) if learner_id is not None else None
            if learner_id is not None and student is None:
                abort(404)
            recent_progress = [item for item in (student_progress(value, _db_path()) for value in assigned) if item]
        else:
            student = _current_student()
            recent_progress = student_progress_summary(_db_path())
        # Only learners already visible here (assigned learners in real mode).
        open_help_requests = open_stuck_reports(
            [student["id"]] if student else [item["student"]["id"] for item in recent_progress], _db_path()
        )
        result_reader = _mentor_saved_assessment_result if current_app.config["LAUNCHPAD_REAL_MODE"] else _latest_saved_assessment_result
        pre_result = result_reader("pre", student)
        post_result = result_reader("post", student)
        for item in recent_progress:
            item["growth"] = assessment_growth(item["latest_pre_assessment"], item["latest_post_assessment"])
        growth = None
        if student:
            growth = assessment_growth(
                latest_assessment_result(student["id"], "pre", _db_path()),
                latest_assessment_result(student["id"], "post", _db_path()),
            )
        return render_template(
            "supervisor.html",
            module_count=len(list_modules()),
            checklist_count=len(list_checklists()),
            scenario_count=len(list_scenarios()),
            paths=paths,
            review_student=student,
            pre_result=pre_result,
            post_result=post_result,
            growth=growth,
            scenario_attempts=recent_scenario_attempts(student["id"], _db_path()) if student else [],
            stuck_reports=recent_stuck_reports(student["id"], _db_path()) if student else [],
            open_help_requests=open_help_requests,
            mentor_review_items=_mentor_review_items(pre_result, post_result),
            checklist_counts=_checklist_counts(),
            recent_progress=recent_progress,
        )

    return app


def _db_path() -> str:
    return str(current_app.config["LAUNCHPAD_DB_PATH"])


def _current_student() -> dict[str, Any] | None:
    if current_app.config["LAUNCHPAD_REAL_MODE"]:
        account = current_account()
        if not account or account["role"] != "learner":
            return None
        return get_student(account["learner_id"], _db_path()) if account["learner_id"] else None
    student_id = session.get("student_id")
    if not student_id:
        return None
    try:
        normalized_student_id = int(student_id)
    except (TypeError, ValueError):
        student = None
    else:
        student = get_student(normalized_student_id, _db_path())
    if student is None:
        _clear_learner_session_state()
        session.pop("student_id", None)
        session.pop("student_display_name", None)
    return student


def _ensure_student(display_name: str = "") -> dict[str, Any]:
    if current_app.config["LAUNCHPAD_REAL_MODE"]:
        account = require_learner_account()
        student = get_student(account["learner_id"], _db_path())
        if student is None:
            abort(403)
        return student
    previous_student_id = _session_student_id()
    name = " ".join(str(display_name or "").split())
    if not name:
        existing = _current_student()
        if existing:
            return existing
        if current_app.config["LAUNCHPAD_DEMO_MODE"]:
            abort(400)
        if "demo_student_token" not in session:
            session["demo_student_token"] = secrets.token_hex(3).upper()
        name = f"Demo Student {session['demo_student_token']}"

    if (
        current_app.config["LAUNCHPAD_DEMO_MODE"]
        and name not in DEMO_LEARNER_NAMES
    ):
        abort(400)

    student = create_or_find_student(name, _db_path())
    if previous_student_id != student["id"]:
        _clear_learner_session_state()
    session["student_id"] = student["id"]
    session["student_display_name"] = student["display_name"]
    return student


def _session_student_id() -> int | None:
    student_id = session.get("student_id")
    if isinstance(student_id, bool):
        return None
    try:
        return int(student_id)
    except (TypeError, ValueError):
        return None


def _clear_learner_session_state() -> None:
    for key in (
        "pre_assessment_result",
        "post_assessment_result",
        "scenario_attempts",
        "guided_scenario_states",
        "stuck_reports",
        "demo_student_token",
    ):
        session.pop(key, None)


def _guided_scenario_state_key(student_id: int, scenario_id: str) -> str:
    return f"{student_id}:{scenario_id}"


def _guided_scenario_state(
    student_id: int,
    scenario: dict[str, Any],
) -> dict[str, Any]:
    states = session.get("guided_scenario_states", {})
    if not isinstance(states, dict):
        states = {}
    state = states.get(_guided_scenario_state_key(student_id, scenario["id"]))
    return normalize_guided_state(scenario, state)


def _save_guided_scenario_state(
    student_id: int,
    scenario: dict[str, Any],
    state: dict[str, Any],
) -> None:
    states = session.get("guided_scenario_states", {})
    if not isinstance(states, dict):
        states = {}
    else:
        states = dict(states)
    states[_guided_scenario_state_key(student_id, scenario["id"])] = normalize_guided_state(
        scenario, state
    )
    session["guided_scenario_states"] = states


def _guided_scenario_is_complete(student_id: int, scenario: dict[str, Any]) -> bool:
    return activity_progress(student_id, _db_path()).get(scenario["activity_id"], False)


def _latest_pre_assessment_result() -> dict[str, Any] | None:
    return _latest_saved_assessment_result("pre")


def _mentor_saved_assessment_result(assessment_type: str, student: dict[str, Any] | None) -> dict[str, Any] | None:
    """Present persisted results without applying today's scoring to old answers."""
    if not student:
        return None
    saved = latest_assessment_result(student["id"], assessment_type, _db_path())
    if not saved:
        return None
    # Current content is context for saved answer values, never historical scoring.
    questions = {}
    if saved["assessment_id"] in {"pre_assessment_v1", "post_assessment_v1"}:
        try:
            questions = {item["id"]: item for item in all_questions(load_assessment(saved["assessment_id"]))}
        except (OSError, ValueError):
            pass
    answers = saved.get("answers")
    alignment = saved.get("role_alignment_summary") or {}
    recorded_role_questions = {item["id"]: item for item in alignment.get("question_results", [])}
    answer_items = []
    review_items = []
    for question_id, answer in (answers.items() if isinstance(answers, dict) else []):
        question = questions.get(question_id, {})
        recorded_question = recorded_role_questions.get(question_id, {})
        response = answer if isinstance(answer, str) else json.dumps(answer, ensure_ascii=False)
        options = {str(option["value"]): option.get("label", "") for option in question.get("options", [])}
        selected = answer if isinstance(answer, list) else [answer]
        answer_items.append({
            "id": question_id,
            "prompt": recorded_question.get("prompt") or question.get("prompt"),
            "prompt_recorded": bool(recorded_question.get("prompt")),
            "response": response,
            "recorded_option_label": recorded_question.get("selected_label") if recorded_question.get("selected_value") == answer else None,
            "current_option_labels": [options[str(value)] for value in selected if str(value) in options],
        })
        if question.get("type") == "free_response" or question.get("mentor_review_needed") is True:
            review_items.append({
                "id": question_id, "prompt": question.get("prompt"),
                "category": question.get("category", "Category unavailable"), "response": response,
            })
    return {
        "assessment_id": saved["assessment_id"],
        "assessment_type": assessment_type,
        "score": saved.get("technical_score"),
        "readiness_label": saved.get("readiness_level"),
        "recommended_path": saved.get("recommended_training_path"),
        "role_alignment_label": saved.get("role_alignment_recommendation"),
        "role_alignment": alignment,
        "saved_at": saved.get("created_at"),
        "answer_items": answer_items,
        "mentor_review_items": review_items,
    }


def _latest_saved_assessment_result(assessment_type: str, student: dict[str, Any] | None = None) -> dict[str, Any] | None:
    student = student or _current_student()
    if not student:
        return None
    saved = latest_assessment_result(student["id"], assessment_type, _db_path())
    if not saved:
        return None
    assessment = load_assessment(saved["assessment_id"])
    result = score_assessment(assessment, saved["answers"])
    if assessment_type == "pre":
        path = get_training_path(result["score"])
        result["path_slug"] = path["slug"]
        result["path_label"] = path["label"]
        result["recommended_path"] = path["recommended_path"]
        result["knowledge_gaps"] = knowledge_gaps(result)
    else:
        readiness = get_post_readiness(assessment, result["score"])
        result["readiness_label"] = readiness["label"] if readiness else None
    return result

def _safe_next_url(next_url: str | None) -> str:
    if next_url and next_url.startswith("/") and not next_url.startswith("//"):
        return next_url
    return url_for("home")


def _modules_by_slug() -> dict[str, dict[str, Any]]:
    return {module["slug"]: module for module in list_modules()}


def _checklists_by_slug() -> dict[str, dict[str, Any]]:
    return {checklist["slug"]: checklist for checklist in list_checklists()}


def _checklist_counts() -> dict[str, int]:
    return {
        checklist["slug"]: len(extract_checklist_items(read_checklist_markdown(checklist["slug"])))
        for checklist in list_checklists()
    }


def _student_progress(student_id: int) -> dict[str, Any] | None:
    return student_progress(student_id, _db_path())

def _saved_training_path(progress: dict[str, Any] | None) -> dict[str, Any] | None:
    if not progress or not isinstance(progress.get("latest_pre_assessment"), dict):
        return None
    score = progress["latest_pre_assessment"].get("technical_score")
    if isinstance(score, bool) or not isinstance(score, int) or not 0 <= score <= 100:
        return None
    return get_training_path(score)


def _training_path_by_slug(slug: str) -> dict[str, Any] | None:
    if not isinstance(slug, str):
        return None
    return next(
        (path for path in load_json("training_paths.json").get("levels", []) if path.get("slug") == slug),
        None,
    )


def _path_continuation(student_id: int, path: dict[str, Any]) -> dict[str, Any]:
    modules_by_slug = _modules_by_slug()
    checklists_by_slug = _checklists_by_slug()
    saved_activities = activity_progress(student_id, _db_path())

    for item in path.get("required_items", []):
        if not isinstance(item, dict):
            return _path_review_step(path)
        item_type = item.get("type")
        item_slug = item.get("slug")

        if item_type == "module":
            module = modules_by_slug.get(item_slug)
            if module is None:
                return _path_review_step(path)
            if not module_is_complete(student_id, item_slug, _db_path()):
                return {
                    "complete": False,
                    "title": module["title"],
                    "url": url_for("module_reader", slug=item_slug),
                }
            continue

        if item_type == "checklist":
            checklist = checklists_by_slug.get(item_slug)
            if checklist is None:
                return _path_review_step(path)
            items = extract_checklist_items(read_checklist_markdown(item_slug))
            checked = checklist_progress(student_id, item_slug, _db_path())
            if not items or not all(checked.get(str(index), False) for index in range(len(items))):
                return {
                    "complete": False,
                    "title": checklist["title"],
                    "url": url_for("checklist_reader", slug=item_slug),
                }
            continue

        if item_type == "activity":
            activity_id = item.get("id")
            label = item.get("label")
            if not isinstance(activity_id, str) or not isinstance(label, str) or not label:
                return _path_review_step(path)
            if not saved_activities.get(activity_id, False):
                scenario_id = item.get("scenario_id")
                item_url = (
                    url_for("scenario_detail", scenario_id=scenario_id)
                    if isinstance(scenario_id, str) and scenario_id
                    else url_for("training_path", slug=path["slug"], _anchor=f"activity-{activity_id}")
                )
                return {
                    "complete": False,
                    "title": label,
                    "url": item_url,
                }
            continue

        if item_type == "assessment" and str(item.get("label", "")).lower() == "post-assessment":
            if latest_assessment_result(student_id, "post", _db_path()) is None:
                return {
                    "complete": False,
                    "title": "Progress Check",
                    "url": url_for("post_assessment"),
                }
            continue

        return _path_review_step(path)

    return {"complete": True, "title": path.get("label", "Training path"), "url": None}



def _path_presentation(student_id: int | None, path: dict[str, Any]) -> dict[str, Any]:
    """Describe recorded steps without adding to or changing completion rules.

    Reuse continuation on each existing required item so the display agrees with
    the next-action logic. Knowledge checks remain visible separately and do not
    change the recorded-step count.
    """
    modules = _modules_by_slug()
    checklists = _checklists_by_slug()
    steps = []
    for position, raw_item in enumerate(path.get("required_items", []), start=1):
        item = raw_item if isinstance(raw_item, dict) else {}
        kind = item.get("type", "step")
        slug = item.get("slug")
        title = item.get("label") or "Review this step with a mentor"
        destination = None
        anchor = f"path-step-{position}"
        quiz_url = None
        quiz_recorded = False
        summary = None
        purpose = item.get("purpose")
        checklist_checked = checklist_total = 0
        if kind == "module" and slug in modules:
            title = modules[slug]["title"]
            summary, purpose = modules[slug].get("summary"), modules[slug].get("purpose")
            destination = url_for("module_reader", slug=slug)
            if get_module_quiz(slug):
                quiz_url = url_for("module_quiz", slug=slug)
                quiz_recorded = bool(student_id and latest_module_quiz_result(student_id, slug, _db_path()))
        elif kind == "checklist" and slug in checklists:
            title = checklists[slug]["title"]
            summary, purpose = checklists[slug].get("summary"), checklists[slug].get("purpose")
            destination = url_for("checklist_reader", slug=slug)
            checklist_total = len(extract_checklist_items(read_checklist_markdown(slug)))
            if student_id is not None:
                checked = checklist_progress(student_id, slug, _db_path())
                checklist_checked = sum(1 for index in range(checklist_total) if checked.get(str(index), False))
        elif kind == "activity" and item.get("id"):
            anchor = f"activity-{item['id']}"
            if item.get("scenario_id"):
                destination = url_for("scenario_detail", scenario_id=item["scenario_id"])
            elif str(title).lower() == "scenario practice":
                destination = url_for("scenario_index")
        elif kind == "assessment" and str(title).lower() == "post-assessment":
            title = "Progress Check"
            destination = url_for("post_assessment")
        completed = False
        if student_id is not None:
            single_step = {**path, "required_items": [raw_item]}
            completed = _path_continuation(student_id, single_step)["complete"]
        # Display-only status: "in progress" reflects saved partial work and
        # never changes the completion rules above.
        status, status_detail = ("completed", None) if completed else ("not_started", None)
        if not completed and kind == "checklist" and checklist_checked:
            status, status_detail = "in_progress", f"{checklist_checked} of {checklist_total} items checked"
        elif not completed and kind == "module" and quiz_recorded:
            status, status_detail = "in_progress", "Knowledge check saved. Mark the reading complete when you finish it."
        steps.append({
            "item": item,
            "position": position,
            "kind": "practice" if item.get("scenario_id") else kind,
            "title": title,
            "summary": summary,
            "purpose": purpose,
            "status": status,
            "status_label": STEP_STATUS_LABELS[status],
            "status_detail": status_detail,
            "url": destination,
            "anchor": anchor,
            "completed": completed,
            "quiz_url": quiz_url,
            "quiz_recorded": quiz_recorded,
        })
    remaining = [step for step in steps if not step["completed"]]
    completed_steps = [step for step in steps if step["completed"]]
    return {
        "steps": steps,
        "current": remaining[0] if remaining else None,
        "upcoming": remaining[1:],
        "completed": completed_steps,
        "completed_count": len(completed_steps),
        "total_count": len(steps),
        "follow_up": _path_follow_up(student_id, steps) if student_id is not None and not remaining else None,
    }


STEP_STATUS_LABELS = {"not_started": "Not started", "in_progress": "In progress", "completed": "Completed"}


def _path_follow_up(student_id: int, steps: list[dict[str, Any]]) -> dict[str, Any]:
    """Suggest concrete optional work after every required step is recorded."""
    pending_quizzes = [step for step in steps if step["quiz_url"] and not step["quiz_recorded"]]
    quiz_total = sum(1 for step in steps if step["quiz_url"])
    progress_check_saved = latest_assessment_result(student_id, "post", _db_path()) is not None
    tasks = [{
        "title": "Progress Check",
        "done": progress_check_saved,
        "detail": "Saved." if progress_check_saved else "A short, not pass/fail check to review with your mentor.",
        "url": url_for("post_assessment"),
        "action": "Take the Progress Check",
        "status": "completed" if progress_check_saved else "not_started",
    }]
    if quiz_total:
        tasks.append({
            "title": "Knowledge checks",
            "done": not pending_quizzes,
            "detail": f"{quiz_total - len(pending_quizzes)} of {quiz_total} saved.",
            "url": pending_quizzes[0]["quiz_url"] if pending_quizzes else None,
            "action": f"Knowledge check: {pending_quizzes[0]['title']}" if pending_quizzes else None,
            "status": "completed" if not pending_quizzes else "in_progress" if len(pending_quizzes) < quiz_total else "not_started",
        })
    for task in tasks:
        task["status_label"] = STEP_STATUS_LABELS[task["status"]]
    next_task = next((task for task in tasks if not task["done"]), None)
    return {
        "tasks": tasks,
        "url": next_task["url"] if next_task else url_for("scenario_index"),
        "action": next_task["action"] if next_task else "Practice a scenario",
    }


CAMPUS_TIMEZONE = ZoneInfo("America/Denver")


def _campus_time(value: Any) -> str:
    """Show a stored UTC timestamp in campus time; keep the raw value if it cannot be read."""
    try:
        moment = datetime.fromisoformat(str(value))
    except ValueError:
        return str(value or "")
    if moment.tzinfo is None:
        return str(value)
    local = moment.astimezone(CAMPUS_TIMEZONE)
    return f"{local:%b} {local.day}, {local.year}, {local.hour % 12 or 12}:{local:%M %p %Z}"


def _help_request_overview(student: dict[str, Any] | None) -> dict[str, Any] | None:
    if not student:
        return None
    overview = help_requests_for_student(student["id"], _db_path(), resolved_limit=0)
    if not overview["open"] and not overview["resolved_total"]:
        return None
    return overview


def _path_review_step(path: dict[str, Any]) -> dict[str, Any]:
    slug = path.get("slug")
    return {
        "complete": False,
        "title": "Review your training path with a mentor",
        "url": url_for("training_path", slug=slug) if isinstance(slug, str) else url_for("pre_assessment"),
    }


def _mentor_review_items(*results: dict[str, Any] | None) -> list[dict[str, Any]]:
    items = []
    for result in results:
        if not result:
            continue
        label = "Progress check" if result["assessment_id"].startswith("post") else "Starting point check"
        for item in result.get("mentor_review_items", []):
            review_item = dict(item)
            review_item["assessment_label"] = label
            items.append(review_item)
    return items
