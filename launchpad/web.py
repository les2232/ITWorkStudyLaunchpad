from __future__ import annotations

import os
from typing import Any

from flask import Flask, abort, redirect, render_template, request, session, url_for

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
from .stuck import generate_stuck_summary


def create_app() -> Flask:
    app = Flask(__name__, template_folder="../templates", static_folder="../static")
    app.config["SECRET_KEY"] = os.environ.get("LAUNCHPAD_SECRET_KEY", "dev-only-launchpad-secret")

    @app.context_processor
    def inject_navigation() -> dict[str, Any]:
        return {"modules": list_modules(), "checklists": list_checklists(), "scenarios": list_scenarios()}

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
            session["pre_assessment_result"] = result
            return redirect(url_for("assessment_results"))
        return render_template("assessment.html", assessment=assessment, action=url_for("pre_assessment"))

    @app.get("/assessment-results")
    def assessment_results():
        result = session.get("pre_assessment_result")
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

    @app.get("/modules/<slug>")
    def module_reader(slug: str):
        module = get_module(slug)
        if module is None:
            abort(404)
        markdown = read_module_markdown(slug)
        return render_template("module.html", item=module, body=render_markdown(markdown), kind="module")

    @app.get("/checklists/<slug>")
    def checklist_reader(slug: str):
        checklist = get_checklist(slug)
        if checklist is None:
            abort(404)
        markdown = read_checklist_markdown(slug)
        return render_template(
            "checklist.html",
            item=checklist,
            body=render_markdown(markdown),
            items=extract_checklist_items(markdown),
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
            reports = session.get("stuck_reports", [])
            reports.append(
                {
                    "student": request.form.get("student", "").strip(),
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
            session["post_assessment_result"] = result
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
        )

    return app


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
