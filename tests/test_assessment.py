import unittest

from launchpad.assessment import get_training_path, knowledge_gaps, load_assessment, score_assessment
from scripts.validate_content import validate_assessment_data


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
            "ra1": "B",
            "ra2": "C",
            "ra3": "A",
            "ra4": "A",
            "ra5": "B",
            "ra6": "A",
            "ra7": "A",
        }

        result = score_assessment(assessment, responses)
        path = get_training_path(result["score"])

        self.assertEqual(result["score"], 100)
        self.assertEqual(path["slug"], "advanced_beginner")
        self.assertEqual(knowledge_gaps(result), [])
        self.assertEqual(result["role_alignment"]["recommended_alignment"]["slug"], "it_launchpad")

    def test_free_response_items_are_excluded_from_auto_score_denominator(self):
        pre_assessment = load_assessment("pre_assessment_v1")
        pre_result = score_assessment(pre_assessment, {"q3": "I want help learning imaging safely."})

        post_assessment = load_assessment("post_assessment_v1")
        post_result = score_assessment(
            post_assessment,
            {
                "q2": "I understand tickets better.",
                "q10": "I would record the exact error and stop.",
                "q11": "Monitor had power and still showed No Signal.",
                "q12": "Imaging error 0x00000000 appeared; I stopped.",
            },
        )

        self.assertEqual(pre_result["possible"], 97)
        self.assertEqual(pre_result["mentor_review_points_possible"], 3)
        self.assertEqual(pre_result["mentor_review_items"][0]["id"], "q3")
        self.assertIsNone(pre_result["mentor_review_items"][0]["earned"])

        self.assertEqual(post_result["possible"], 65)
        self.assertEqual(post_result["mentor_review_points_possible"], 35)
        self.assertEqual(
            {item["id"] for item in post_result["mentor_review_items"]},
            {"q2", "q10", "q11", "q12"},
        )
        self.assertTrue(all(item["earned"] is None for item in post_result["mentor_review_items"]))

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
                "ra1": "B",
                "ra2": "C",
                "ra3": "B",
                "ra4": "B",
                "ra5": "B",
                "ra6": "A",
                "ra7": "B",
            }
        )

        result = score_assessment(assessment, responses)
        path = get_training_path(result["score"])
        gaps = {gap["area"] for gap in knowledge_gaps(result)}

        self.assertLessEqual(result["score"], 39)
        self.assertEqual(path["slug"], "beginner")
        self.assertIn("IT Vocabulary", gaps)
        self.assertIn("Workflow and Escalation", gaps)
        self.assertEqual(result["role_alignment"]["recommended_alignment"]["slug"], "student_services_exploration")

    def test_score_thresholds_match_training_paths(self):
        self.assertEqual(get_training_path(39)["slug"], "beginner")
        self.assertEqual(get_training_path(40)["slug"], "developing")
        self.assertEqual(get_training_path(70)["slug"], "ready_to_shadow")
        self.assertEqual(get_training_path(85)["slug"], "advanced_beginner")

    def test_role_alignment_can_recommend_hybrid_support(self):
        assessment = load_assessment("pre_assessment_v1")
        responses = {
            "ra1": "B",
            "ra2": "C",
            "ra3": "A",
            "ra4": "B",
            "ra5": "B",
            "ra6": "B",
            "ra7": "B",
        }

        result = score_assessment(assessment, responses)
        alignment = result["role_alignment"]

        self.assertEqual(alignment["recommended_alignment"]["slug"], "hybrid_it_user_support")
        self.assertIn("Technical troubleshooting interest", [signal["label"] for signal in alignment["signals"]])
        self.assertIn("User-facing support interest", [signal["label"] for signal in alignment["signals"]])

    def test_role_alignment_can_recommend_structured_shadowing(self):
        assessment = load_assessment("pre_assessment_v1")
        responses = {
            "ra1": "C",
            "ra2": "A",
            "ra3": "D",
            "ra4": "D",
            "ra5": "A",
            "ra6": "D",
            "ra7": "D",
        }

        result = score_assessment(assessment, responses)

        self.assertEqual(result["score"], 1)
        self.assertEqual(result["possible"], 97)
        self.assertEqual(result["role_alignment"]["recommended_alignment"]["slug"], "structured_shadowing")

    def test_pre_assessment_role_alignment_content_validates(self):
        self.assertEqual(validate_assessment_data("pre_assessment_v1.json"), [])


if __name__ == "__main__":
    unittest.main()
