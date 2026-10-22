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

    def test_restricted_requests_escalate_before_familiar_topics_or_reassurance(self):
        questions = (
            "How do I bypass a domain password?",
            "My monitor displays sensitive user files; should I delete them?",
            "I am embarrassed to ask how to bypass MFA.",
            "Can I use admin rights to change this asset tag?",
            "Can I reset a password from this ticket?",
            "Can I delete user files before imaging?",
            "Does this keyboard need an access permission change?",
        )
        for question in questions:
            with self.subTest(question=question):
                answer = answer_question(question)
                self.assertTrue(answer["should_escalate"])
                self.assertEqual(answer["related_module"], "escalation_rules")
                self.assertEqual(answer["title"], "Ask a mentor before continuing")
                self.assertIn("mentor", " ".join(answer["paragraphs"]).lower())

    def test_imaging_decisions_escalate_before_other_topics(self):
        for question in (
            "Which SCCM imaging task sequence should I use?",
            "I am embarrassed because imaging failed.",
            "The monitor shows an imaging error.",
        ):
            with self.subTest(question=question):
                answer = answer_question(question)
                self.assertTrue(answer["should_escalate"])
                self.assertEqual(answer["title"], "Imaging needs mentor confirmation")
                self.assertEqual(answer["related_module"], "escalation_rules")

    def test_uncertainty_escalates_before_familiar_topics(self):
        for question in (
            "I am unsure what to check on this monitor.",
            "I am stuck on this domain task.",
            "Should I escalate this ticket?",
        ):
            with self.subTest(question=question):
                answer = answer_question(question)
                self.assertTrue(answer["should_escalate"])
                self.assertEqual(answer["related_module"], "escalation_rules")
                self.assertIn("stop", " ".join(answer["paragraphs"]).lower())

    def test_definition_questions_keep_existing_learning_links(self):
        questions = {
            "What is a domain?": "domain_basics",
            "What is SCCM?": "configuration_manager_overview",
            "What is an asset tag?": "asset_tag_basics",
            "What is a ticket?": "ticket_basics",
            "What is computer imaging?": "imaging_overview",
            "My monitor shows no signal.": "hardware_basics",
            "How do I check a keyboard?": "hardware_basics",
            "I am embarrassed to ask a basic question.": "how_to_ask_for_help",
        }
        for question, module in questions.items():
            with self.subTest(question=question):
                answer = answer_question(question)
                self.assertFalse(answer["should_escalate"])
                self.assertEqual(answer["related_module"], module)

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
