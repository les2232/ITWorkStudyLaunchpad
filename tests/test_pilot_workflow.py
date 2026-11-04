"""Real local HTTP and process-restart coverage using disposable synthetic data.

This checks application persistence, not browser rendering or pilot access gates.
"""

import os
import select
import subprocess
import sys
import tempfile
import unittest
from http.cookiejar import CookieJar
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import HTTPCookieProcessor, ProxyHandler, Request, build_opener

from launchpad.content import extract_checklist_items, read_checklist_markdown
from launchpad.demo import DEMO_NOVA_NAME, prepare_demo_database
from launchpad.quizzes import get_module_quiz
from launchpad.scenarios import get_scenario
from launchpad.storage import (
    activity_progress,
    checklist_progress,
    connect,
    latest_assessment_result,
    latest_module_quiz_result,
    module_is_complete,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SERVER_CODE = """
import sys
from launchpad import create_app
from werkzeug.serving import make_server

app = create_app({
    'LAUNCHPAD_DB_PATH': sys.argv[1],
    'LAUNCHPAD_DEMO_MODE': True,
    'LAUNCHPAD_PILOT_MODE': False,
    'SECRET_KEY': 'isolated-http-restart-regression-secret',
    'SESSION_COOKIE_SECURE': False,
})
server = make_server('127.0.0.1', 0, app)
print(server.server_port, flush=True)
server.serve_forever()
"""


class PilotWorkflowPersistenceTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="launchpad-http-", dir="/tmp")
        self.addCleanup(temporary.cleanup)
        self.db_path = Path(temporary.name) / "synthetic-workflow.sqlite"
        prepare_demo_database(self.db_path)
        with connect(self.db_path) as database:
            self.student_id = database.execute(
                "SELECT id FROM students WHERE display_name = ?", (DEMO_NOVA_NAME,)
            ).fetchone()["id"]
        self.other_records = self._other_learner_records()
        self._new_browser_session()

    def _new_browser_session(self):
        self.browser = build_opener(ProxyHandler({}), HTTPCookieProcessor(CookieJar()))

    @staticmethod
    def _stop_server(process):
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        if process.stdout:
            process.stdout.close()

    def _start_server(self):
        errors = tempfile.TemporaryFile(mode="w+t")
        self.addCleanup(errors.close)
        environment = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
        process = subprocess.Popen(
            [sys.executable, "-u", "-c", SERVER_CODE, str(self.db_path)],
            cwd=PROJECT_ROOT,
            env=environment,
            stdout=subprocess.PIPE,
            stderr=errors,
            text=True,
        )
        self.addCleanup(self._stop_server, process)
        readable, _, _ = select.select([process.stdout], [], [], 10)
        port_line = process.stdout.readline().strip() if readable else ""
        if not port_line.isdecimal():
            self._stop_server(process)
            errors.seek(0)
            self.fail(f"Isolated HTTP server did not start: {errors.read()}")
        self.base_url = f"http://127.0.0.1:{int(port_line)}"
        return process

    def _request(self, route, data=None):
        body = urlencode(data, doseq=True).encode() if data is not None else None
        request = Request(self.base_url + route, data=body)
        with self.browser.open(request, timeout=5) as response:
            self.assertEqual(response.status, 200, route)
            return response.read().decode("utf-8")

    def _other_learner_records(self):
        tables = (
            "assessment_results", "module_progress", "module_quiz_results",
            "checklist_progress", "activity_progress", "stuck_reports",
        )
        with connect(self.db_path) as database:
            return {
                table: [tuple(row) for row in database.execute(
                    f"SELECT * FROM {table} WHERE student_id != ? ORDER BY id",
                    (self.student_id,),
                )]
                for table in tables
            }

    def _assert_saved_state(self, total_checklist_items, scenario):
        self.assertIn("Auto-scored starting point: 18%", self._request("/assessment-results"))
        module = self._request("/modules/hardware_basics")
        self.assertIn("Reading recorded as complete.", module)
        self.assertIn("3 / 3 correct (100%)", module)
        self.assertIn(
            f"2 / {total_checklist_items} items complete",
            self._request("/checklists/day_1"),
        )
        self.assertIn(
            "This troubleshooting lab is complete",
            self._request(f"/scenarios/{scenario['id']}"),
        )
        progress = self._request("/student")
        for expected in (
            "Modules complete: 1", "Module quizzes complete: 1",
            "Checklist items complete: 2",
        ):
            self.assertIn(expected, progress)

        saved_assessment = latest_assessment_result(self.student_id, "pre", self.db_path)
        self.assertEqual(saved_assessment["technical_score"], 18)
        self.assertEqual(saved_assessment["readiness_level"], "Beginner")
        saved_quiz = latest_module_quiz_result(self.student_id, "hardware_basics", self.db_path)
        self.assertEqual((saved_quiz["score"], saved_quiz["earned"], saved_quiz["possible"]), (100, 3, 3))
        self.assertTrue(module_is_complete(self.student_id, "hardware_basics", self.db_path))
        self.assertEqual(
            checklist_progress(self.student_id, "day_1", self.db_path),
            {str(index): index in {0, 2} for index in range(total_checklist_items)},
        )
        self.assertEqual(
            activity_progress(self.student_id, self.db_path),
            {scenario["activity_id"]: True},
        )
        self.assertEqual(self._other_learner_records(), self.other_records)

    def test_saved_learner_work_survives_navigation_reload_and_process_restart(self):
        process = self._start_server()
        self._request("/student", {"display_name": DEMO_NOVA_NAME})
        self.assertIn("Synthetic demo shortcut", self._request("/pre-assessment"))
        result = self._request("/pre-assessment", {"synthetic_preset": "beginner"})
        self.assertIn("Auto-scored starting point: 18%", result)

        self.assertIn("Mark Module Complete", self._request("/modules/hardware_basics"))
        self._request("/modules/hardware_basics", {"completed": "1"})
        quiz = get_module_quiz("hardware_basics")
        self._request("/modules/hardware_basics/quiz")
        quiz_result = self._request(
            "/modules/hardware_basics/quiz",
            {question["id"]: question["answer"] for question in quiz["questions"]},
        )
        self.assertIn("3 / 3 correct (100%)", quiz_result)

        total_items = len(extract_checklist_items(read_checklist_markdown("day_1")))
        self._request("/checklists/day_1", {"completed_items": ["0", "2"]})
        scenario = get_scenario("classroom_no_display")
        scenario_url = f"/scenarios/{scenario['id']}"
        self.assertNotIn("This troubleshooting lab is complete", self._request(scenario_url))
        for inspection in scenario["required_inspections"]:
            self._request(scenario_url + "/actions", {"action_id": inspection})
        resolved = self._request(
            scenario_url + "/actions", {"action_id": scenario["resolution"]["action_id"]}
        )
        self.assertIn("not yet saved", resolved)
        self.assertEqual(activity_progress(self.student_id, self.db_path), {})
        self._request(scenario_url + "/complete", {})

        self._request("/learn")
        self._assert_saved_state(total_items, scenario)
        self._request("/help")
        self._assert_saved_state(total_items, scenario)

        self._stop_server(process)
        self._start_server()
        # An existing signed browser session survives an actual server restart.
        self._assert_saved_state(total_items, scenario)
        # A fresh browser must recover these records from SQLite, not its cookie.
        self._new_browser_session()
        self.assertIn("Choose Demo Learner", self._request("/modules/hardware_basics"))
        self._request("/student", {"display_name": DEMO_NOVA_NAME})
        self._assert_saved_state(total_items, scenario)


if __name__ == "__main__":
    unittest.main()
