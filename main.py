#!/usr/bin/env python3
"""CLI entry point for the CertiFlow multi-agent orchestrator."""

import argparse
import json
import sys
from pathlib import Path

from orchestrator import (
    AzureAIEngine,
    CuratorAgent,
    EngagementAgent,
    ManagerInsightsAgent,
    PlannerAgent,
    TesterAgent,
)
from safety import sanitize_input, validate_request
from telemetry import log_event

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"


def load_request(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _resolve_request_path(raw_path: str) -> Path:
    request_path = Path(raw_path)
    if not request_path.is_absolute():
        request_path = BASE_DIR / request_path
    return request_path


def _build_foundry_context(track_id: str, fallback_context: str) -> str:
    curator = CuratorAgent(knowledge_base_path=str(DATA_DIR / "foundry_iq.json"))
    try:
        return curator.extract_learning_modules(track_id=track_id)
    except Exception:
        return fallback_context


def _run_pipeline_impl(request: dict) -> dict:
    request = sanitize_input(request)
    validate_request(request)

    log_event("pipeline_start", {"employee_id": request.get("employee_id")})

    employee_id = request.get("employee_id")
    track_id = request.get("track_id")
    employee_profile = request.get("employee_profile", {})
    context_data = _build_foundry_context(track_id, request.get("context_data", "{}"))

    ai_engine = AzureAIEngine()

    planner = PlannerAgent(
        schedule_base_path=str(DATA_DIR / "work_iq.json"),
        fabric_base_path=str(DATA_DIR / "fabric_iq.json"),
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

    engagement = EngagementAgent(
        work_base_path=str(DATA_DIR / "work_iq.json"),
        ai_engine=ai_engine,
    )
    try:
        nudge_json = engagement.generate_nudge(employee_id, employee_profile)
        nudge = json.loads(nudge_json)
    except Exception as e:
        nudge = {"error": str(e)}
        log_event("engagement_error", {"error": str(e)})

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

    manager = ManagerInsightsAgent(
        session_state_path=str(DATA_DIR / "session_state.json"),
        telemetry_path=str(DATA_DIR / "system_telemetry.json"),
        fabric_base_path=str(DATA_DIR / "fabric_iq.json"),
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


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run the CertiFlow multi-agent orchestrator locally",
    )
    parser.add_argument(
        "--request",
        type=str,
        default="sample_request.json",
        help="Path to the JSON request file",
    )
    args = parser.parse_args()

    request_path = _resolve_request_path(args.request)
    if not request_path.is_file():
        print(f"Request file not found: {request_path}", file=sys.stderr)
        sys.exit(1)

    request = sanitize_input(load_request(request_path))

    print(
        "Disclaimer: This demo uses synthetic data only. "
        "No real user data is processed. Outputs should be reviewed by a human."
    )

    try:
        combined = _run_pipeline_impl(request)
    except Exception as e:
        print(f"Pipeline failed: {e}", file=sys.stderr)
        sys.exit(1)

    print(json.dumps(combined, indent=2))


def run_pipeline(request: dict) -> dict:
    """Execute the full orchestration pipeline given a request dict."""
    return _run_pipeline_impl(request)


if __name__ == "__main__":
    main()
