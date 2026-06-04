from __future__ import annotations

import os
import secrets
from typing import Any

from flask import Flask, abort, current_app, redirect, render_template, request, session, url_for

from .assessment import (
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
from .guidance import answer_question
from .scenarios import build_feedback, get_scenario, list_scenarios, scenarios_for_path
from .storage import (
    DEFAULT_DB_PATH,
    checklist_progress,
    create_or_find_student,
    get_student,
    init_db,
    latest_assessment_result,
    mark_module_complete,
    module_is_complete,
    save_assessment_result,
    save_checklist_progress,
    save_stuck_report,
    student_progress_summary,
)
from .stuck import generate_stuck_summary


def create_app(config: dict[str, Any] | None = None) -> Flask:
    app = Flask(__name__, template_folder="../templates", static_folder="../static")
    app.config["SECRET_KEY"] = os.environ.get("LAUNCHPAD_SECRET_KEY", "dev-only-launchpad-secret")
    app.config["LAUNCHPAD_DB_PATH"] = os.environ.get("LAUNCHPAD_DB_PATH", str(DEFAULT_DB_PATH))
    if config:
        app.config.update(config)
    init_db(app.config["LAUNCHPAD_DB_PATH"])

    @app.context_processor
    def inject_navigation() -> dict[str, Any]:
        return {
            "modules": list_modules(),
            "checklists": list_checklists(),
            "scenarios": list_scenarios(),
            "current_student": _current_student(),
        }

    @app.get("/")
    def home():
        return render_template(
            "home.html",
            module_count=len(list_modules()),
            checklist_count=len(list_checklists()),
            scenario_count=len(list_scenarios()),
            checklist_counts=_checklist_counts(),
            paths=load_json("training_paths.json")["levels"],
        )

    @app.route("/student", methods=["GET", "POST"])
    def student_identity():
        if request.method == "POST":
            student = _ensure_student(request.form.get("display_name", ""))
            next_url = _safe_next_url(request.args.get("next"))
            session["student_id"] = student["id"]
            session["student_display_name"] = student["display_name"]
            return redirect(next_url)
        return render_template("student.html", next_url=_safe_next_url(request.args.get("next")))

    @app.route("/pre-assessment", methods=["GET", "POST"])
    def pre_assessment():
        assessment = load_assessment("pre_assessment_v1")
        if request.method == "POST":
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
            session["pre_assessment_result"] = _session_assessment_result(result)
            return redirect(url_for("assessment_results"))
        return render_template("assessment.html", assessment=assessment, action=url_for("pre_assessment"))

    @app.get("/assessment-results")
    def assessment_results():
        result = session.get("pre_assessment_result")
        if not result:
            result = _latest_pre_assessment_result()
        if not result:
            return redirect(url_for("pre_assessment"))
        path = get_training_path(result["score"])
        return render_template("assessment_results.html", result=result, path=path, modules_by_slug=_modules_by_slug())

    @app.get("/training-path/<slug>")
    def training_path(slug: str):
        paths = load_json("training_paths.json")["levels"]
        path = next((item for item in paths if item["slug"] == slug), None)
        if path is None:
            abort(404)
        return render_template(
            "training_path.html",
            path=path,
            modules_by_slug=_modules_by_slug(),
            checklists_by_slug=_checklists_by_slug(),
            recommended_scenarios=scenarios_for_path(slug),
            checklist_counts=_checklist_counts(),
        )

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
        return render_template("module.html", item=module, body=render_markdown(markdown), kind="module", completed=completed)

    @app.route("/checklists/<slug>", methods=["GET", "POST"])
    def checklist_reader(slug: str):
        checklist = get_checklist(slug)
        if checklist is None:
            abort(404)
        markdown = read_checklist_markdown(slug)
        items = extract_checklist_items(markdown)
        if request.method == "POST":
            student = _ensure_student()
            completed_items = set(request.form.getlist("completed_items"))
            for index, _item in enumerate(items):
                save_checklist_progress(student["id"], slug, str(index), str(index) in completed_items, _db_path())
            return redirect(url_for("checklist_reader", slug=slug))
        student = _current_student()
        checked_items = checklist_progress(student["id"], slug, _db_path()) if student else {}
        return render_template(
            "checklist.html",
            item=checklist,
            body=render_markdown(markdown, checked_items),
            items=items,
            checked_count=sum(1 for checked in checked_items.values() if checked),
        )

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

        feedback = None
        student_response = ""
        if request.method == "POST":
            student_response = request.form.get("student_response", "")
            feedback = build_feedback(scenario, student_response)
            attempts = session.get("scenario_attempts", [])
            attempts.append(
                {
                    "scenario_id": scenario["id"],
                    "scenario_title": scenario["title"],
                    "student_response": feedback["student_response"],
                    "needs_mentor_review": True,
                }
            )
            session["scenario_attempts"] = attempts[-20:]

        return render_template(
            "scenario_detail.html",
            scenario=scenario,
            feedback=feedback,
            student_response=student_response,
            modules_by_slug=_modules_by_slug(),
        )

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
            summary = generate_stuck_summary(request.form)
            student = _ensure_student(request.form.get("student", ""))
            save_stuck_report(student["id"], request.form, summary, _db_path())
            reports = session.get("stuck_reports", [])
            reports.append(
                {
                    "student": student["display_name"],
                    "topic": request.form.get("topic", "").strip(),
                    "summary": summary,
                }
            )
            session["stuck_reports"] = reports[-10:]
        return render_template("stuck.html", summary=summary)

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
            session["post_assessment_result"] = _session_assessment_result(result)
        return render_template(
            "assessment.html",
            assessment=assessment,
            action=url_for("post_assessment"),
            result=result,
            readiness=readiness,
        )

    @app.get("/supervisor")
    def supervisor():
        paths = load_json("training_paths.json")["levels"]
        pre_result = session.get("pre_assessment_result")
        post_result = session.get("post_assessment_result")
        recent_progress = student_progress_summary(_db_path())
        return render_template(
            "supervisor.html",
            module_count=len(list_modules()),
            checklist_count=len(list_checklists()),
            scenario_count=len(list_scenarios()),
            paths=paths,
            pre_result=pre_result,
            post_result=post_result,
            scenario_attempts=session.get("scenario_attempts", []),
            stuck_reports=session.get("stuck_reports", []),
            mentor_review_items=_mentor_review_items(pre_result, post_result),
            checklist_counts=_checklist_counts(),
            recent_progress=recent_progress,
        )

    return app


def _db_path() -> str:
    return str(current_app.config["LAUNCHPAD_DB_PATH"])


def _current_student() -> dict[str, Any] | None:
    student_id = session.get("student_id")
    if not student_id:
        return None
    student = get_student(int(student_id), _db_path())
    if student is None:
        session.pop("student_id", None)
        session.pop("student_display_name", None)
    return student


def _ensure_student(display_name: str = "") -> dict[str, Any]:
    name = " ".join(str(display_name or "").split())
    if not name:
        existing = _current_student()
        if existing:
            return existing
        if "demo_student_token" not in session:
            session["demo_student_token"] = secrets.token_hex(3).upper()
        name = f"Demo Student {session['demo_student_token']}"

    student = create_or_find_student(name, _db_path())
    session["student_id"] = student["id"]
    session["student_display_name"] = student["display_name"]
    return student


def _latest_pre_assessment_result() -> dict[str, Any] | None:
    student = _current_student()
    if not student:
        return None
    saved = latest_assessment_result(student["id"], "pre", _db_path())
    if not saved:
        return None

    assessment = load_assessment(saved["assessment_id"])
    result = score_assessment(assessment, saved["answers"])
    path = get_training_path(result["score"])
    result["path_slug"] = path["slug"]
    result["path_label"] = path["label"]
    result["recommended_path"] = path["recommended_path"]
    result["knowledge_gaps"] = knowledge_gaps(result)
    session["pre_assessment_result"] = _session_assessment_result(result)
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


def _mentor_review_items(*results: dict[str, Any] | None) -> list[dict[str, Any]]:
    items = []
    for result in results:
        if not result:
            continue
        label = "Post-assessment" if result["assessment_id"].startswith("post") else "Pre-assessment"
        for item in result.get("mentor_review_items", []):
            review_item = dict(item)
            review_item["assessment_label"] = label
            items.append(review_item)
    return items


def _session_assessment_result(result: dict[str, Any]) -> dict[str, Any]:
    """Keep Flask's signed session cookie small enough for browsers."""

    compact = {
        key: result[key]
        for key in (
            "assessment_id",
            "score",
            "earned",
            "possible",
            "mentor_review_points_possible",
            "categories",
            "mentor_review_items",
            "path_slug",
            "path_label",
            "recommended_path",
            "knowledge_gaps",
            "readiness_label",
        )
        if key in result
    }

    if result.get("role_alignment"):
        role_alignment = result["role_alignment"]
        compact["role_alignment"] = {
            key: role_alignment[key]
            for key in (
                "title",
                "signals",
                "recommended_alignment",
                "mentor_note",
            )
            if key in role_alignment
        }

    if compact.get("mentor_review_items"):
        compact["mentor_review_items"] = [
            {
                key: item[key]
                for key in (
                    "id",
                    "prompt",
                    "category",
                    "possible",
                    "response",
                    "mentor_review_needed",
                    "mentor_use",
                )
                if key in item
            }
            for item in compact["mentor_review_items"]
        ]

    return compact
