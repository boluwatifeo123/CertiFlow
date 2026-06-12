import json
import os
import shutil
import unittest
from unittest.mock import patch

from orchestrator import run_pipeline_step


class TestSchedulePersistence(unittest.TestCase):
    def setUp(self):
        self.workspace_root = os.path.abspath(os.path.dirname(__file__))
        self.telemetry_path = os.path.join(self.workspace_root, "data", "system_telemetry.json")
        self.telemetry_backup = os.path.join(self.workspace_root, "data", "system_telemetry.json.bak")
        shutil.copyfile(self.telemetry_path, self.telemetry_backup)

    def tearDown(self):
        if os.path.exists(self.telemetry_backup):
            shutil.copyfile(self.telemetry_backup, self.telemetry_path)
            os.remove(self.telemetry_backup)

    @patch("orchestrator.AzureAIEngine.__init__", lambda self: None)
    @patch("orchestrator.AzureAIEngine.ask_llm")
    def test_generate_schedule_persists_modules_schedule(self, mock_ask_llm):
        mock_ask_llm.return_value = "INVALID JSON"

        run_pipeline_step("EMP-001", "GENERATE_SCHEDULE")

        with open(self.telemetry_path, "r", encoding="utf-8") as f:
            telemetry = json.load(f)

        employee_data = telemetry.get("employees", {}).get("EMP-001", {})
        self.assertIn("schedule", employee_data)

        schedule = employee_data["schedule"].get("weekly_learning_schedule")
        self.assertIsInstance(schedule, dict)

        modules_schedule = schedule.get("modules_schedule")
        self.assertIsInstance(modules_schedule, list)
        self.assertGreater(len(modules_schedule), 0)

        first_module = modules_schedule[0]
        self.assertIn("module_id", first_module)
        self.assertIn("name", first_module)
        self.assertIn("scheduled_hours", first_module)


if __name__ == "__main__":
    unittest.main()
