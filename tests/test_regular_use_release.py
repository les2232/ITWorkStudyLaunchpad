"""Regular-use release: sign-in-verified AD sessions, real-mode wording and a learner journey.

Invented identities and disposable databases only. The directory boundary is
mocked exactly as in the existing AD tests; an accidental LDAP connection fails.
"""
from contextlib import closing
import re
import time
import unittest
from unittest.mock import patch

from launchpad import create_app
from launchpad.accounts import assign_mentor, get_session_account, set_account_active
from launchpad.content import load_json
from launchpad.demo import synthetic_beginner_responses
from launchpad.scenarios import get_scenario
from launchpad.storage import activity_progress, connect, help_requests_for_student, module_is_complete
from scripts.start_real import prepare_runtime
from tests import test_ad_login as fixture
from tests.test_ux_navigation import Page

# Wording that belongs only to demo, prototype, pilot or controlled-test modes.
NON_RELEASE_WORDING = re.compile(
    r"\b(demo|demonstration|prototype|synthetic|invented|controlled test|test sessions?|pilot|mvp|persona)\b",
    re.IGNORECASE,
)


def post_assessment_answers():
    """A valid answer for every Progress Check question, taken from the content file."""
    from launchpad.assessment import all_questions, load_assessment
    answers = {}
    for question in all_questions(load_assessment("post_assessment_v1")):
        if question["type"] == "rating":
            answers[question["id"]] = "3"
        elif question["type"] in {"multiple_choice", "select_all"}:
            answers[question["id"]] = str(question["options"][0]["value"])
        else:
            answers[question["id"]] = "I would pause and ask my mentor."
    return answers


class SignInPolicyBase(unittest.TestCase):
    base_url = fixture.ADLoginTests.base_url
    cookie_name = fixture.ADLoginTests.cookie_name
    issuer = fixture.ADLoginTests.issuer
    namespace = fixture.ADLoginTests.namespace
    first_guid = fixture.ADLoginTests.first_guid
    second_guid = fixture.ADLoginTests.second_guid
    mentor_guid = fixture.ADLoginTests.mentor_guid
    reads = fixture.ADLoginTests.reads
    writes = fixture.ADLoginTests.writes
    identity = staticmethod(fixture.ADLoginTests.identity)
    get = fixture.ADLoginTests.get
    post = fixture.ADLoginTests.post
    token = fixture.ADLoginTests.token
    handle = fixture.ADLoginTests.handle
    submit = fixture.ADLoginTests.submit
    login = fixture.ADLoginTests.login
    learner_tables = fixture.ADLoginTests.learner_tables
    snapshot = fixture.ADLoginTests.snapshot

    def setUp(self):
        fixture.ADLoginTests.setUp(self)
        patch("ldap3.Connection", side_effect=AssertionError("No live directory calls in tests")).start()
        self.config.update(
            LAUNCHPAD_AD_SESSION_POLICY="signin",
            LAUNCHPAD_AD_LOOKUP_USERNAME="", LAUNCHPAD_AD_LOOKUP_PASSWORD="",
            LAUNCHPAD_AD_REVALIDATE_SECONDS="",
        )
        self.app = create_app(self.config)
        self.client = self.app.test_client()
        self.start = int(time.time())
        self.wall_clock = patch("launchpad.accounts.time.time", return_value=self.start).start()


