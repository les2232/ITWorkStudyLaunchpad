import unittest

from launchpad.assessment import get_training_path, knowledge_gaps, load_assessment, score_assessment


class AssessmentScoringTests(unittest.TestCase):
    def test_pre_assessment_all_strong_answers_scores_advanced_beginner(self):
        assessment = load_assessment("pre_assessment_v1")
        responses = {
            "q1": "A",
            "q2": [
                "connected_peripherals",
                "installed_software",
                "troubleshot_computer",
                "ticketing_system",
                "asset_tags",
            ],
            "q3": "I am nervous about imaging but I will ask for help.",
            "q4": "5",
            "q5": "5",
            "q6": "5",
            "q7": "5",
            "q8": "B",
            "q9": "B",
            "q10": "A",
            "q11": "A",
            "q12": "A",
            "q13": "B",
            "q14": "B",
            "q15": "C",
            "q16": "B",
            "q17": "B",
            "q18": "C",
            "q19": "C",
            "q20": "C",
        }

        result = score_assessment(assessment, responses)
        path = get_training_path(result["score"])

        self.assertEqual(result["score"], 100)
        self.assertEqual(path["slug"], "advanced_beginner")
        self.assertEqual(knowledge_gaps(result), [])

    def test_pre_assessment_low_answers_routes_to_beginner_and_gaps(self):
        assessment = load_assessment("pre_assessment_v1")
        responses = {question_id: "" for question_id in [f"q{number}" for number in range(1, 21)]}
        responses.update(
            {
                "q1": "B",
                "q2": ["none"],
                "q4": "1",
                "q5": "1",
                "q6": "1",
                "q7": "1",
                "q8": "A",
                "q9": "A",
                "q10": "B",
                "q11": "B",
                "q12": "B",
                "q13": "A",
                "q14": "A",
                "q15": "A",
                "q16": "A",
                "q17": "A",
                "q18": "A",
                "q19": "A",
                "q20": "A",
            }
        )

        result = score_assessment(assessment, responses)
        path = get_training_path(result["score"])
        gaps = {gap["area"] for gap in knowledge_gaps(result)}

        self.assertLessEqual(result["score"], 39)
        self.assertEqual(path["slug"], "beginner")
        self.assertIn("IT Vocabulary", gaps)
        self.assertIn("Workflow and Escalation", gaps)

    def test_score_thresholds_match_training_paths(self):
        self.assertEqual(get_training_path(39)["slug"], "beginner")
        self.assertEqual(get_training_path(40)["slug"], "developing")
        self.assertEqual(get_training_path(70)["slug"], "ready_to_shadow")
        self.assertEqual(get_training_path(85)["slug"], "advanced_beginner")


if __name__ == "__main__":
    unittest.main()
