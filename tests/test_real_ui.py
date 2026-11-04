"""Authenticated form-flow checks; these do not establish rendered-browser QA."""
from html.parser import HTMLParser
from pathlib import Path
import tempfile
import unittest

from launchpad.accounts import assign_mentor, create_auth_session, enroll_account
from launchpad.real_data import initialize_real_database
from launchpad.storage import recent_stuck_reports
from launchpad.web import create_app


class Forms(HTMLParser):
    def __init__(self, markup):
        super().__init__()
        self.forms = []
        self.current = None
        self.ids = []
        self.references = []
        self.feed(markup)

    def handle_starttag(self, tag, attributes):
        values = dict(attributes)
        if values.get("id"):
            self.ids.append(values["id"])
        for key in ("for", "aria-labelledby", "aria-describedby", "aria-controls"):
            self.references.extend(values.get(key, "").split())
        if tag == "form":
            self.current = {"action": values.get("action"), "controls": []}
            self.forms.append(self.current)
        if tag in {"input", "textarea", "select", "button"} and self.current is not None:
            self.current["controls"].append((tag, values))

    def handle_endtag(self, tag):
        if tag == "form":
            self.current = None

    def form(self, action):
        return next(item for item in self.forms if item["action"] == action)

    def hidden(self, action):
        return {attributes["name"]: attributes.get("value", "")
                for tag, attributes in self.form(action)["controls"]
                if tag == "input" and attributes.get("type") == "hidden"}


class RealUIFlowTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(dir="/tmp")
        self.database = Path(self.directory.name) / "real-ui.sqlite"
        initialize_real_database(self.database)
        self.issuer = "https://identity.example.invalid"
        self.first = enroll_account(self.issuer, "isolated-a", "Invented learner A", db_path=self.database)
        self.second = enroll_account(self.issuer, "isolated-b", "Invented learner B", db_path=self.database)
        self.mentor = enroll_account(self.issuer, "isolated-mentor", role="mentor", db_path=self.database)
        self.origin = "https://launchpad.example.invalid"
        self.app = create_app({
            "TESTING": True,
            "SECRET_KEY": "isolated-signing-secret-more-than-32-characters",
            "LAUNCHPAD_REAL_MODE": True, "LAUNCHPAD_DEMO_MODE": False, "LAUNCHPAD_PILOT_MODE": False,
            "LAUNCHPAD_DB_PATH": str(self.database),
            "LAUNCHPAD_TRUSTED_HOSTS": "launchpad.example.invalid",
            "LAUNCHPAD_OIDC_ISSUER": self.issuer,
            "LAUNCHPAD_OIDC_CLIENT_ID": "isolated-ui-client",
            "LAUNCHPAD_OIDC_CLIENT_SECRET": "isolated-ui-client-secret",
            "LAUNCHPAD_OIDC_REDIRECT_URI": self.origin + "/auth/callback",
            # Identity verification is covered by the OIDC suite, not faked as
            # browser/provider evidence by these authenticated UI flow tests.
            "LAUNCHPAD_OIDC_CLIENT": object(),
        })
        self.client = self.app.test_client()

    def tearDown(self):
        self.directory.cleanup()

    def sign_in(self, account):
        token = create_auth_session(account["id"], self.database)
        with self.client.session_transaction(base_url=self.origin) as state:
            state["auth_session"] = token

    def get(self, path):
        return self.client.get(path, base_url=self.origin)

    def post(self, path, data):
        return self.client.post(path, base_url=self.origin, data=data)

    def test_anonymous_login_form_is_csrf_protected_and_requests_no_password_or_learner_identity(self):
        response = self.get("/student")
        self.assertEqual(response.status_code, 401)
        markup = response.get_data(as_text=True)
        page = Forms(markup)
        self.assertTrue(page.hidden("/auth/login")["csrf_token"])
        inputs = [attributes for tag, attributes in page.form("/auth/login")["controls"] if tag == "input"]
        self.assertTrue(all(item.get("type") == "hidden" for item in inputs))
        self.assertIn("Continue with organization sign-in", markup)
        self.assertNotIn("Invented learner A", markup)
        self.assertNotIn("Invented learner B", markup)
        self.assertNotIn('href="/supervisor"', markup)
        self.assertEqual(len(page.ids), len(set(page.ids)))
        self.assertTrue(set(page.references) <= set(page.ids))
        self.assertEqual(self.post("/auth/login", {}).status_code, 400)

    def test_learner_progress_has_no_selector_and_logout_form_ends_access(self):
        self.sign_in(self.first)
        response = self.get("/student")
        self.assertEqual(response.status_code, 200)
        markup = response.get_data(as_text=True)
        page = Forms(markup)
        self.assertIn("My Progress", markup)
        self.assertIn("Invented learner A", markup)
        self.assertNotIn("Invented learner B", markup)
        self.assertNotIn("Switch demo learner", markup)
        self.assertNotIn('href="/supervisor"', markup)
        self.assertNotIn('name="display_name"', markup)
        self.assertNotIn('action="/student', markup)
        logout = self.post("/auth/logout", page.hidden("/auth/logout"))
        self.assertEqual(logout.status_code, 302)
        self.assertEqual(self.get("/student").status_code, 401)

    def test_rendered_help_form_submits_without_identity_fields_and_saves_only_own_record(self):
        self.sign_in(self.first)
        response = self.get("/stuck")
        self.assertEqual(response.status_code, 200)
        page = Forms(response.get_data(as_text=True))
        names = {attributes.get("name") for _, attributes in page.form("/stuck")["controls"]}
        self.assertFalse(names & {"student", "student_id", "learner_id", "display_name", "account_id"})
        data = page.hidden("/stuck") | {
            "topic": "Training monitor practice", "trying_to_do": "Complete an invented training exercise.",
            "what_happened": "The practice display was blank.", "already_checked": "Read the training checklist.",
            "current_blocker": "Need mentor guidance for the next approved practice check.", "related_item": "Training exercise",
        }
        saved = self.post("/stuck", data)
        self.assertEqual(saved.status_code, 200)
        self.assertIn("Invented learner A", saved.get_data(as_text=True))
        own = recent_stuck_reports(self.first["learner_id"], self.database)
        self.assertEqual(len(own), 1)
        self.assertIn("Invented learner A", own[0]["summary"])
        self.assertEqual(recent_stuck_reports(self.second["learner_id"], self.database), [])
        refreshed = self.get("/student").get_data(as_text=True)
        self.assertIn("Help requests: 1", refreshed)

    def test_mentor_empty_state_and_assigned_links_are_read_only_and_scoped(self):
        self.sign_in(self.mentor)
        empty = self.get("/supervisor").get_data(as_text=True)
        self.assertIn("No learners are assigned to you", empty)
        self.assertIn("Read-only mentor access", empty)
        self.assertNotIn("Invented learner A", empty)
        self.assertNotIn("Invented learner B", empty)
        assign_mentor(self.mentor["id"], self.first["learner_id"], self.database)
        response = self.get("/supervisor")
        self.assertEqual(response.status_code, 200)
        markup = response.get_data(as_text=True)
        detail = f"/supervisor/learners/{self.first['learner_id']}"
        self.assertIn(f'href="{detail}"', markup)
        self.assertNotIn("Invented learner B", markup)
        self.assertNotIn('href="/student"', markup)
        self.assertNotIn("synthetic learner", markup)
        self.assertNotIn("production student tracking", markup)
        reviewed = self.get(detail)
        self.assertEqual(reviewed.status_code, 200)
        self.assertIn("Reviewing <strong>Invented learner A</strong>", reviewed.get_data(as_text=True))
        self.assertEqual(self.get(f"/supervisor/learners/{self.second['learner_id']}").status_code, 404)
        preview = self.get("/stuck").get_data(as_text=True)
        self.assertIn("<fieldset disabled>", preview)
        self.assertEqual(self.post("/stuck", Forms(preview).hidden("/stuck")).status_code, 403)


if __name__ == "__main__":
    unittest.main()