class SignInPolicyTests(SignInPolicyBase):
    def test_policy_starts_without_lookup_account_and_validates_its_limits(self):
        self.assertEqual(self.app.config["PERMANENT_SESSION_LIFETIME"].total_seconds(), 4 * 3600)
        for values in (
            {"LAUNCHPAD_AD_LOOKUP_USERNAME": "reader@example.test"},
            {"LAUNCHPAD_AD_LOOKUP_PASSWORD": "synthetic-reader-password"},
            {"LAUNCHPAD_SESSION_MAX_HOURS": "0"},
            {"LAUNCHPAD_SESSION_MAX_HOURS": "9"},
            {"LAUNCHPAD_SESSION_MAX_HOURS": "four"},
            {"LAUNCHPAD_AD_SESSION_POLICY": "always"},
        ):
            with self.subTest(values=values), self.assertRaises(ValueError):
                create_app({**self.config, **values})
        with self.assertRaises(ValueError):
            create_app({**self.config, "LAUNCHPAD_AUTH_BACKEND": "oidc"})
        two_hours = create_app({**self.config, "LAUNCHPAD_SESSION_MAX_HOURS": "2"})
        self.assertEqual(two_hours.config["LAUNCHPAD_SESSION_SECONDS"], 7200)

    def test_production_launcher_accepts_signin_but_never_the_test_policy(self):
        environ = {
            "LAUNCHPAD_REAL_MODE": "1", "LAUNCHPAD_DEMO_MODE": "0", "LAUNCHPAD_PILOT_MODE": "0",
            "LAUNCHPAD_SECRET_KEY": self.config["SECRET_KEY"],
            "LAUNCHPAD_TRUSTED_HOSTS": "launchpad.example", "LAUNCHPAD_AUTH_BACKEND": "ad",
            "LAUNCHPAD_DATA_DIR": str(self.database.parent.resolve()),
            "LAUNCHPAD_DB_PATH": str(self.database.resolve()),
            **{key: str(value) for key, value in self.config.items() if key.startswith("LAUNCHPAD_AD_")},
        }
        self.assertEqual(prepare_runtime(environ), self.database.resolve())
        with self.assertRaises(ValueError):
            prepare_runtime({**environ, "LAUNCHPAD_AD_SESSION_POLICY": "controlled_test"})
        with self.assertRaises(ValueError):
            prepare_runtime({**environ, "LAUNCHPAD_SESSION_MAX_HOURS": "12"})

    def test_sessions_end_after_idle_and_absolute_limits_with_accurate_notice(self):
        self.login()
        token = self.handle()
        with closing(connect(self.database)) as db:
            row = db.execute("SELECT created_at, expires_at, idle_timeout_seconds FROM auth_sessions").fetchone()
        self.assertEqual(tuple(row), (self.start, self.start + 4 * 3600, 1800))

        # Activity keeps the session alive up to the absolute limit.
        for elapsed in range(1500, 4 * 3600, 1500):
            self.wall_clock.return_value = self.start + elapsed
            self.assertEqual(self.get("/student").status_code, 200, elapsed)
        self.wall_clock.return_value = self.start + 4 * 3600
        before = self.snapshot(self.first["learner_id"])
        refused = self.submit("/modules/hardware_basics", {"completed": "1"})
        self.assertEqual(refused.status_code, 401)
        for text in ("30 minutes without activity or 4 hours after sign-in", "Progress you already submitted is saved",
                     "was not saved and will not be submitted automatically"):
            self.assertIn(text, refused.text)
        self.assertEqual(self.snapshot(self.first["learner_id"]), before)
        self.assertIsNone(get_session_account(token, self.database))
        page = self.get("/student")
        self.assertEqual(page.status_code, 401)
        self.assertIn('name="username"', page.text)

        self.login()
        self.wall_clock.return_value = self.start + 4 * 3600 + 1801
        idle = self.get("/")
        self.assertEqual(idle.status_code, 401)
        self.assertIn("30 minutes without activity", idle.text)
        self.revalidate.assert_not_called()

    def test_first_visit_shows_no_session_ended_notice(self):
        page = self.get("/")
        self.assertEqual(page.status_code, 401)
        self.assertNotIn("Your sign-in ended", page.text)
        self.assertIn("30 minutes without activity", page.text)

    def test_local_disable_and_sign_out_take_effect_immediately(self):
        self.login()
        self.assertEqual(self.get("/").status_code, 200)
        set_account_active(self.first["id"], False, self.database)
        self.assertEqual(self.get("/").status_code, 401)
        set_account_active(self.first["id"], True, self.database)
        self.login()
        self.assertEqual(self.submit("/auth/logout").status_code, 302)
        self.assertEqual(self.get("/").status_code, 401)
        self.authenticate.side_effect = fixture.ADLoginError()
        self.assertEqual(self.submit("/auth/login", {"username": "invented.user", "password": "x"}).status_code, 401)
        self.revalidate.assert_not_called()


