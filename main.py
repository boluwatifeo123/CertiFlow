#!/usr/bin/env python3
"""Entry point for the CertiFlow multi‑agent orchestrator.

This script wires together the core agents defined in ``orchestrator.py``
and provides a simple command‑line interface for local testing.

It demonstrates the high‑level flow:

1. Load a JSON request describing the employee and certification track.
2. Initialise the Azure AI engine (or a mock when environment variables are missing).
3. Invoke the Planner, Engagement, Tester and Manager Insight agents in order.
4. Print the combined results as JSON.

The implementation is deliberately lightweight – it uses the existing agent
classes without requiring real Azure resources.  When the required Azure
environment variables are not set, the ``AzureAIEngine`` fallback will raise
a clear error, prompting the user to populate a ``.env`` file.
"""

import argparse
import json
import os
import sys
from pathlib import Path

# Import agent classes and helper functions from orchestrator.py
from orchestrator import (
    AzureAIEngine,
    PlannerAgent,
    EngagementAgent,
    TesterAgent,
    ManagerInsightsAgent,
)

from safety import validate_request
from telemetry import log_event

def load_request(path: Path) -> dict:
    """Load a JSON request file.

    The request must contain at least:
    - ``employee_id`` (str)
    - ``track_id`` (str)
    - ``employee_profile`` (dict) – optional but used by some agents
    """
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run the CertiFlow multi‑agent orchestrator locally"
    )
    parser.add_argument(
        "--request",
        type=str,
        default="sample_request.json",
        help="Path to the JSON request file",
    )
    args = parser.parse_args()

    request_path = Path(args.request)
    if not request_path.is_file():
        print(f"❌ Request file not found: {request_path}", file=sys.stderr)
        sys.exit(1)

    request = load_request(request_path)
    employee_id = request.get("employee_id")
    track_id = request.get("track_id")
    employee_profile = request.get("employee_profile", {})
    context_data = request.get("context_data", "{}")  # JSON string of modules etc.

    # Initialise the Azure AI engine – it will raise if required env vars are missing.
    try:
        ai_engine = AzureAIEngine()
    except Exception as e:
        print(f"❌ Azure AI Engine initialization failed: {e}", file=sys.stderr)
        sys.exit(1)

    # ---------------------------------------------------------------------
    # Planner – generate a study schedule
    # ---------------------------------------------------------------------
    planner = PlannerAgent(
        schedule_base_path="./data/schedule.json",  # placeholder path
        fabric_base_path="./data/fabric.json",    # placeholder path
        ai_engine=ai_engine,
    )
    try:
        schedule_json = planner.generate_ai_schedule(
            employee_id=employee_id,
            context_data=context_data,
            employee_profile=employee_profile,
        )
        schedule = json.loads(schedule_json)
    except Exception as e:
        print(f"⚠️ Planner failed: {e}", file=sys.stderr)
        schedule = {"error": str(e)}

    # ---------------------------------------------------------------------
    # Engagement – generate a nudge/reminder for the employee
    # ---------------------------------------------------------------------
    engagement = EngagementAgent(
        work_base_path="./data/work.json",  # placeholder path
        ai_engine=ai_engine,
    )
    try:
        nudge_json = engagement.generate_nudge(employee_id, employee_profile)
        nudge = json.loads(nudge_json)
    except Exception as e:
        print(f"⚠️ Engagement failed: {e}", file=sys.stderr)
        nudge = {"error": str(e)}

    # ---------------------------------------------------------------------
    # Tester – generate a quiz and evaluate it (using placeholder answers)
    # ---------------------------------------------------------------------
    tester = TesterAgent(ai_engine=ai_engine)
    try:
        quiz_json = tester.generate_quiz(
            foundry_context=context_data,
            module_name="Sample Module",
        )
        # For a quick demo we supply empty answers – the agent will still return a payload.
        performance_json = tester.evaluate_performance(
            quiz_json=quiz_json,
            user_answers="{}",
            foundry_context=context_data,
        )
        performance = json.loads(performance_json)
    except Exception as e:
        print(f"⚠️ Tester failed: {e}", file=sys.stderr)
        performance = {"error": str(e)}

    # ---------------------------------------------------------------------
    # Manager Insights – produce a dashboard summary
    # ---------------------------------------------------------------------
    manager = ManagerInsightsAgent(
        session_state_path="./data/session_state.json",
        telemetry_path="./data/telemetry.json",
        fabric_base_path="./data/fabric.json",
        ai_engine=ai_engine,
    )
    try:
        dashboard_json = manager.generate_dashboard()
        dashboard = json.loads(dashboard_json)
    except Exception as e:
        print(f"⚠️ Manager Insights failed: {e}", file=sys.stderr)
        dashboard = {"error": str(e)}

    # ---------------------------------------------------------------------
    # Combine results and output
    # ---------------------------------------------------------------------
    combined = {
        "request": request,
        "schedule": schedule,
        "nudge": nudge,
        "performance": performance,
        "dashboard": dashboard,
    }

    print(json.dumps(combined, indent=2))


