import copy
import unittest

from scripts.validate_content import (
    REQUIRED_DATA_FILES,
    read_json,
    validate_scenarios,
    validate_training_paths,
)


class ScenarioValidationTests(unittest.TestCase):
    def setUp(self):
        self.scenarios = read_json("scenarios.json")
        self.training_paths = read_json("training_paths.json")
        self.guided = next(
            scenario
            for scenario in self.scenarios
            if scenario["id"] == "classroom_no_display"
        )

    def _developing_activity(self, paths=None):
        paths = paths or self.training_paths
        developing = next(
            level for level in paths["levels"] if level["slug"] == "developing"
        )
        return next(
            item
            for item in developing["required_items"]
            if item.get("id") == "developing_no_display_troubleshooting"
        )

    def test_scenarios_json_is_required_and_current_content_is_valid(self):
        self.assertIn("scenarios.json", REQUIRED_DATA_FILES)
        self.assertEqual(validate_scenarios(self.scenarios, self.training_paths), [])
        self.assertEqual(
            validate_training_paths(self.training_paths, self.scenarios), []
        )

    def test_loose_displayport_scenario_has_deterministic_contract(self):
        self.assertEqual(self.guided["scenario_type"], "guided_troubleshooting")
        self.assertEqual(
            self.guided["activity_id"], "developing_no_display_troubleshooting"
        )
        self.assertEqual(
            self.guided["required_inspections"],
            ["computer_power", "monitor_status", "input_source", "display_cable"],
        )
        self.assertEqual(
            self.guided["resolution"]["action_id"], "reconnect_displayport"
        )
        self.assertIn(
            "practice display is restored",
            self.guided["resolution"]["confirmation"].lower(),
        )
        self.assertIn("unsafe", {action["kind"] for action in self.guided["actions"]})
        self.assertIn(
            "premature", {action["kind"] for action in self.guided["actions"]}
        )

        activity = self._developing_activity()
        self.assertEqual(activity["label"], "Classroom computer has no display")
        self.assertEqual(activity["scenario_id"], "classroom_no_display")

    def test_legacy_text_response_scenario_remains_valid(self):
        legacy = copy.deepcopy(self.scenarios[0])

        self.assertNotIn("scenario_type", legacy)
        self.assertEqual(validate_scenarios([legacy], self.training_paths), [])

    def test_duplicate_scenario_inspection_and_action_ids_are_rejected(self):
        duplicate_scenarios = copy.deepcopy(self.scenarios)
        duplicate_scenarios.append(copy.deepcopy(self.scenarios[0]))

        duplicate_guided = copy.deepcopy(self.guided)
        duplicate_guided["inspections"].append(
            copy.deepcopy(duplicate_guided["inspections"][0])
        )
        duplicate_guided["actions"].append(
            copy.deepcopy(duplicate_guided["actions"][0])
        )

        scenario_errors = validate_scenarios(
            duplicate_scenarios, self.training_paths
        )
        guided_errors = validate_scenarios([duplicate_guided], self.training_paths)

        self.assertTrue(
            any("duplicate scenario id: ticket_term_unknown" in error for error in scenario_errors)
        )
        self.assertTrue(
            any("duplicate inspection id: computer_power" in error for error in guided_errors)
        )
        self.assertTrue(
            any("duplicate action id: reconnect_displayport" in error for error in guided_errors)
        )

    def test_required_inspection_and_resolution_references_are_validated(self):
        scenario = copy.deepcopy(self.guided)
        scenario["required_inspections"].append("missing_inspection")
        scenario["resolution"]["action_id"] = "missing_action"

        errors = validate_scenarios([scenario], self.training_paths)

        self.assertTrue(
            any("required inspections are not defined" in error for error in errors)
        )
        self.assertTrue(
            any("resolution references unknown action: missing_action" in error for error in errors)
        )

    def test_inspection_definitions_must_all_be_required(self):
        scenario = copy.deepcopy(self.guided)
        scenario["inspections"].append(
            {
                "id": "unused_check",
                "label": "Inspect unused check",
                "feedback": "This synthetic check is intentionally unreferenced.",
            }
        )

        errors = validate_scenarios([scenario], self.training_paths)

        self.assertTrue(any("inspections are not required" in error for error in errors))

    def test_path_scenario_references_and_activity_linkage_are_validated(self):
        unknown_paths = copy.deepcopy(self.training_paths)
        self._developing_activity(unknown_paths)["scenario_id"] = "unknown_scenario"

        missing_link_paths = copy.deepcopy(self.training_paths)
        del self._developing_activity(missing_link_paths)["scenario_id"]

        path_errors = validate_training_paths(unknown_paths, self.scenarios)
        scenario_errors = validate_scenarios([self.guided], missing_link_paths)

        self.assertTrue(
            any("unknown scenario id: unknown_scenario" in error for error in path_errors)
        )
        self.assertTrue(
            any("must reference its scenario_id" in error for error in scenario_errors)
        )

    def test_legacy_lists_and_guided_action_kinds_are_schema_validated(self):
        malformed_legacy = copy.deepcopy(self.scenarios[0])
        malformed_legacy["safe_actions"] = "guess"

        malformed_guided = copy.deepcopy(self.guided)
        for action in malformed_guided["actions"]:
            if action["kind"] == "unsafe":
                action["kind"] = "premature"

        legacy_errors = validate_scenarios([malformed_legacy], self.training_paths)
        guided_errors = validate_scenarios([malformed_guided], self.training_paths)

        self.assertTrue(
            any("field safe_actions must be a non-empty list" in error for error in legacy_errors)
        )
        self.assertTrue(
            any("must define a unsafe action" in error for error in guided_errors)
        )


if __name__ == "__main__":
    unittest.main()
