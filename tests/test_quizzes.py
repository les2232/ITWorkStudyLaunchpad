import unittest

from launchpad.content import list_modules
from launchpad.quizzes import get_module_quiz, list_module_quizzes, score_module_quiz


class ModuleQuizTests(unittest.TestCase):
    def test_every_module_has_a_quiz(self):
        module_slugs = {module["slug"] for module in list_modules()}
        quiz_slugs = set(list_module_quizzes())

        self.assertEqual(module_slugs, quiz_slugs)

    def test_quiz_questions_are_low_stakes_and_auto_scorable(self):
        for module_slug, quiz in list_module_quizzes().items():
            with self.subTest(module_slug=module_slug):
                self.assertIn("Knowledge Check", quiz["title"])
                self.assertGreaterEqual(len(quiz["questions"]), 3)
                self.assertLessEqual(len(quiz["questions"]), 5)
                for question in quiz["questions"]:
                    self.assertIn(question["type"], {"multiple_choice", "true_false"})
                    self.assertIn(question["answer"], {choice["value"] for choice in question["choices"]})
                    self.assertTrue(question["feedback"])

    def test_score_module_quiz_counts_correct_answers(self):
        quiz = get_module_quiz("hardware_basics")
        responses = {question["id"]: question["answer"] for question in quiz["questions"]}
        first_question = quiz["questions"][0]
        responses[first_question["id"]] = next(
            choice["value"] for choice in first_question["choices"] if choice["value"] != first_question["answer"]
        )

        result = score_module_quiz(quiz, responses)

        self.assertEqual(result["earned"], 2)
        self.assertEqual(result["possible"], 3)
        self.assertEqual(result["score"], 67)
        self.assertFalse(result["answers"][0]["is_correct"])
        self.assertTrue(result["answers"][1]["is_correct"])


if __name__ == "__main__":
    unittest.main()