if __name__ == "__main__":
    main()

# -------------------------------------------------------------
# Pipeline callable for programmatic use (used by Flask demo server)
# -------------------------------------------------------------
import json
from safety import validate_request
from telemetry import log_event

def run_pipeline(request: dict) -> dict:
    """Execute the full orchestration pipeline given a request dict.
    Returns a dict with combined results.
    """
    # Safety validation
    validate_request(request)

    log_event("pipeline_start", {"employee_id": request.get("employee_id")})

    employee_id = request.get("employee_id")
    track_id = request.get("track_id")
    employee_profile = request.get("employee_profile", {})
    context_data = request.get("context_data", "{}")

    # Initialise the Azure AI engine – it will raise if required env vars are missing.
    try:
        ai_engine = AzureAIEngine()
    except Exception as e:
        raise RuntimeError(f"Azure AI Engine initialization failed: {e}")

    # Planner – generate a study schedule
    planner = PlannerAgent(
        schedule_base_path="./data/schedule.json",
        fabric_base_path="./data/fabric.json",
        ai_engine=ai_engine,
    )
    try:
        schedule_json = planner.generate_ai_schedule(
            employee_id=employee_id,
            context_data=context_data,
            employee_profile=employee_profile,
        )
        schedule = json.loads(schedule_json)
    except Exception as e:
        schedule = {"error": str(e)}
        log_event("planner_error", {"error": str(e)})

    # Engagement – generate a nudge/reminder for the employee
    engagement = EngagementAgent(
        work_base_path="./data/work.json",
        ai_engine=ai_engine,
    )
    try:
        nudge_json = engagement.generate_nudge(employee_id, employee_profile)
        nudge = json.loads(nudge_json)
    except Exception as e:
        nudge = {"error": str(e)}
        log_event("engagement_error", {"error": str(e)})

    # Tester – generate a quiz and evaluate it (using placeholder answers)
    tester = TesterAgent(ai_engine=ai_engine)
    try:
        quiz_json = tester.generate_quiz(
            foundry_context=context_data,
            module_name="Sample Module",
        )
        performance_json = tester.evaluate_performance(
            quiz_json=quiz_json,
            user_answers="{}",
            foundry_context=context_data,
        )
        performance = json.loads(performance_json)
    except Exception as e:
        performance = {"error": str(e)}
        log_event("tester_error", {"error": str(e)})

    # Manager Insights – produce a dashboard summary
    manager = ManagerInsightsAgent(
        session_state_path="./data/session_state.json",
        telemetry_path="./data/telemetry.json",
        fabric_base_path="./data/fabric.json",
        ai_engine=ai_engine,
    )
    try:
        dashboard_json = manager.generate_dashboard()
        dashboard = json.loads(dashboard_json)
    except Exception as e:
        dashboard = {"error": str(e)}
        log_event("manager_error", {"error": str(e)})

    combined = {
        "request": request,
        "schedule": schedule,
        "nudge": nudge,
        "performance": performance,
        "dashboard": dashboard,
    }

    log_event("pipeline_end", {"status": "success"})
    return combined