class RealModeWordingTests(SignInPolicyBase):
    def visible_text(self, response):
        return Page(response).find("body")[0].label

    def get_routes(self):
        samples = {
            "slug": {"training_path": "beginner", "module_reader": "hardware_basics",
                     "module_quiz": "hardware_basics", "checklist_reader": "day_1"},
            "scenario_id": "ticket_term_unknown",
        }
        routes = []
        for rule in self.app.url_map.iter_rules():
            if "GET" not in rule.methods or rule.endpoint in {"static", "auth_callback"}:
                continue
            values = {}
            for argument in rule.arguments:
                sample = samples.get(argument)
                values[argument] = sample.get(rule.endpoint) if isinstance(sample, dict) else sample
            if None in values.values() or "learner_id" in rule.arguments:
                continue
            with self.app.test_request_context(base_url=self.base_url):
                from flask import url_for
                routes.append(url_for(rule.endpoint, **values))
        return sorted(set(routes))

    def complete_checklist(self, learner_id, slug):
        from launchpad.content import extract_checklist_items, read_checklist_markdown
        from launchpad.storage import save_checklist_progress
        for index, _ in enumerate(extract_checklist_items(read_checklist_markdown(slug))):
            save_checklist_progress(learner_id, slug, str(index), True, self.database)

    def assert_release_wording(self, path, response):
        self.assertIn(response.status_code, {200, 401}, path)
        found = NON_RELEASE_WORDING.findall(self.visible_text(response))
        self.assertEqual(found, [], f"{path} shows non-release wording")

    def test_sign_in_learner_and_mentor_pages_have_no_demo_prototype_or_test_wording(self):
        self.assert_release_wording("/auth/login", self.get("/auth/login"))
        # The shared AD fixture's labels contain the word "synthetic"; use real-looking labels.
        with closing(connect(self.database)) as db, db:
            db.execute("UPDATE students SET display_name = 'Jordan Rivera' WHERE id = ?", (self.first["learner_id"],))
        self.login()
        routes = self.get_routes()
        self.assertIn("/help-requests", routes)
        routes += ["/scenarios/classroom_no_display", "/training-path/beginner"]

        def sweep(state):
            for path in routes:
                response = self.get(path)
                if response.status_code in {302, 403}:
                    continue
                with self.subTest(state=state, learner_page=path):
                    self.assert_release_wording(path, response)

        sweep("new learner")
        self.submit("/pre-assessment", synthetic_beginner_responses())
        self.submit("/stuck", {"topic": "Printer", "trying_to_do": "a", "what_happened": "b",
                               "already_checked": "c", "current_blocker": "d"})
        self.submit("/scenarios/ticket_term_unknown", {"student_response": "Ask my mentor what the term means."})
        sweep("partway with an open help request")
        learner_id = self.first["learner_id"]
        beginner = next(path for path in load_json("training_paths.json")["levels"] if path["slug"] == "beginner")
        scenario = get_scenario("classroom_no_display")
        for action in scenario["required_inspections"]:
            self.submit("/scenarios/classroom_no_display/actions", {"action_id": action})
        self.submit("/scenarios/classroom_no_display/actions", {"action_id": scenario["resolution"]["action_id"]})
        self.submit("/scenarios/classroom_no_display/complete")
        for item in beginner["required_items"]:
            if item["type"] == "module":
                self.submit(f"/modules/{item['slug']}", {"completed": "1"})
            elif item["type"] == "checklist":
                self.complete_checklist(learner_id, item["slug"])
            elif item["type"] == "activity" and not item.get("scenario_id"):
                self.submit(f"/training-path/beginner/activities/{item['id']}", {"completed": "1"})
        self.submit("/post-assessment", post_assessment_answers())
        report = help_requests_for_student(learner_id, self.database)["open"][0]
        self.submit(f"/help-requests/{report['id']}/status", {"status": "resolved"})
        sweep("completed path with a resolved help request")

        mentor = self.app.test_client()
        assign_mentor(self.mentor["id"], self.first["learner_id"], self.database)
        self.login(self.mentor, mentor)
        for path in ("/supervisor", f"/supervisor/learners/{self.first['learner_id']}", "/learn", "/modules"):
            with self.subTest(mentor_page=path):
                self.assert_release_wording(path, self.get(path, mentor))


