import unittest

from launchpad.guidance import answer_question
from launchpad.stuck import generate_stuck_summary


class GuidanceAndStuckTests(unittest.TestCase):
    def test_risky_access_question_escalates(self):
        answer = answer_question("A user cannot log in and asks me to reset a password")

        self.assertTrue(answer["should_escalate"])
        self.assertEqual(answer["related_module"], "escalation_rules")
        self.assertIn("mentor", " ".join(answer["paragraphs"]).lower())

    def test_safe_term_question_links_to_module(self):
        answer = answer_question("What is an asset tag?")

        self.assertFalse(answer["should_escalate"])
        self.assertEqual(answer["related_module"], "asset_tag_basics")

    def test_stuck_summary_preserves_context_and_stops(self):
        summary = generate_stuck_summary(
            {
                "student": "Sam",
                "topic": "Imaging",
                "trying_to_do": "image a workbench laptop",
                "what_happened": "error 0x00000000 appeared",
                "already_checked": "recorded the asset tag",
                "current_blocker": "not sure what the error means",
                "related_item": "Computer Imaging Overview",
            }
        )

        self.assertIn("Sam", summary)
        self.assertIn("error 0x00000000 appeared", summary)
        self.assertIn("Stop here", summary)
        self.assertIn("wait for the next approved step", summary)


if __name__ == "__main__":
    unittest.main()
