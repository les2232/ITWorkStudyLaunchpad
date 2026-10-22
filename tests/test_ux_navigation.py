from collections import deque
from html.parser import HTMLParser
from pathlib import Path
import sqlite3
import tempfile
import unittest
from urllib.parse import urlsplit

from launchpad import create_app
from launchpad.content import (
    extract_checklist_items, list_checklists, list_modules,
    load_json, read_checklist_markdown,
)
from launchpad.demo import DEMO_NOVA_NAME, prepare_demo_database
from launchpad.quizzes import get_module_quiz
from launchpad.scenarios import list_scenarios
from launchpad.storage import (
    create_or_find_student, mark_module_complete, save_assessment_result,
    save_checklist_progress, set_activity_complete,
)


class Element:
    def __init__(self, tag, attrs, parents):
        self.tag = tag
        self.attrs = dict(attrs)
        self.parents = tuple(parents)
        self.text = ""

    @property
    def label(self):
        return " ".join(self.text.split())


class Page(HTMLParser):
    VOID_TAGS = {
        "area", "base", "br", "col", "embed", "hr", "img",
        "input", "link", "meta", "param", "source", "track", "wbr",
    }

    def __init__(self, response):
        super().__init__()
        self.nodes, self.stack = [], []
        self.feed(response.get_data(as_text=True))

    def handle_starttag(self, tag, attrs):
        node = Element(tag, attrs, self.stack)
        self.nodes.append(node)
        if tag not in self.VOID_TAGS:
            self.stack.append(node)

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index].tag == tag:
                self.stack = self.stack[:index]
                break

    def handle_data(self, text):
        for node in self.stack:
            node.text += text

    def find(self, tag=None, **attrs):
        return [
            node for node in self.nodes
            if (tag is None or node.tag == tag)
            and all(node.attrs.get(key) == value for key, value in attrs.items())
        ]

    def within(self, parent, tag=None):
        return [
            node for node in self.nodes
            if parent in node.parents and (tag is None or node.tag == tag)
        ]

    def primary(self, parent):
        return [
            node for node in self.within(parent)
            if node.tag in {"a", "button"}
            and {"button", "primary"} <= set(node.attrs.get("class", "").split())
        ]


class FocusedNavigationTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmpdir.name) / "ux-navigation.sqlite"
        self.app = create_app({
            "TESTING": True,
            "LAUNCHPAD_DEMO_MODE": False,
            "LAUNCHPAD_DB_PATH": str(self.db_path),
        })
        self.client = self.app.test_client()
        self.path = next(
            path for path in load_json("training_paths.json")["levels"]
            if path["slug"] == "beginner"
        )

    def tearDown(self):
        self.tmpdir.cleanup()

    def _page(self, route, client=None):
        response = (client or self.client).get(route, follow_redirects=True)
        self.assertEqual(response.status_code, 200, route)
        return Page(response)

    def _learner(self, score=0):
        name = "DEMO UX Verification"
        self.client.post("/student", data={"display_name": name})
        student = create_or_find_student(name, self.db_path)
        if score is not None:
            save_assessment_result(
                student["id"], "pre_assessment_v1", "pre",
                {
                    "score": score,
                    "path_label": self.path["label"],
                    "recommended_path": self.path["recommended_path"],
                },
                {}, self.db_path,
            )
        return student["id"]

    def _snapshot(self, db_path=None):
        with sqlite3.connect(db_path or self.db_path) as database:
            return tuple(database.iterdump())

    def _home_action(self, label, href, client=None):
        page = self._page("/", client)
        focus = page.find(id="home-next-action")[0]
        actions = page.primary(focus)
        self.assertEqual(len(actions), 1)
        self.assertEqual((actions[0].label, actions[0].attrs["href"]), (label, href))
        self.assertLessEqual(len(page.within(focus, "a")), 3)
        self.assertEqual(len(page.find("h1")), 1)
        self.assertFalse(page.find(**{"aria-label": "Launchpad inventory"}))
        self.assertFalse(page.find(**{"aria-label": "Launchpad actions"}))
        return page

    def test_four_student_categories_and_separate_mentor_navigation(self):
        expected = [
            ("Learn", "/learn"), ("Practice", "/scenarios"),
            ("Progress", "/student"), ("Help", "/help"),
        ]
        pages = expected + [
            ("Learn", "/modules/hardware_basics"),
            ("Learn", "/modules/hardware_basics/quiz"),
            ("Learn", "/training-path/beginner"),
            ("Learn", "/pre-assessment"),
            ("Practice", "/scenarios/classroom_no_display"),
            ("Progress", "/post-assessment"),
            ("Help", "/ask"), ("Help", "/stuck"),
        ]
        for category, route in pages:
            with self.subTest(route=route):
                page = self._page(route)
                nav = page.find("nav", **{"aria-label": "Primary navigation"})[0]
                links = page.within(nav, "a")
                self.assertEqual(
                    [(link.label, link.attrs["href"]) for link in links], expected
                )
                self.assertEqual(
                    [link.label for link in links
                     if link.attrs.get("aria-current") == "page"], [category]
                )
                footer = page.find("footer")[0]
                mentor_links = [
                    link for link in page.within(footer, "a")
                    if link.attrs.get("href") == "/supervisor"
                ]
                self.assertEqual([link.label for link in mentor_links], ["Mentor View"])
                self.assertFalse(any(
                    link.attrs.get("href") == "/supervisor" for link in links
                ))
                self.assertTrue(page.find("a", href="/", **{"class": "brand"}))
                self.assertTrue(page.find("a", href="#main-content"))
                self.assertEqual(len(page.find("main", id="main-content")), 1)

    def test_anonymous_and_named_fresh_home_actions(self):
        self._home_action("Start assessment", "/student?next=/pre-assessment")
        self._learner(score=None)
        self._home_action("Start assessment", "/pre-assessment")

    def test_partial_path_focuses_current_step_and_collapses_other_work(self):
        student_id = self._learner()
        mark_module_complete(student_id, "what_does_it_do", True, self.db_path)
        self._home_action("Continue: Common IT Words", "/modules/common_it_words")
        page = self._page("/training-path/beginner")
        current = page.find(id="current-step")[0]
        self.assertIn("Common IT Words", current.label)
        self.assertEqual(len(page.primary(current)), 1)
        progress = page.find("progress", id="path-progress")[0]
        self.assertEqual(progress.attrs["value"], "1")
        self.assertEqual(progress.attrs["max"], "12")
        for disclosure_id in ("remaining-steps", "completed-steps"):
            disclosure = page.find("details", id=disclosure_id)[0]
            self.assertNotIn("open", disclosure.attrs)
            self.assertTrue(page.within(disclosure, "summary"))
        preview = page.find("section", **{"aria-labelledby": "upcoming-heading"})[0]
        self.assertEqual(len(page.within(preview, "li")), 2)
        self.assertTrue(page.find(id="activity-beginner_shadow_mentor"))

    def test_completed_path_preserves_existing_completion_rules(self):
        student_id = self._learner()
        for item in self.path["required_items"]:
            if item["type"] == "module":
                mark_module_complete(student_id, item["slug"], True, self.db_path)
            elif item["type"] == "checklist":
                items = extract_checklist_items(read_checklist_markdown(item["slug"]))
                for index in range(len(items)):
                    save_checklist_progress(
                        student_id, item["slug"], str(index), True, self.db_path
                    )
            elif item["type"] == "activity":
                set_activity_complete(student_id, item["id"], True, self.db_path)
        # Do not add optional quizzes or a post-assessment to Beginner requirements.
        home = self._home_action("Take the Progress Check", "/post-assessment")
        focus = home.find(id="home-next-action")[0]
        self.assertIn("Required steps recorded", focus.label)
        self.assertIn("not mentor-confirmed readiness", focus.label)
        page = self._page("/training-path/beginner")
        self.assertEqual(page.find("progress")[0].attrs["value"], "12")
        self.assertIn("Required steps recorded", page.find(id="current-step")[0].label)
        self.assertFalse(page.find(id="remaining-steps"))
        self.assertTrue(page.find("details", id="completed-steps"))

    def test_progress_prioritizes_work_over_learner_switching(self):
        self._learner()
        page = self._page("/student")
        focus = page.find(id="progress-next-action")[0]
        picker = page.find("details", id="learner-selection")[0]
        self.assertLess(page.nodes.index(focus), page.nodes.index(picker))
        self.assertNotIn("open", picker.attrs)
        self.assertEqual(len(page.primary(focus)), 1)
        requested = self._page("/student?next=/pre-assessment")
        self.assertIn(
            "open", requested.find("details", id="learner-selection")[0].attrs
        )

    def test_module_primary_action_follows_recorded_reading_state(self):
        student_id = self._learner()
        for completed, expected in (
            (False, "Mark Module Complete"), (True, "Check Your Understanding"),
        ):
            with self.subTest(completed=completed):
                mark_module_complete(student_id, "hardware_basics", completed, self.db_path)
                page = self._page("/modules/hardware_basics")
                after_reading = page.find(
                    "section", **{"aria-labelledby": "module-next-heading"}
                )[0]
                self.assertEqual(
                    [action.label for action in page.primary(after_reading)], [expected]
                )
                quiz_links = page.find("a", href="/modules/hardware_basics/quiz")
                self.assertEqual(len(quiz_links), 1)
                body = page.find("div", **{"class": "markdown-body"})[0]
                self.assertLess(page.nodes.index(body), page.nodes.index(quiz_links[0]))
                if completed:
                    self.assertTrue(any(
                        button.label == "Mark Not Complete"
                        for button in page.within(after_reading, "button")
                    ))

    def test_existing_features_and_deep_links_remain_reachable_without_writes(self):
        self._learner()
        before = self._snapshot()
        expected = {
            "/learn", "/help", "/student", "/pre-assessment",
            "/assessment-results", "/post-assessment", "/modules",
            "/scenarios", "/ask", "/stuck", "/mentor-summary", "/supervisor",
        }
        expected.update(
            "/training-path/" + path["slug"]
            for path in load_json("training_paths.json")["levels"]
        )
        expected.update("/modules/" + item["slug"] for item in list_modules())
        expected.update(
            "/modules/" + item["slug"] + "/quiz"
            for item in list_modules() if get_module_quiz(item["slug"])
        )
        expected.update("/checklists/" + item["slug"] for item in list_checklists())
        expected.update("/scenarios/" + item["id"] for item in list_scenarios())
        visited, pending, fragments = set(), deque(["/"]), set()
        while pending:
            route = pending.popleft()
            if route in visited:
                continue
            visited.add(route)
            self.assertLess(len(visited), 150, "Unexpected crawl expansion")
            page = self._page(route)
            for link in page.find("a"):
                parsed = urlsplit(link.attrs.get("href", ""))
                if parsed.scheme or parsed.netloc:
                    continue
                target = parsed.path or route
                if not target.startswith("/") or target.startswith("/static/"):
                    continue
                pending.append(target)
                if parsed.fragment:
                    fragments.add((target, parsed.fragment))
        self.assertFalse(expected - visited, sorted(expected - visited))
        for route, fragment in fragments:
            with self.subTest(route=route, fragment=fragment):
                self.assertTrue(self._page(route).find(id=fragment))
        for alias, destination in (
            ("/day-1-checklist", "/checklists/day_1"),
            ("/week-1-checklist", "/checklists/week_1"),
        ):
            self.assertEqual(self.client.get(alias).location, destination)
        self.assertEqual(self._snapshot(), before, "Browsing must not update saved records")

    def test_guarded_anonymous_actions_preserve_selection_destination(self):
        demo_path = Path(self.tmpdir.name) / "guarded-ux-demo.sqlite"
        prepare_demo_database(demo_path)
        demo = create_app({
            "TESTING": True,
            "LAUNCHPAD_DEMO_MODE": True,
            "LAUNCHPAD_DB_PATH": str(demo_path),
            "SECRET_KEY": "synthetic-ux-test-secret",
        }).test_client()
        before = self._snapshot(demo_path)
        self._home_action("Start assessment", "/student?next=/pre-assessment", demo)
        help_page = self._page("/help", demo)
        help_focus = help_page.find(
            "section", **{"aria-labelledby": "help-heading"}
        )[0]
        self.assertEqual(
            help_page.primary(help_focus)[0].attrs["href"], "/student?next=/stuck"
        )
        path_page = self._page("/training-path/developing", demo)
        current = path_page.find(id="current-step")[0]
        self.assertEqual(
            path_page.primary(current)[0].attrs["href"],
            "/student?next=/training-path/developing",
        )
        module = self._page("/modules/hardware_basics", demo)
        after_reading = module.find(
            "section", **{"aria-labelledby": "module-next-heading"}
        )[0]
        self.assertEqual(
            [action.label for action in module.primary(after_reading)],
            ["Choose Demo Learner"],
        )
        self.assertEqual(self._snapshot(demo_path), before)
        selected = demo.post(
            "/student?next=/pre-assessment", data={"display_name": DEMO_NOVA_NAME}
        )
        self.assertEqual(selected.status_code, 302)
        self.assertEqual(selected.location, "/pre-assessment")
        self._home_action("Start assessment", "/pre-assessment", demo)


if __name__ == "__main__":
    unittest.main()
