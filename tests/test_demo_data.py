import os
import sqlite3
import tempfile
import unittest
from html.parser import HTMLParser
from pathlib import Path

from launchpad import create_app
from launchpad.assessment import all_questions, get_training_path, load_assessment, score_assessment
from launchpad.content import extract_checklist_items, read_checklist_markdown
from launchpad.demo import (
    DEMO_DATASET_ID,
    DEMO_LEARNER_NAMES,
    DEMO_NOVA_NAME,
    DEMO_QUINN_NAME,
    DEMO_RILEY_NAME,
    DEMO_TIMESTAMP,
    NO_DISPLAY_ACTIVITY_ID,
    DemoDataError,
    prepare_demo_database,
    reset_demo_database,
    synthetic_beginner_responses,
    synthetic_developing_responses,
    synthetic_ready_to_shadow_responses,
    validate_demo_database,
)
from launchpad.storage import (
    DEFAULT_DB_PATH,
    activity_progress,
    checklist_progress,
    connect,
    create_or_find_student,
    latest_assessment_result,
    mark_module_complete,
    module_is_complete,
)


class SyntheticResponseTests(unittest.TestCase):
    def test_profiles_are_complete_deterministic_and_land_in_expected_paths(self):
        assessment = load_assessment("pre_assessment_v1")
        question_ids = {question["id"] for question in all_questions(assessment)}
        profiles = (
            (synthetic_beginner_responses, 18, "beginner"),
            (synthetic_ready_to_shadow_responses, 75, "ready_to_shadow"),
            (synthetic_developing_responses, 55, "developing"),
        )

        for profile, expected_score, expected_path in profiles:
            with self.subTest(profile=profile.__name__):
                first = profile()
                second = profile()
                self.assertEqual(first, second)
                self.assertIsNot(first, second)
                self.assertEqual(set(first), question_ids)
                result = score_assessment(assessment, first)
                self.assertEqual(result["score"], expected_score)
                self.assertEqual(get_training_path(result["score"])["slug"], expected_path)

        changed = synthetic_beginner_responses()
        changed["q2"].append("customer_service")
        self.assertEqual(synthetic_beginner_responses()["q2"], ["none"])


class DemoDatabaseTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory(dir="/tmp")
        self.root = Path(self.tmpdir.name)
        self.db_path = self.root / "launchpad-demo.sqlite"

    def tearDown(self):
        self.tmpdir.cleanup()

    def _students(self, db_path=None):
        with connect(db_path or self.db_path) as db:
            rows = db.execute("SELECT * FROM students ORDER BY id").fetchall()
        return {row["display_name"]: dict(row) for row in rows}

    def _snapshot(self, db_path=None):
        tables = (
            "demo_dataset_metadata",
            "students",
            "assessment_results",
            "module_progress",
            "module_quiz_results",
            "checklist_progress",
            "activity_progress",
            "stuck_reports",
        )
        result = {}
        with connect(db_path or self.db_path) as db:
            for table in tables:
                if table == "demo_dataset_metadata":
                    rows = db.execute(
                        "SELECT singleton, dataset_id, schema_version "
                        "FROM demo_dataset_metadata"
                    )
                else:
                    rows = db.execute(f"SELECT * FROM {table}")
                result[table] = [tuple(row) for row in rows]
        return result

    def test_prepare_seeds_only_the_three_fixed_synthetic_personas(self):
        prepared = prepare_demo_database(self.db_path)
        validation = validate_demo_database(self.db_path)
        students = self._students()

        self.assertEqual(prepared, self.db_path)
        self.assertEqual(validation["dataset_id"], DEMO_DATASET_ID)
        self.assertTrue(validation["session_generation"])
        self.assertEqual(set(students), set(DEMO_LEARNER_NAMES))
        self.assertEqual(self.db_path.stat().st_mode & 0o777, 0o600)

        nova_id = students[DEMO_NOVA_NAME]["id"]
        with connect(self.db_path) as db:
            nova_record_counts = {
                table: db.execute(
                    f"SELECT COUNT(*) AS count FROM {table} WHERE student_id = ?",
                    (nova_id,),
                ).fetchone()["count"]
                for table in (
                    "assessment_results",
                    "module_progress",
                    "module_quiz_results",
                    "checklist_progress",
                    "activity_progress",
                    "stuck_reports",
                )
            }
        self.assertEqual(set(nova_record_counts.values()), {0})

        riley_id = students[DEMO_RILEY_NAME]["id"]
        riley_result = latest_assessment_result(riley_id, "pre", self.db_path)
        riley_checklist = checklist_progress(riley_id, "day_1", self.db_path)
        riley_activities = activity_progress(riley_id, self.db_path)
        day_one_count = len(extract_checklist_items(read_checklist_markdown("day_1")))
        self.assertEqual(riley_result["technical_score"], 75)
        self.assertEqual(riley_result["readiness_level"], "Ready to Shadow")
        self.assertEqual(len(riley_checklist), day_one_count)
        self.assertTrue(all(riley_checklist.values()))
        self.assertTrue(riley_activities["ready_to_shadow_department_expectations"])
        self.assertNotIn("ready_to_shadow_confidentiality_review", riley_activities)

        quinn_id = students[DEMO_QUINN_NAME]["id"]
        quinn_result = latest_assessment_result(quinn_id, "pre", self.db_path)
        quinn_activities = activity_progress(quinn_id, self.db_path)
        self.assertEqual(quinn_result["technical_score"], 55)
        self.assertEqual(quinn_result["readiness_level"], "Developing")
        self.assertTrue(quinn_activities["developing_shadow_mentor"])
        self.assertTrue(quinn_activities["developing_scenario_practice"])
        self.assertNotIn(NO_DISPLAY_ACTIVITY_ID, quinn_activities)
        for module_id in (
            "common_it_words",
            "hardware_basics",
            "imaging_overview",
            "ticket_basics",
            "escalation_rules",
            "how_to_ask_for_help",
        ):
            self.assertTrue(module_is_complete(quinn_id, module_id, self.db_path))
        self.assertTrue(all(checklist_progress(quinn_id, "day_1", self.db_path).values()))

        with connect(self.db_path) as db:
            timestamp_values = {
                row[0] for row in db.execute("SELECT DISTINCT updated_at FROM students")
            }
            no_display_rows = db.execute(
                "SELECT COUNT(*) FROM activity_progress WHERE activity_id = ?",
                (NO_DISPLAY_ACTIVITY_ID,),
            ).fetchone()[0]
        self.assertEqual(timestamp_values, {DEMO_TIMESTAMP})
        self.assertEqual(no_display_rows, 0)

    def test_prepare_is_semantically_repeatable(self):
        second_path = self.root / "launchpad-demo-second.sqlite"
        prepare_demo_database(self.db_path)
        prepare_demo_database(second_path)

        self.assertEqual(self._snapshot(self.db_path), self._snapshot(second_path))

    def test_prepare_refuses_existing_file_without_changing_it(self):
        original = b"existing non-SQLite content"
        self.db_path.write_bytes(original)

        with self.assertRaisesRegex(DemoDataError, "already exists"):
            prepare_demo_database(self.db_path)

        self.assertEqual(self.db_path.read_bytes(), original)

    def test_unsafe_paths_and_symlinks_are_refused(self):
        outside_tmp = DEFAULT_DB_PATH.parent / "never-demo.sqlite"
        relative = Path("relative-demo.sqlite")
        missing_parent = self.root / "missing" / "demo.sqlite"
        target = self.root / "target.sqlite"
        link = self.root / "linked.sqlite"
        target.write_bytes(b"not a database")
        link.symlink_to(target)

        for unsafe_path in (DEFAULT_DB_PATH, outside_tmp, relative, missing_parent, link):
            with self.subTest(path=unsafe_path):
                with self.assertRaises(DemoDataError):
                    prepare_demo_database(unsafe_path)

        self.assertEqual(target.read_bytes(), b"not a database")

    def test_reset_quarantines_verified_database_and_restores_seed(self):
        prepare_demo_database(self.db_path)
        original_snapshot = self._snapshot()
        original_generation = validate_demo_database(self.db_path)["session_generation"]
        nova_id = self._students()[DEMO_NOVA_NAME]["id"]
        mark_module_complete(nova_id, "hardware_basics", True, self.db_path)

        prepared, quarantine = reset_demo_database(self.db_path)

        self.assertEqual(prepared, self.db_path)
        self.assertTrue(self.db_path.exists())
        self.assertTrue(quarantine.exists())
        self.assertNotEqual(quarantine, self.db_path)
        refreshed = validate_demo_database(self.db_path)
        validate_demo_database(quarantine)
        self.assertNotEqual(refreshed["session_generation"], original_generation)
        self.assertEqual(self._snapshot(), original_snapshot)
        fresh_nova_id = self._students()[DEMO_NOVA_NAME]["id"]
        self.assertFalse(module_is_complete(fresh_nova_id, "hardware_basics", self.db_path))

    def test_reset_refuses_non_sqlite_unknown_learners_and_unknown_tables(self):
        self.db_path.write_bytes(b"not SQLite")
        with self.assertRaisesRegex(DemoDataError, "not a SQLite database"):
            reset_demo_database(self.db_path)
        self.assertEqual(self.db_path.read_bytes(), b"not SQLite")

        self.db_path.unlink()
        prepare_demo_database(self.db_path)
        create_or_find_student("UNAPPROVED Fixture Persona", self.db_path)
        original_identity = os.stat(self.db_path)
        with self.assertRaisesRegex(DemoDataError, "outside the three fixed"):
            reset_demo_database(self.db_path)
        self.assertEqual(os.stat(self.db_path).st_ino, original_identity.st_ino)
        self.assertEqual(list(self.root.glob("*.quarantine-*.sqlite")), [])

        with connect(self.db_path) as db:
            db.execute("DELETE FROM students WHERE display_name = 'UNAPPROVED Fixture Persona'")
            db.execute("CREATE TABLE unexpected_records (id INTEGER PRIMARY KEY)")
        with self.assertRaisesRegex(DemoDataError, "unknown tables"):
            reset_demo_database(self.db_path)
        self.assertTrue(self.db_path.exists())

    def test_reset_refuses_database_with_sqlite_sidecar(self):
        prepare_demo_database(self.db_path)
        sidecar = Path(f"{self.db_path}-wal")
        sidecar.write_bytes(b"synthetic test sidecar")

        with self.assertRaisesRegex(DemoDataError, "sidecar files"):
            reset_demo_database(self.db_path)

        self.assertTrue(self.db_path.exists())
        self.assertTrue(sidecar.exists())

    def test_demo_mode_startup_fails_closed_without_a_valid_database_and_secret(self):
        missing_path = self.root / "missing-demo.sqlite"
        explicit_secret = "demo-mode-startup-test-secret"

        with self.assertRaises(DemoDataError):
            create_app(
                {
                    "TESTING": True,
                    "LAUNCHPAD_DEMO_MODE": True,
                    "LAUNCHPAD_DB_PATH": str(missing_path),
                    "SECRET_KEY": explicit_secret,
                }
            )
        self.assertFalse(missing_path.exists())

        with self.assertRaises(DemoDataError):
            create_app(
                {
                    "TESTING": True,
                    "LAUNCHPAD_DEMO_MODE": True,
                    "LAUNCHPAD_DB_PATH": str(DEFAULT_DB_PATH),
                    "SECRET_KEY": explicit_secret,
                }
            )

        prepare_demo_database(self.db_path)
        with self.assertRaisesRegex(DemoDataError, "explicit LAUNCHPAD_SECRET_KEY"):
            create_app(
                {
                    "TESTING": True,
                    "LAUNCHPAD_DEMO_MODE": True,
                    "LAUNCHPAD_DB_PATH": str(self.db_path),
                    "SECRET_KEY": "dev-only-launchpad-secret",
                }
            )

        app = create_app(
            {
                "TESTING": True,
                "LAUNCHPAD_DEMO_MODE": True,
                "LAUNCHPAD_DB_PATH": str(self.db_path),
                "SECRET_KEY": explicit_secret,
            }
        )
        self.assertTrue(app.config["LAUNCHPAD_DEMO_SESSION_GENERATION"])

    def test_demo_mode_allows_only_fixed_personas_and_binds_preset_to_nova(self):
        prepare_demo_database(self.db_path)
        app = create_app(
            {
                "TESTING": True,
                "LAUNCHPAD_DEMO_MODE": True,
                "LAUNCHPAD_DB_PATH": str(self.db_path),
                "SECRET_KEY": "demo-mode-persona-test-secret",
            }
        )
        client = app.test_client()

        picker = client.get("/student")
        self.assertEqual(picker.status_code, 200)
        self.assertIn(b"Demonstration mode", picker.data)
        self.assertIn(b"synthetic learner data only", picker.data)
        self.assertIn(b"Community College of Aurora", picker.data)
        self.assertIn(b'href="#main-content"', picker.data)
        for learner_name in DEMO_LEARNER_NAMES:
            self.assertIn(learner_name.encode(), picker.data)
        for persona_role in (
            b"New beginner",
            b"Returning learner",
            b"Scenario learner",
        ):
            self.assertIn(persona_role, picker.data)
        self.assertNotIn(b'autocomplete="name"', picker.data)

        home = client.get("/")
        self.assertEqual(home.status_code, 200)
        self.assertIn(
            "Demonstration mode — synthetic learner data only".encode("utf-8"),
            home.data,
        )
        self.assertLess(home.data.index(b"</header>"), home.data.index(b"class=\x22demo-banner\x22"))
        self.assertLess(home.data.index(b"class=\x22demo-banner\x22"), home.data.index(b"<main"))
        self.assertIn(b'aria-label="Mentor navigation"', home.data)
        self.assertIn(b"href=\x22/supervisor\x22", home.data)
        self.assertIn(b"Mentor View", home.data)
        self.assertGreater(home.data.index(b'href="/supervisor"'), home.data.index(b"<footer"))
        self.assertIn(b">Progress</a>", home.data)
        self.assertIn(b"Start assessment", home.data)
        self.assertIn(b"Choose a synthetic learner", home.data)
        self.assertIn(b"href=\x22/student?next=/pre-assessment\x22", home.data)
        self.assertEqual(home.data.count(b"<h1"), 1)
        self.assertIn(
            b"Welcome to the Launchpad.",
            home.data,
        )
        self.assertNotIn(b"Starting paths", home.data)
        self.assertIn(
            b"Your onboarding journey",
            home.data,
        )
        for score_range in (b"0-39%", b"40-69%", b"70-84%", b"85-100%"):
            self.assertNotIn(score_range, home.data)

        for route, marker in (
            ("/pre-assessment", b"Choose a synthetic learner before starting."),
            ("/modules/hardware_basics", b"Choose Demo Learner"),
            ("/modules/hardware_basics/quiz", b"Choose a synthetic learner before starting."),
            ("/checklists/day_1", b"Choose Demo Learner"),
            ("/training-path/developing", b"Choose a synthetic learner to save activity progress."),
        ):
            with self.subTest(unselected_demo_route=route):
                unselected_page = client.get(route)
                self.assertEqual(unselected_page.status_code, 200)
                self.assertIn(marker, unselected_page.data)

        refused = client.post(
            "/student", data={"display_name": "Unapproved Real Name"}
        )
        self.assertEqual(refused.status_code, 400)
        self.assertEqual(set(self._students()), set(DEMO_LEARNER_NAMES))

        self.assertEqual(
            client.post(
                "/student", data={"display_name": DEMO_RILEY_NAME}
            ).status_code,
            302,
        )
        self.assertNotIn(b"Synthetic demo shortcut", client.get("/pre-assessment").data)
        riley_home = client.get("/")
        self.assertIn(b">Progress</a>", riley_home.data)
        self.assertIn(DEMO_RILEY_NAME.encode(), riley_home.data)
        self.assertNotIn(b"nav__persona--choose", riley_home.data)
        self.assertEqual(
            client.post(
                "/pre-assessment", data={"synthetic_preset": "beginner"}
            ).status_code,
            400,
        )
        riley_id = self._students()[DEMO_RILEY_NAME]["id"]
        self.assertEqual(
            latest_assessment_result(riley_id, "pre", self.db_path)["technical_score"],
            75,
        )

        forged_switch = client.post(
            "/stuck",
            data={
                "student": DEMO_NOVA_NAME,
                "trying_to_do": "Synthetic practice only",
                "what_happened": "Synthetic result only",
                "already_checked": "Synthetic checks only",
                "current_blocker": "Synthetic blocker only",
            },
        )
        self.assertEqual(forged_switch.status_code, 400)

        self.assertEqual(
            client.post(
                "/student", data={"display_name": DEMO_NOVA_NAME}
            ).status_code,
            302,
        )
        self.assertIn(b"Synthetic demo shortcut", client.get("/pre-assessment").data)
        self.assertEqual(
            client.post(
                "/pre-assessment", data={"synthetic_preset": "beginner"}
            ).status_code,
            302,
        )
        nova_id = self._students()[DEMO_NOVA_NAME]["id"]
        self.assertEqual(
            latest_assessment_result(nova_id, "pre", self.db_path)["technical_score"],
            18,
        )
        self.assertEqual(set(self._students()), set(DEMO_LEARNER_NAMES))

    def test_assessment_and_draft_controls_require_a_selected_demo_learner(self):
        class LearnerControls(HTMLParser):
            def __init__(self, response):
                super().__init__()
                self.controls = []
                self.feed(response.get_data(as_text=True))

            def handle_starttag(self, tag, attrs):
                attributes = dict(attrs)
                if tag in {"input", "textarea", "button"} and attributes.get("type") != "hidden":
                    self.controls.append((tag, attributes))

        prepare_demo_database(self.db_path)
        app = create_app({
            "TESTING": True,
            "LAUNCHPAD_DEMO_MODE": True,
            "LAUNCHPAD_DB_PATH": str(self.db_path),
            "SECRET_KEY": "demo-assessment-controls-test-secret",
        })
        client = app.test_client()

        for selected in (False, True):
            if selected:
                self.assertEqual(
                    client.post("/student", data={"display_name": DEMO_RILEY_NAME}).status_code,
                    302,
                )
            for route, notice_id in (
                ("/pre-assessment", "assessment-learner-required"),
                ("/post-assessment", "assessment-learner-required"),
                ("/scenarios/ticket_term_unknown", "scenario-learner-required"),
            ):
                with self.subTest(route=route, selected=selected):
                    response = client.get(route)
                    self.assertEqual(response.status_code, 200)
                    page = LearnerControls(response)
                    self.assertTrue(page.controls)
                    buttons = [attrs for tag, attrs in page.controls if tag == "button"]
                    self.assertEqual(len(buttons), 1)
                    self.assertEqual(buttons[0].get("type"), "submit")
                    for tag, attrs in page.controls:
                        self.assertEqual("disabled" in attrs, not selected, (tag, attrs))
                    if not selected:
                        self.assertEqual(
                            buttons[0].get("aria-describedby"),
                            notice_id,
                        )
                        self.assertIn(f'id="{notice_id}"'.encode(), response.data)
                        self.assertIn(f'href="/student?next={route}"'.encode(), response.data)

    def test_nova_saved_synthetic_response_renders_after_session_reload(self):
        prepare_demo_database(self.db_path)
        app = create_app(
            {
                "TESTING": True,
                "LAUNCHPAD_DEMO_MODE": True,
                "LAUNCHPAD_DB_PATH": str(self.db_path),
                "SECRET_KEY": "demo-mode-saved-response-test-secret",
            }
        )
        client = app.test_client()
        expected_response = synthetic_beginner_responses()["q3"]

        self.assertEqual(
            client.post(
                "/student", data={"display_name": DEMO_NOVA_NAME}
            ).status_code,
            302,
        )
        self.assertEqual(
            client.post(
                "/pre-assessment", data={"synthetic_preset": "beginner"}
            ).status_code,
            302,
        )

        nova_id = self._students()[DEMO_NOVA_NAME]["id"]
        saved = latest_assessment_result(nova_id, "pre", self.db_path)
        self.assertEqual(saved["technical_score"], 18)
        self.assertEqual(saved["readiness_level"], "Beginner")
        self.assertEqual(
            saved["recommended_training_path"],
            "Full IT Foundations path",
        )
        self.assertEqual(saved["answers"]["q3"], expected_response)

        with client.session_transaction() as browser_session:
            browser_session.pop("pre_assessment_result", None)

        reloaded = client.get("/assessment-results")
        self.assertEqual(reloaded.status_code, 200)
        self.assertIn(b"Question", reloaded.data)
        self.assertIn(
            b"What are you most nervous about in this role?",
            reloaded.data,
        )
        self.assertIn(b"Synthetic response", reloaded.data)
        self.assertIn(expected_response.encode(), reloaded.data)

    def test_demo_reset_invalidates_existing_browser_scenario_state(self):
        prepare_demo_database(self.db_path)
        secret = "demo-reset-session-test-secret"
        app = create_app(
            {
                "TESTING": True,
                "LAUNCHPAD_DEMO_MODE": True,
                "LAUNCHPAD_DB_PATH": str(self.db_path),
                "SECRET_KEY": secret,
            }
        )
        client = app.test_client()
        self.assertEqual(
            client.post(
                "/student", data={"display_name": DEMO_QUINN_NAME}
            ).status_code,
            302,
        )
        quinn_id = self._students()[DEMO_QUINN_NAME]["id"]
        with client.session_transaction() as browser_session:
            old_generation = browser_session["demo_dataset_generation"]
            browser_session["guided_scenario_states"] = {
                f"{quinn_id}:classroom_no_display": {
                    "inspected": [
                        "computer_power",
                        "monitor_status",
                        "input_source",
                        "display_cable",
                    ],
                    "resolved": True,
                    "feedback": "Synthetic resolved state before reset.",
                    "feedback_tone": "success",
                    "last_action": "reconnect_displayport",
                }
            }
        self.assertIn(
            b"Finish and save", client.get("/scenarios/classroom_no_display").data
        )

        reset_demo_database(self.db_path)
        restarted_app = create_app(
            {
                "TESTING": True,
                "LAUNCHPAD_DEMO_MODE": True,
                "LAUNCHPAD_DB_PATH": str(self.db_path),
                "SECRET_KEY": secret,
            }
        )
        restarted_client = restarted_app.test_client()
        with restarted_client.session_transaction() as browser_session:
            browser_session["demo_dataset_generation"] = old_generation
            browser_session["student_id"] = quinn_id
            browser_session["student_display_name"] = DEMO_QUINN_NAME
            browser_session["guided_scenario_states"] = {"stale": "state"}

        page = restarted_client.get("/scenarios/classroom_no_display")
        self.assertEqual(page.status_code, 200)
        self.assertIn(b"0 of 4 required checks complete", page.data)
        self.assertIn(b"Choose a synthetic demo learner first", page.data)
        self.assertNotIn(b"Finish and save", page.data)
        with restarted_client.session_transaction() as browser_session:
            self.assertNotEqual(
                browser_session["demo_dataset_generation"], old_generation
            )
            self.assertNotIn("student_id", browser_session)
            self.assertNotIn("guided_scenario_states", browser_session)


if __name__ == "__main__":
    unittest.main()