class WrittenAnswerNoticeTests(SignInPolicyBase):
    def test_every_saved_written_answer_page_warns_about_sensitive_information(self):
        self.login()
        for path in ("/pre-assessment", "/post-assessment", "/scenarios/ticket_term_unknown", "/stuck", "/ask"):
            with self.subTest(path=path):
                text = Page(self.get(path)).find("main")[0].label
                self.assertIn("Do not include passwords", text)
        self.assertIn("This question is not saved.", self.get("/ask").text)
        self.assertIn("your assigned mentor can read them", self.get("/pre-assessment").text)


class NewLearnerJourneyTests(SignInPolicyBase):
    def test_new_learner_signs_in_works_asks_for_help_and_finds_progress_later(self):
        learner_id = self.first["learner_id"]
        self.login()
        home = Page(self.get("/"))
        self.assertIn("Start assessment", home.find("main")[0].label)

        self.assertEqual(self.submit("/pre-assessment", synthetic_beginner_responses()).status_code, 302)
        beginner = next(path for path in load_json("training_paths.json")["levels"] if path["slug"] == "beginner")
        first_module = next(item["slug"] for item in beginner["required_items"] if item["type"] == "module")
        self.assertEqual(self.submit(f"/modules/{first_module}", {"completed": "1"}).status_code, 302)
        activity = next(item["id"] for item in beginner["required_items"]
                        if item["type"] == "activity" and not item.get("scenario_id"))
        self.assertEqual(self.submit(f"/training-path/beginner/activities/{activity}", {"completed": "1"}).status_code, 302)
        saved = self.submit("/stuck", {"topic": "Imaging question", "trying_to_do": "Start imaging",
                                       "what_happened": "It paused", "already_checked": "Cable",
                                       "current_blocker": "Which step is next?"})
        self.assertEqual(saved.status_code, 200)
        self.assertIn("It was not sent to anyone", saved.text)
        self.assertEqual(self.submit("/auth/logout").status_code, 302)
        self.assertEqual(self.get("/").status_code, 401)

        # The next day, in a new browser.
        self.wall_clock.return_value = self.start + 86400
        later = self.app.test_client()
        self.login(client=later)
        home = Page(self.get("/", later))
        text = home.find("main")[0].label
        self.assertIn("Welcome back", text)
        self.assertIn("Next:", text)
        self.assertIn("1 open request", text)
        self.assertIn("Imaging question", text)
        progress = home.find(id="home-path-progress")[0]
        self.assertGreaterEqual(int(progress.attrs["value"]), 2)
        self.assertTrue(module_is_complete(learner_id, first_module, self.database))
        self.assertTrue(activity_progress(learner_id, self.database)[activity])

        report = help_requests_for_student(learner_id, self.database)["open"][0]
        listing = self.get("/help-requests", later)
        self.assertIn("Imaging question", listing.text)
        self.assertEqual(self.submit(f"/help-requests/{report['id']}/status", {"status": "resolved"}, later).status_code, 302)
        self.assertEqual(help_requests_for_student(learner_id, self.database)["resolved_total"], 1)
        self.assertIn("No open help requests", self.get("/", later).text)

        # Another learner signing in sees none of it.
        other = self.app.test_client()
        self.login(self.second, other)
        other_home = self.get("/", other).text
        self.assertNotIn("Imaging question", other_home)
        self.assertIn("Start assessment", other_home)
        self.assertEqual(self.submit(f"/help-requests/{report['id']}/status", {"status": "open"}, other).status_code, 404)
        self.revalidate.assert_not_called()


if __name__ == "__main__":
    unittest.main()
