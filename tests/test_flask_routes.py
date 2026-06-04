import os
import tempfile
import unittest
from pathlib import Path

from launchpad.assessment import get_training_path, knowledge_gaps, load_assessment, score_assessment


def load_flask_app(config=None):
    import app as app_module

    if hasattr(app_module, "create_app"):
        return app_module.create_app(config)

    if hasattr(app_module, "app"):
        return app_module.app

    raise RuntimeError("Could not find create_app() or app in app.py")


class FlaskRouteSmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmpdir = tempfile.TemporaryDirectory()
        cls.db_path = Path(cls.tmpdir.name) / "launchpad-routes.sqlite"
        cls.old_db_path = os.environ.get("LAUNCHPAD_DB_PATH")
        os.environ["LAUNCHPAD_DB_PATH"] = str(cls.db_path)
        cls.app = load_flask_app({"TESTING": True, "LAUNCHPAD_DB_PATH": str(cls.db_path)})
        cls.client = cls.app.test_client()

    @classmethod
    def tearDownClass(cls):
        if cls.old_db_path is None:
            os.environ.pop("LAUNCHPAD_DB_PATH", None)
        else:
            os.environ["LAUNCHPAD_DB_PATH"] = cls.old_db_path
        cls.tmpdir.cleanup()

    def test_simple_get_routes_do_not_crash(self):
        simple_get_routes = []

        for rule in self.app.url_map.iter_rules():
            if "GET" not in rule.methods:
                continue

            # Skip Flask's built-in static route.
            if rule.endpoint == "static":
                continue

            # Skip dynamic routes such as /modules/<module_id>.
            # Those should get separate targeted tests later.
            if rule.arguments:
                continue

            simple_get_routes.append(rule.rule)

        self.assertTrue(simple_get_routes, "No simple GET routes found to smoke test.")

        for route in simple_get_routes:
            with self.subTest(route=route):
                response = self.client.get(route)
                self.assertLess(
                    response.status_code,
                    500,
                    f"{route} returned {response.status_code}",
                )

    def test_pre_assessment_marks_role_alignment_as_separate_signal(self):
        response = self.client.get("/pre-assessment")

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Work Style and Role Alignment", response.data)
        self.assertIn(b"separate role-alignment signal", response.data)

    def test_pre_assessment_results_explain_mentor_review_items(self):
        assessment = load_assessment("pre_assessment_v1")
        result = score_assessment(assessment, {"q3": "I want help learning imaging safely."})
        path = get_training_path(result["score"])
        result["path_slug"] = path["slug"]
        result["path_label"] = path["label"]
        result["recommended_path"] = path["recommended_path"]
        result["knowledge_gaps"] = knowledge_gaps(result)
        result.pop("questions", None)
        result.pop("role_alignment", None)

        with self.client.session_transaction() as session:
            session["pre_assessment_result"] = result

        response = self.client.get("/assessment-results")

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Auto-scored readiness", response.data)
        self.assertIn(b"Free-Response Review Items", response.data)
        self.assertIn(b"not auto-scored", response.data)
        self.assertIn(b"A high auto-score does not mean the full assessment is complete", response.data)
        self.assertNotIn(b"automatically scored", response.data)

    def test_post_assessment_result_explains_mentor_review_items(self):
        response = self.client.post(
            "/post-assessment",
            data={
                "q2": "I understand tickets better.",
                "q10": "I would record the exact error and stop.",
                "q11": "Monitor had power and still showed No Signal.",
                "q12": "Imaging error 0x00000000 appeared; I stopped.",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Auto-scored readiness", response.data)
        self.assertIn(b"Free-Response Review Items", response.data)
        self.assertIn(b"not auto-scored", response.data)
        self.assertIn(b"A high auto-score does not mean the full assessment is complete", response.data)
        self.assertNotIn(b"automatically scored", response.data)

    def test_training_path_links_existing_required_items(self):
        response = self.client.get("/training-path/beginner")

        self.assertEqual(response.status_code, 200)
        self.assertIn(b'href="/modules/what_does_it_do"', response.data)
        self.assertIn(b'href="/modules/escalation_rules"', response.data)
        self.assertIn(b'href="/checklists/day_1"', response.data)

    def test_training_path_shows_scenarios_and_post_assessment(self):
        response = self.client.get("/training-path/developing")

        self.assertEqual(response.status_code, 200)
        self.assertIn(b'href="/scenarios"', response.data)
        self.assertIn(b"Recommended Scenarios", response.data)
        self.assertIn(b'href="/scenarios/ticket_term_unknown"', response.data)
        self.assertIn(b"Ready to check your progress?", response.data)
        self.assertIn(b'href="/post-assessment"', response.data)

    def test_home_discovers_scenarios_and_post_assessment(self):
        response = self.client.get("/")

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Practice Scenarios", response.data)
        self.assertIn(b'href="/scenarios"', response.data)
        self.assertIn(b"Post-Assessment", response.data)
        self.assertIn(b'href="/post-assessment"', response.data)


if __name__ == "__main__":
    unittest.main()
