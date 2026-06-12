import os
import json
import re
import sys
from copy import deepcopy
from typing import Any, Optional

try:
    from dotenv import load_dotenv
except ImportError:
    def load_dotenv(*args, **kwargs):
        return None

try:
    from azure.identity import DefaultAzureCredential
    from azure.ai.projects import AIProjectClient
except ImportError:
    DefaultAzureCredential = None
    AIProjectClient = None

load_dotenv()

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def _load_json_file(path: str) -> Any:
    with open(path, "r", encoding="utf-8-sig") as f:
        return json.load(f)


def _extract_json_payload(raw_text: str) -> Any:
    """
    Extract a JSON object or array from model output.
    Handles common cases like code fences and extra explanatory text.
    """
    text = raw_text.strip()

    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text)

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        object_start = text.find("{")
        array_start = text.find("[")
        candidates = [idx for idx in (object_start, array_start) if idx != -1]
        if not candidates:
            raise

        start = min(candidates)
        end = max(text.rfind("}"), text.rfind("]"))
        if end <= start:
            raise

        return json.loads(text[start : end + 1])


def _parse_model_json(raw_text: str, fallback_label: str) -> dict:
    """
    Parse model output into JSON, but never let a bad response break the workflow.
    If parsing fails, return a structured error payload that includes the raw text.
    """
    try:
        parsed = _extract_json_payload(raw_text)
        if isinstance(parsed, dict):
            return parsed
        return {"result": parsed}
    except Exception as e:
        return {
            "verdict": "FAILED",
            "feedback": f"{fallback_label} could not be parsed as JSON: {e}",
            "raw_response": raw_text,
        }


def _json_schema_response_format(name: str, schema: dict) -> dict:
    return {
        "type": "json_schema",
        "json_schema": {
            "name": name,
            "strict": True,
            "schema": schema,
        },
    }

class AzureAIEngine:
    """Initializes and manages the cloud control connection to Azure AI Studio."""
    def __init__(self):
        self.endpoint = os.getenv("AZURE_AI_PROJECT_ENDPOINT")
        self.model_deployment = os.getenv("AZURE_AI_MODEL_DEPLOYMENT")

        if DefaultAzureCredential is None or AIProjectClient is None:
            raise RuntimeError("Azure SDK imports are unavailable in this environment.")

        if not self.endpoint or not self.model_deployment:
            raise ValueError("❌ Error: Missing Azure AI environment variables in .env")

        self.credential = DefaultAzureCredential()
        self.project_client = AIProjectClient(
            endpoint=self.endpoint,
            credential=self.credential
        )

    def ask_llm(
        self,
        system_prompt: str,
        user_prompt: str,
        response_format: Optional[dict] = None,
    ) -> str:
        try:
            openai_client = self.project_client.get_openai_client()
            request_kwargs = {
                "model": self.model_deployment,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                "temperature": 0.2,
            }
            if response_format is not None:
                request_kwargs["response_format"] = response_format

            response = openai_client.chat.completions.create(**request_kwargs)
            return response.choices[0].message.content
        except Exception as e:
            print(f"💥 Azure AI Inference Error: {e}")
            return "ERROR: Inference failure."


class CuratorAgent:
    def __init__(self, knowledge_base_path: str):
        self.knowledge_base_path = knowledge_base_path

    def extract_learning_modules(self, track_id: str) -> str:
        data = _load_json_file(self.knowledge_base_path)
        for track in data.get("certification_tracks", []):
            if track.get("track_id") == track_id:
                retrieval_trace = {
                    "lookup_target": track_id,
                    "matched_track_id": track.get("track_id"),
                    "matched_title": track.get("title"),
                    "module_count": len(track.get("modules", [])),
                    "module_ids": [module.get("module_id") for module in track.get("modules", [])],
                }
                return json.dumps(
                    {
                        "track_id": track.get("track_id"),
                        "track_title": track.get("title"),
                        "modules": track.get("modules", []),
                        "retrieval_trace": retrieval_trace,
                    }
                )
        raise ValueError(f"Track '{track_id}' was not found in {self.knowledge_base_path}")


class StudyPlanGenerator:
    """Generates capability-aware, workload-balanced study schedules using Fabric IQ and Work IQ context."""
    def __init__(self, schedule_base_path: str, fabric_base_path: str, ai_engine: AzureAIEngine):
        self.schedule_base_path = schedule_base_path
        self.fabric_base_path = fabric_base_path
        self.ai_engine = ai_engine

    def _extract_work_constraints(self, employee_id: str) -> dict:
        """Extract busy blocks and preferred learning windows from Work IQ."""
        work_data = _load_json_file(self.schedule_base_path)
        schedule = next(
            (item for item in work_data.get("schedules", []) if item.get("employee_id") == employee_id),
            {},
        )
        return {
            "busy_blocks": schedule.get("weekly_busy_blocks", []),
            "learning_windows": schedule.get("preferred_learning_windows", []),
        }

    def _extract_fabric_context(self, employee_profile: dict) -> dict:
        """Extract semantic business context from Fabric IQ."""
        return {
            "role": employee_profile.get("role"),
            "department": employee_profile.get("department"),
            "passing_threshold": employee_profile.get("passing_score_threshold", 75),
        }

    def _calculate_available_slots(self, work_constraints: dict) -> list[dict]:
        """Compute learnable time blocks by filtering busy blocks from work calendar."""
        busy_blocks = {block.get("day"): block for block in work_constraints.get("busy_blocks", [])}
        learning_windows = work_constraints.get("learning_windows", [])
        available = []
        for window in learning_windows:
            day = window.get("day")
            if day not in busy_blocks:
                available.append(window)
        return available

    def _build_fallback_schedule(self, employee_id: str, track_id: str, role: str, modules: list[dict], available_slots: list[dict]) -> dict:
        """Build a simple deterministic fallback schedule when AI output is missing or incomplete."""
        if not modules:
            return {
                "employee_id": employee_id,
                "track_id": track_id,
                "modules_schedule": [],
            }

        if not available_slots:
            # No preferred windows; allocate flexible time blocks
            available_slots = [
                {"day": "Monday", "start_time": "09:00", "end_time": "11:00"},
                {"day": "Wednesday", "start_time": "09:00", "end_time": "11:00"},
                {"day": "Friday", "start_time": "09:00", "end_time": "11:00"},
            ]

        schedule = []
        slot_index = 0
        for module in modules:
            module_id = module.get("module_id", "UNKNOWN")
            name = module.get("name", "Unnamed Module")
            slot = available_slots[slot_index % len(available_slots)]
            schedule.append(
                {
                    "module_id": module_id,
                    "name": name,
                    "scheduled_hours": [
                        {
                            "day": slot.get("day", "TBD"),
                            "start_time": slot.get("start_time", "09:00"),
                            "end_time": slot.get("end_time", "11:00"),
                        }
                    ],
                    "notes": f"Fallback schedule for {role}: allocated to {slot.get('day', 'TBD')} "
                              f"during {slot.get('start_time', '09:00')}–{slot.get('end_time', '11:00')}.",
                }
            )
            slot_index += 1

        return {
            "employee_id": employee_id,
            "track_id": track_id,
            "modules_schedule": schedule,
        }

    def _validate_schedule_payload(self, schedule: Any) -> bool:
        if not isinstance(schedule, dict):
            return False

        modules = schedule.get("modules_schedule")
        if not isinstance(modules, list) or not modules:
            return False

        for module in modules:
            if not isinstance(module, dict):
                return False
            if not module.get("module_id") or not module.get("name"):
                return False
            scheduled_hours = module.get("scheduled_hours")
            if not isinstance(scheduled_hours, list) or not scheduled_hours:
                return False
            for block in scheduled_hours:
                if not isinstance(block, dict):
                    return False
                if not all(
                    isinstance(block.get(field), str) and block.get(field).strip()
                    for field in ("day", "start_time", "end_time")
                ):
                    return False

        return True

    def _extract_schedule_from_parsed(self, parsed_response: Any) -> Optional[dict]:
        if not isinstance(parsed_response, dict):
            return None

        candidates = [
            parsed_response.get("weekly_learning_schedule"),
            parsed_response.get("schedule"),
            parsed_response.get("weekly_schedule"),
        ]
        for candidate in candidates:
            if self._validate_schedule_payload(candidate):
                return candidate

        result = parsed_response.get("result")
        if isinstance(result, dict):
            return self._extract_schedule_from_parsed(result)
        if isinstance(result, list):
            for item in result:
                if self._validate_schedule_payload(item):
                    return item
                if isinstance(item, dict):
                    nested = self._extract_schedule_from_parsed(item)
                    if nested is not None:
                        return nested

        for value in parsed_response.values():
            if self._validate_schedule_payload(value):
                return value

        return None

    def _finalize_ai_schedule(self, schedule: dict, employee_id: str, track_id: str) -> dict:
        schedule = dict(schedule)
        schedule["employee_id"] = schedule.get("employee_id", employee_id)
        schedule["track_id"] = schedule.get("track_id", track_id)
        return schedule

    def generate_ai_schedule(self, employee_id: str, context_data: str, employee_profile: dict) -> str:
        """Generate a constraint-aware, AI-reasoned study schedule grounded in Foundry/Fabric/Work IQ."""
        work_constraints = self._extract_work_constraints(employee_id)
        fabric_context = self._extract_fabric_context(employee_profile)
        available_slots = self._calculate_available_slots(work_constraints)
        context_payload = json.loads(context_data) if isinstance(context_data, str) else context_data

        system_instruction = (
            "You are the Study Plan Generator for CertiFlow.\n"
            "You must ground all scheduling decisions in the provided Foundry IQ module metadata (fields may include: module_id, name, estimated_hours_required, difficulty, prerequisites, syllabus_topics).\n"
            "Generate a weekly learning schedule that meets these rules:\n"
            "1) Respect Work IQ busy blocks: never schedule during busy blocks.\n"
            "2) Use only preferred learning windows when available; if none exist, choose early-week flexible windows.\n"
            "3) Balance estimated_hours_required across available windows so no single day is overloaded.\n"
            "4) Sequence modules to satisfy prerequisites (if module A lists module B as a prerequisite, schedule B earlier).\n"
            "5) Prefer shorter modules earlier to build momentum; place higher-difficulty modules when the employee's preferred windows are longest.\n"
            "6) For each scheduled module include: module_id, name, scheduled_hours (list with day,start_time,end_time), and an optional notes field explaining the grounding decision.\n"
            "If any required field is missing, synthesize reasonable defaults but indicate them in the notes.\n"
            "Return only valid JSON that matches the supplied schema. Do not include markdown, headings, or extraneous text. If you cannot produce a valid schedule, return an explicit empty modules_schedule array (the orchestrator will use a deterministic fallback)."
        )

        response_schema = _json_schema_response_format(
            "certiflow_weekly_schedule",
            {
                "type": "object",
                "properties": {
                    "weekly_learning_schedule": {
                        "type": "object",
                        "properties": {
                            "employee_id": {"type": "string"},
                            "track_id": {"type": "string"},
                            "modules_schedule": {
                                "type": "array",
                                "minItems": 1,
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "module_id": {"type": "string"},
                                        "name": {"type": "string"},
                                        "scheduled_hours": {
                                            "type": "array",
                                            "minItems": 1,
                                            "items": {
                                                "type": "object",
                                                "properties": {
                                                    "day": {"type": "string"},
                                                    "start_time": {"type": "string"},
                                                    "end_time": {"type": "string"},
                                                },
                                                "required": ["day", "start_time", "end_time"],
                                                "additionalProperties": False,
                                            },
                                        },
                                    },
                                    "required": ["module_id", "name", "scheduled_hours"],
                                    "additionalProperties": False,
                                },
                            },
                        },
                        "required": ["employee_id", "track_id", "modules_schedule"],
                        "additionalProperties": False,
                    }
                },
                "required": ["weekly_learning_schedule"],
                "additionalProperties": False,
            },
        )

        user_input = (
            f"Employee ID: {employee_id}\n"
            f"Fabric IQ Role Context: {json.dumps(fabric_context)}\n"
            f"Learning Modules (Foundry IQ): {context_data}\n"
            f"Work Calendar Constraints: Busy blocks: {json.dumps(work_constraints.get('busy_blocks', []))}\n"
            f"Preferred Learning Windows: {json.dumps(available_slots)}\n"
            f"\nTask: Map modules to available learning windows, respecting all constraints and role context."
        )

        ai_response = self.ai_engine.ask_llm(system_instruction, user_input, response_format=response_schema)
        parsed_response = _parse_model_json(ai_response, "Study plan generation")

        schedule = self._extract_schedule_from_parsed(parsed_response)
        track_id = json.loads(context_data).get("track_id", "UNKNOWN") if isinstance(context_data, str) else "UNKNOWN"

        if schedule is None:
            fallback_schedule = self._build_fallback_schedule(
                employee_id,
                track_id,
                fabric_context.get("role", "UNKNOWN"),
                json.loads(context_data).get("modules", []),
                available_slots,
            )
            return json.dumps({"weekly_learning_schedule": fallback_schedule})

        schedule = self._finalize_ai_schedule(schedule, employee_id, track_id)
        return json.dumps({"weekly_learning_schedule": schedule})


class PlannerAgent:
    """Orchestrates study plan generation using StudyPlanGenerator."""
    def __init__(self, schedule_base_path: str, fabric_base_path: str, ai_engine: AzureAIEngine):
        self.schedule_base_path = schedule_base_path
        self.fabric_base_path = fabric_base_path
        self.ai_engine = ai_engine
        self.plan_generator = StudyPlanGenerator(schedule_base_path, fabric_base_path, ai_engine)

    def generate_ai_schedule(self, employee_id: str, context_data: str, employee_profile: dict) -> str:
        """Generate AI schedule delegating to StudyPlanGenerator."""
        return self.plan_generator.generate_ai_schedule(employee_id, context_data, employee_profile)
    

class TesterAgent:
    def __init__(self, ai_engine: AzureAIEngine):
        self.ai_engine = ai_engine

    @staticmethod
    def _normalize_question_id(question_id: Any) -> str:
        text = str(question_id).strip().upper()
        if text.startswith("Q"):
            return text
        return f"Q{text}"

    @staticmethod
    def _parse_submission_answers(user_answers: str) -> dict[str, Any]:
        payload = _extract_json_payload(user_answers)
        if not isinstance(payload, dict):
            raise ValueError("Submission payload must be a JSON object.")

        answers = payload.get("submission", [])
        if not isinstance(answers, list):
            raise ValueError("Submission payload must contain a list under 'submission'.")

        answer_map: dict[str, Any] = {}
        for item in answers:
            if not isinstance(item, dict):
                continue
            question_id = item.get("question_id")
            if question_id is None:
                continue
            answer_map[TesterAgent._normalize_question_id(question_id)] = item.get("selected_choice")
        return answer_map

    @staticmethod
    def _build_study_recommendation(module_name: str, question_text: str, is_correct: bool) -> str:
        if is_correct:
            return f"Correct. Keep reinforcing {module_name} and move on to the next objective."
        return (
            f"Review {module_name} and re-read the section that addresses: {question_text}. "
            "Then retry the question after you can explain the rule in your own words."
        )

    def generate_quiz(self, foundry_context: str, module_name: str) -> str:
        system_instruction = (
            "You are the Assessment Agent for CertiFlow.\n"
            "Generate exactly two quiz questions grounded only in the provided syllabus.\n"
            "Return only JSON that matches the supplied schema.\n"
            "Do not add markdown, extra keys, explanations, or prose."
        )
        response_schema = _json_schema_response_format(
            "certiflow_quiz",
            {
                "type": "object",
                "properties": {
                    "module": {"type": "string"},
                    "quiz": {
                        "type": "array",
                        "minItems": 2,
                        "maxItems": 2,
                        "items": {
                            "type": "object",
                            "properties": {
                                "question_id": {"type": "string"},
                                "question": {"type": "string"},
                                "options": {
                                    "type": "array",
                                    "minItems": 4,
                                    "maxItems": 4,
                                    "items": {"type": "string"},
                                },
                                "correct_answer": {"type": "string"},
                            },
                            "required": ["question_id", "question", "options", "correct_answer"],
                            "additionalProperties": False,
                        },
                    }
                },
                "required": ["module", "quiz"],
                "additionalProperties": False,
            },
        )
        user_input = f"Context: {foundry_context}\nModule: {module_name}"
        return self.ai_engine.ask_llm(system_instruction, user_input, response_format=response_schema)

    def evaluate_performance(self, quiz_json: str, user_answers: str, foundry_context: str) -> str:
        quiz_payload = _extract_json_payload(quiz_json)
        if not isinstance(quiz_payload, dict):
            raise ValueError("Quiz payload must be a JSON object.")

        answer_map = self._parse_submission_answers(user_answers)
        quiz_questions = quiz_payload.get("quiz", [])
        if not isinstance(quiz_questions, list):
            raise ValueError("Quiz payload must contain a list under 'quiz'.")

        verification_trace = []
        wrong_items = []

        for question in quiz_questions:
            if not isinstance(question, dict):
                continue

            question_id = self._normalize_question_id(question.get("question_id"))
            selected_choice = answer_map.get(question_id)
            correct_answer = question.get("correct_answer")
            is_correct = selected_choice == correct_answer
            module_name = quiz_payload.get("module", "the current module")
            study_recommendation = self._build_study_recommendation(
                module_name=module_name,
                question_text=question.get("question", ""),
                is_correct=is_correct,
            )

            trace_item = {
                "question_id": question_id,
                "selected_choice": selected_choice,
                "correct_answer": correct_answer,
                "status": "correct" if is_correct else "incorrect",
                "study_recommendation": study_recommendation,
            }
            verification_trace.append(trace_item)

            if not is_correct:
                wrong_items.append(
                    {
                        "question_id": question_id,
                        "question": question.get("question", ""),
                        "selected_choice": selected_choice,
                        "correct_answer": correct_answer,
                    }
                )

        score_percentage = round((len(quiz_questions) and sum(1 for item in verification_trace if item["status"] == "correct") or 0) / max(len(quiz_questions), 1) * 100)
        verdict = "PASSED" if score_percentage == 100 else "FAILED"

        reasoning_trace = []
        if wrong_items:
            system_instruction = (
                "You are the Critic node in the CertiFlow verification loop.\n"
                "Explain why each wrong answer is incorrect using only the supplied Foundry IQ context.\n"
                "Return only JSON matching the supplied schema.\n"
                "Keep each explanation brief, specific, and instructionally useful."
            )
            response_schema = _json_schema_response_format(
                "certiflow_wrong_answer_analysis",
                {
                    "type": "object",
                    "properties": {
                        "analyses": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "question_id": {"type": "string"},
                                    "why_wrong": {"type": "string"},
                                    "syllabus_focus": {"type": "string"},
                                    "corrective_action": {"type": "string"},
                                    "study_recommendation": {"type": "string"},
                                },
                                "required": ["question_id", "why_wrong", "syllabus_focus", "corrective_action", "study_recommendation"],
                                "additionalProperties": False,
                            },
                        }
                    },
                    "required": ["analyses"],
                    "additionalProperties": False,
                },
            )
            user_input = (
                f"Foundry IQ context:\n{foundry_context}\n\n"
                f"Quiz:\n{json.dumps(quiz_payload)}\n\n"
                f"Wrong answers needing critique:\n{json.dumps(wrong_items)}\n\n"
                "Cross-reference the wrong answers against the syllabus context and explain the knowledge gap."
            )
            critique_json = self.ai_engine.ask_llm(system_instruction, user_input, response_format=response_schema)
            critique_data = _parse_model_json(critique_json, "Critique response")
            reasoning_trace = critique_data.get("analyses", []) if isinstance(critique_data, dict) else []

        feedback = "All answers aligned with the quiz template and syllabus context." if verdict == "PASSED" else "One or more answers need review against the cited syllabus context."

        final_payload = {
            "grading_step_verified": True,
            "score_percentage": score_percentage,
            "verdict": verdict,
            "feedback": feedback,
            "verification_trace": verification_trace,
            "reasoning_trace": reasoning_trace,
            "wrong_answer_count": len(wrong_items),
        }
        return json.dumps(final_payload)


class EngagementAgent:
    def __init__(self, work_base_path: str, ai_engine: AzureAIEngine):
        self.work_base_path = work_base_path
        self.ai_engine = ai_engine

    def generate_nudge(self, employee_id: str, employee_profile: dict) -> str:
        work_data = _load_json_file(self.work_base_path)
        schedule_profile = next(
            (item for item in work_data.get("schedules", []) if item.get("employee_id") == employee_id),
            {},
        )

        system_instruction = (
            "You are the Engagement Agent for CertiFlow.\n"
            "Generate a concise, contextual reminder for a learner using only the provided Work IQ data.\n"
            "Pick a low-disruption time window and explain why it is a good moment.\n"
            "Return only JSON matching the supplied schema."
        )

        response_schema = _json_schema_response_format(
            "certiflow_engagement_nudge",
            {
                "type": "object",
                "properties": {
                    "employee_id": {"type": "string"},
                    "best_window": {
                        "type": "object",
                        "properties": {
                            "day": {"type": "string"},
                            "start_time": {"type": "string"},
                            "end_time": {"type": "string"},
                        },
                        "required": ["day", "start_time", "end_time"],
                        "additionalProperties": False,
                    },
                    "message": {"type": "string"},
                    "reason": {"type": "string"},
                },
                "required": ["employee_id", "best_window", "message", "reason"],
                "additionalProperties": False,
            },
        )

        user_input = (
            f"Employee profile: {json.dumps(employee_profile)}\n"
            f"Work IQ schedule: {json.dumps(schedule_profile)}\n"
            "Choose the best low-friction reminder window and draft a supportive nudge."
        )
        return self.ai_engine.ask_llm(system_instruction, user_input, response_format=response_schema)


class ManagerInsightsAgent:
    def __init__(self, session_state_path: str, telemetry_path: str, fabric_base_path: str, ai_engine: AzureAIEngine):
        self.session_state_path = session_state_path
        self.telemetry_path = telemetry_path
        self.fabric_base_path = fabric_base_path
        self.ai_engine = ai_engine

    def _load_session_state(self) -> dict:
        if os.path.exists(self.session_state_path):
            return _load_json_file(self.session_state_path)
        return {"employees": {}}

    def _load_telemetry(self) -> dict:
        if os.path.exists(self.telemetry_path):
            return _load_json_file(self.telemetry_path)
        return {"employees": {}, "manager_insights": {}, "inspection_log": []}

    def _load_role_lookup(self) -> dict[str, str]:
        fabric_data = _load_json_file(self.fabric_base_path)
        lookup = {}
        for employee in fabric_data.get("employees", []):
            employee_id = employee.get("employee_id")
            if employee_id:
                lookup[employee_id] = employee.get("role", "Unknown")
        return lookup

    def _display_stage(self, stage: str, active_quiz: bool, submission_count: int) -> str:
        if submission_count > 0 or stage == "COMPLETED_ASSESSMENT":
            return "assessment_done"
        if active_quiz or stage == "QUIZ_PENDING":
            return "quiz_pending"
        if stage == "SCHEDULED":
            return "schedule_ready"
        if stage == "INITIALIZED":
            return "initialized"
        return stage.lower()

    def _build_employee_rows(self, employees: dict, telemetry_employees: dict, role_lookup: dict[str, str]) -> list[dict]:
        rows = []
        for employee_id, record in employees.items():
            telemetry_record = telemetry_employees.get(employee_id, {})
            submissions = telemetry_record.get("quiz_submissions", [])
            schedule = telemetry_record.get("schedule")
            active_quiz = record.get("active_quiz")
            stage = record.get("current_stage", "Unknown")
            progress = self._estimate_progress(stage, bool(schedule), bool(active_quiz), len(submissions))
            stage_label = self._display_stage(stage, bool(active_quiz), len(submissions))

            rows.append(
                {
                    "employee_id": employee_id,
                    "role": role_lookup.get(employee_id, record.get("role", "Unknown")),
                    "track": record.get("assigned_track", "Unknown"),
                    "stage": stage,
                    "stage_label": stage_label,
                    "has_schedule": bool(schedule),
                    "has_quiz": bool(active_quiz),
                    "submissions": len(submissions),
                    "progress_percentage": progress,
                }
            )
        return rows

    def _estimate_progress(self, stage: str, has_schedule: bool, has_quiz: bool, submission_count: int) -> int:
        if stage == "COMPLETED_ASSESSMENT" or submission_count > 0:
            return 100
        if stage == "QUIZ_PENDING" or has_quiz:
            return 70
        if stage == "SCHEDULED" or has_schedule:
            return 35
        if stage == "IDLE":
            return 10 if has_schedule else 0
        return 0

    def generate_dashboard(self) -> dict:
        session_state = self._load_session_state()
        telemetry_state = self._load_telemetry()
        role_lookup = self._load_role_lookup()
        employees = session_state.get("employees", {})
        telemetry_employees = telemetry_state.get("employees", {})
        rows = self._build_employee_rows(employees, telemetry_employees, role_lookup)

        team_size = len(rows)
        scheduled_count = sum(1 for row in rows if row["has_schedule"])
        quiz_pending_count = sum(1 for row in rows if row["stage_label"] == "quiz_pending")
        quiz_completed_count = sum(1 for row in rows if row["submissions"] > 0)
        assessment_done_count = sum(1 for row in rows if row["stage_label"] == "assessment_done")
        average_progress = round(sum(row["progress_percentage"] for row in rows) / team_size) if team_size else 0
        risk_score = min(100, max(0, round(100 - average_progress)))

        if risk_score >= 70:
            risk_level = "HIGH"
        elif risk_score >= 35:
            risk_level = "MEDIUM"
        else:
            risk_level = "LOW"

        risk_flags = []
        if scheduled_count < team_size:
            risk_flags.append("Not every learner has a schedule yet.")
        if quiz_pending_count > 0:
            risk_flags.append("Some learners have quizzes waiting for answers.")
        if team_size and assessment_done_count == 0:
            risk_flags.append("No assessment submissions have been recorded.")
        if average_progress < 50 and team_size:
            risk_flags.append("Average learner progress is still below the halfway mark.")
        if not risk_flags:
            risk_flags.append("No major delivery risks detected in the current snapshot.")

        recommended_actions = [
            "Prioritize learners without schedules.",
            "Use engagement nudges during low-disruption Work IQ windows.",
            "Review assessment completion weekly.",
        ]

        completed_count = sum(1 for row in rows if row["progress_percentage"] == 100)
        top_gaps = []
        if team_size and scheduled_count < team_size:
            top_gaps.append("Scheduling gaps remain")
        if team_size and quiz_pending_count > 0:
            top_gaps.append("Quiz answers are still pending")
        if team_size and completed_count == 0:
            top_gaps.append("No learners have completed the full loop yet")

        system_instruction = (
            "You are the Manager Insights reasoning node for CertiFlow.\n"
            "Use the provided synthetic metrics to synthesize an executive dashboard narrative.\n"
            "Do not invent data. Return only JSON matching the supplied schema."
        )
        response_schema = _json_schema_response_format(
            "certiflow_manager_dashboard_reasoning",
            {
                "type": "object",
                "properties": {
                    "risk_level": {"type": "string"},
                    "executive_summary": {
                        "type": "object",
                        "properties": {
                            "headline": {"type": "string"},
                            "secondary": {"type": "string"},
                            "trailing": {"type": "string"},
                            "top_gaps": {
                                "type": "array",
                                "items": {"type": "string"},
                            },
                        },
                        "required": ["headline", "secondary", "trailing", "top_gaps"],
                        "additionalProperties": False,
                    },
                    "risk_flags": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "recommended_actions": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "manager_narrative": {"type": "string"},
                },
                "required": ["risk_level", "executive_summary", "risk_flags", "recommended_actions", "manager_narrative"],
                "additionalProperties": False,
            },
        )
        metrics_snapshot = {
            "team_size": team_size,
            "scheduled_count": scheduled_count,
            "quiz_pending_count": quiz_pending_count,
            "quiz_completed_count": quiz_completed_count,
            "assessment_done_count": assessment_done_count,
            "average_progress": average_progress,
            "risk_score": risk_score,
            "risk_level": risk_level,
            "top_gaps": top_gaps,
        }
        reasoning_input = (
            f"Metrics snapshot: {json.dumps(metrics_snapshot)}\n"
            f"Employee rows: {json.dumps(rows)}\n"
            "Synthesize an executive-ready view of the team state."
        )
        reasoning_json = self.ai_engine.ask_llm(system_instruction, reasoning_input, response_format=response_schema)
        reasoning_data = _parse_model_json(reasoning_json, "Manager dashboard reasoning")

        summary = {
            "team_summary": (
                f"{team_size} employee(s) tracked, "
                f"{scheduled_count} scheduled, {quiz_pending_count} quiz pending, "
                f"{quiz_completed_count} quiz completed, {assessment_done_count} assessment done."
            ),
            "team_size": team_size,
            "active_learners": sum(1 for row in rows if row["stage"] in {"SCHEDULED", "QUIZ_PENDING", "COMPLETED_ASSESSMENT"}),
            "average_progress": average_progress,
            "risk_score": risk_score,
            "risk_level": reasoning_data.get("risk_level", risk_level) if isinstance(reasoning_data, dict) else risk_level,
            "risk_flags": reasoning_data.get("risk_flags", risk_flags) if isinstance(reasoning_data, dict) else risk_flags,
            "recommended_actions": reasoning_data.get("recommended_actions", recommended_actions) if isinstance(reasoning_data, dict) else recommended_actions,
            "executive_summary": reasoning_data.get("executive_summary", {
                "headline": f"{average_progress}% average progress across {team_size} learner(s).",
                "secondary": f"Risk is {risk_level.lower()} with a score of {risk_score}/100.",
                "trailing": (
                    f"{completed_count} fully completed, {scheduled_count} scheduled, "
                    f"{quiz_pending_count} quiz pending, {quiz_completed_count} quiz completed, "
                    f"{assessment_done_count} assessment done."
                ),
                "top_gaps": top_gaps or ["No major operational gaps detected."],
            }) if isinstance(reasoning_data, dict) else {
                "headline": f"{average_progress}% average progress across {team_size} learner(s).",
                "secondary": f"Risk is {risk_level.lower()} with a score of {risk_score}/100.",
                "trailing": (
                    f"{completed_count} fully completed, {scheduled_count} scheduled, "
                    f"{quiz_pending_count} quiz pending, {quiz_completed_count} quiz completed, "
                    f"{assessment_done_count} assessment done."
                ),
                "top_gaps": top_gaps or ["No major operational gaps detected."],
            },
            "manager_narrative": reasoning_data.get("manager_narrative", "") if isinstance(reasoning_data, dict) else "",
            "employees": rows,
        }

        return summary

    def render_dashboard(self, dashboard: dict) -> str:
        rows = dashboard.get("employees", [])
        lines = []
        lines.append("=" * 78)
        lines.append("CERTIFLOW MANAGER DASHBOARD")
        lines.append("=" * 78)
        executive = dashboard.get("executive_summary", {})
        lines.append(f"Headline          : {executive.get('headline', 'N/A')}")
        lines.append(f"Status            : {executive.get('secondary', 'N/A')}")
        lines.append(f"Snapshot          : {executive.get('trailing', 'N/A')}")
        lines.append(f"Risk score        : {dashboard.get('risk_score', 0)}/100")
        lines.append(f"Average progress   : {dashboard.get('average_progress', 0)}%")
        lines.append("")
        lines.append(f"Team summary      : {dashboard.get('team_summary', 'N/A')}")
        lines.append(f"Team size         : {dashboard.get('team_size', 0)}")
        lines.append(f"Active learners   : {dashboard.get('active_learners', 0)}")
        lines.append(f"Risk level        : {dashboard.get('risk_level', 'UNKNOWN')}")
        lines.append("")
        lines.append("Executive gaps")
        for gap in executive.get("top_gaps", []):
            lines.append(f"  - {gap}")
        lines.append("")
        lines.append("Risk flags")
        for flag in dashboard.get("risk_flags", []):
            lines.append(f"  - {flag}")
        lines.append("")
        lines.append("Recommended actions")
        for action in dashboard.get("recommended_actions", []):
            lines.append(f"  - {action}")
        lines.append("")
        lines.append("Employee snapshot")
        lines.append(f"{'Employee':<12} {'Role':<28} {'Stage':<20} {'Prog':<6} {'Sched':<6} {'Quiz':<5} {'Subs':<5}")
        lines.append("-" * 78)
        for row in rows:
            lines.append(
                f"{row['employee_id']:<12} {row['role'][:28]:<28} {row['stage_label'][:20]:<20} "
                f"{str(row['progress_percentage']) + '%':<6} {'Y' if row['has_schedule'] else 'N':<6} "
                f"{'Y' if row['has_quiz'] else 'N':<5} {row['submissions']:<5}"
            )
        lines.append("=" * 78)
        return "\n".join(lines)


class CertiFlowOrchestrator:
    """Manages system state transformations across asynchronous workflow boundaries."""
    def __init__(
        self,
        state_file: str = "data/session_state.json",
        telemetry_file: str = "data/system_telemetry.json",
    ):
        self.state_file = state_file
        self.telemetry_file = telemetry_file
        self.state = self._load_state()
        self.telemetry = self._load_telemetry()

    def _load_state(self) -> dict:
        if os.path.exists(self.state_file):
            try:
                with open(self.state_file, "r", encoding="utf-8-sig") as f:
                    return json.load(f)
            except json.JSONDecodeError as e:
                print(f"⚠️ Invalid session state JSON in {self.state_file}: {e}. Resetting to a clean baseline.")
        return {"employees": {}}

    def _load_telemetry(self) -> dict:
        if os.path.exists(self.telemetry_file):
            try:
                with open(self.telemetry_file, "r", encoding="utf-8-sig") as f:
                    return json.load(f)
            except json.JSONDecodeError as e:
                print(f"⚠️ Invalid telemetry JSON in {self.telemetry_file}: {e}. Resetting to a clean baseline.")
        return {"employees": {}, "manager_insights": {}, "inspection_log": []}

    def _ensure_employee_telemetry(self, employee_id: str):
        employees = self.telemetry.setdefault("employees", {})
        if employee_id not in employees:
            employees[employee_id] = {
                "schedule": None,
                "quiz_submissions": [],
                "last_engagement_nudge": None,
            }

    def save_state(self):
        directory = os.path.dirname(self.state_file)
        if directory:
            os.makedirs(directory, exist_ok=True)
        with open(self.state_file, "w", encoding="utf-8") as f:
            json.dump(self.state, f, indent=4)

    def save_telemetry(self):
        directory = os.path.dirname(self.telemetry_file)
        if directory:
            os.makedirs(directory, exist_ok=True)
        with open(self.telemetry_file, "w", encoding="utf-8") as f:
            json.dump(self.telemetry, f, indent=4)

    def _set_telemetry_value(self, employee_id: str, key: str, data: Any):
        self._ensure_employee_telemetry(employee_id)
        self.telemetry["employees"][employee_id][key] = data
        self.save_telemetry()

    def initialize_employee_state(self, employee_id: str, track: str, role: str):
        if employee_id not in self.state["employees"]:
            self.state["employees"][employee_id] = {
                "assigned_track": track,
                "role": role,
                "current_stage": "INITIALIZED",
                "active_quiz": None,
            }
            self.save_state()
        self._ensure_employee_telemetry(employee_id)
        self.save_telemetry()

    def update_stage(self, employee_id: str, stage: str, key: str, data: Any):
        if employee_id not in self.state["employees"]:
            return

        self.state["employees"][employee_id]["current_stage"] = stage
        if key == "active_quiz":
            self.state["employees"][employee_id]["active_quiz"] = data
            self.save_state()
        else:
            self._set_telemetry_value(employee_id, key, data)

    def save_team_insights(self, insights: dict):
        self.telemetry["manager_insights"] = insights
        self.save_telemetry()

    def record_inspection_event(
        self,
        *,
        action: str,
        employee_id: str | None,
        before_state: dict | None,
        after_state: dict | None,
        inputs: dict | None,
        note: str = "",
    ):
        self.telemetry.setdefault("inspection_log", [])
        self.telemetry["inspection_log"].append(
            {
                "action": action,
                "employee_id": employee_id,
                "inputs": inputs or {},
                "before_state": before_state or {},
                "after_state": after_state or {},
                "note": note,
            }
        )
        self.save_telemetry()

    def build_inspection_report(self, include_inspection_log: bool = True) -> dict:
        self.telemetry.setdefault("inspection_log", [])
        report = {
            "state_file": self.state_file,
            "telemetry_file": self.telemetry_file,
            "employee_count": len(self.state.get("employees", {})),
            "employees": deepcopy(self.state.get("employees", {})),
            "telemetry_employees": deepcopy(self.telemetry.get("employees", {})),
            "manager_insights": deepcopy(self.telemetry.get("manager_insights", {})),
        }
        if include_inspection_log:
            report["inspection_log"] = deepcopy(self.telemetry.get("inspection_log", []))
        else:
            report["inspection_log"] = []
        return report

    @staticmethod
    def render_inspection_report(report: dict) -> str:
        lines = []
        lines.append("=" * 78)
        lines.append("CERTIFLOW BACKEND INSPECTION REPORT")
        lines.append("=" * 78)
        lines.append(f"State file       : {report.get('state_file', 'N/A')}")
        lines.append(f"Employee count   : {report.get('employee_count', 0)}")
        lines.append(f"Inspection events: {len(report.get('inspection_log', []))}")
        lines.append("")
        lines.append("Current employees")
        for employee_id, data in report.get("employees", {}).items():
            lines.append(f"- {employee_id}: {data.get('current_stage', 'UNKNOWN')} | {data.get('role', 'Unknown')}")
        lines.append("")
        lines.append("Recent inspection events")
        for event in report.get("inspection_log", [])[-5:]:
            lines.append(f"- Action: {event.get('action')} | Employee: {event.get('employee_id', 'N/A')}")
            lines.append(f"  Inputs: {json.dumps(event.get('inputs', {}))}")
            lines.append(f"  Note  : {event.get('note', '')}")
        lines.append("=" * 78)
        return "\n".join(lines)

    def get_employee_state(self, employee_id: str) -> dict:
        core_state = self.state["employees"].get(employee_id, {})
        telemetry_state = self.telemetry.get("employees", {}).get(employee_id, {})
        merged = dict(core_state)
        merged.update(telemetry_state)
        return merged

    def get_employee_core_state(self, employee_id: str) -> dict:
        return self.state["employees"].get(employee_id, {})

    def get_employee_telemetry(self, employee_id: str) -> dict:
        return self.telemetry.get("employees", {}).get(employee_id, {})


def run_pipeline_step(target_employee_id: str, requested_action: str, target_module: str = None, submission_payload: str = None):
    print(f"\n⚙️ [Orchestrator] Invoking action: '{requested_action}' for {target_employee_id}")
    foundry_iq_path = "data/foundry_iq.json"
    work_iq_path = "data/work_iq.json"
    fabric_iq_path = "data/fabric_iq.json"

    try:
        ai_engine = AzureAIEngine()
        orchestrator = CertiFlowOrchestrator()

        fabric_data = _load_json_file(fabric_iq_path)
        emp_profile = next((e for e in fabric_data.get("employees", []) if e.get("employee_id") == target_employee_id), None)
        if not emp_profile:
            print(f"❌ Employee {target_employee_id} not found.")
            return

        orchestrator.initialize_employee_state(target_employee_id, emp_profile["assigned_track"], emp_profile["role"])
        emp_state = orchestrator.get_employee_state(target_employee_id)
    except Exception as e:
        print(f"❌ Failed to initialize workflow: {e}")
        return

    before_employee_state = json.loads(json.dumps(emp_state))

    # ACTION 1: Generate or refresh schedule
    if requested_action == "GENERATE_SCHEDULE":
        try:
            curator = CuratorAgent(knowledge_base_path=foundry_iq_path)
            foundry_context = curator.extract_learning_modules(track_id=emp_state["assigned_track"])

            planner = PlannerAgent(schedule_base_path=work_iq_path, fabric_base_path=fabric_iq_path, ai_engine=ai_engine)
            ai_schedule = planner.generate_ai_schedule(target_employee_id, foundry_context, emp_profile)
            if ai_schedule.startswith("ERROR:"):
                raise RuntimeError(ai_schedule)
            schedule_data = _extract_json_payload(ai_schedule)

            orchestrator.update_stage(target_employee_id, "SCHEDULED", "schedule", schedule_data)
            orchestrator.record_inspection_event(
                action="GENERATE_SCHEDULE",
                employee_id=target_employee_id,
                before_state=before_employee_state,
                after_state=orchestrator.get_employee_state(target_employee_id),
                inputs={
                    "target_module": target_module,
                    "submission_payload": submission_payload,
                    "employee_profile": emp_profile,
                },
                note="Schedule generated from Foundry IQ + Work IQ + Fabric IQ context with constraint enforcement.",
            )
            print("✅ Schedule generated and committed to persistent state ledger.")
        except Exception as e:
            print(f"❌ Schedule generation failed: {e}")
            return

    # ACTION 2: Generate Quiz
    elif requested_action == "GENERATE_QUIZ":
        if not target_module:
            print("❌ Target module required for quiz generation.")
            return
        try:
            curator = CuratorAgent(knowledge_base_path=foundry_iq_path)
            foundry_context = curator.extract_learning_modules(track_id=emp_state["assigned_track"])

            tester = TesterAgent(ai_engine=ai_engine)
            quiz_json = tester.generate_quiz(foundry_context, target_module)
            if quiz_json.startswith("ERROR:"):
                raise RuntimeError(quiz_json)
            quiz_data = _extract_json_payload(quiz_json)

            orchestrator.update_stage(target_employee_id, "QUIZ_PENDING", "active_quiz", quiz_data)
            orchestrator.record_inspection_event(
                action="GENERATE_QUIZ",
                employee_id=target_employee_id,
                before_state=before_employee_state,
                after_state=orchestrator.get_employee_state(target_employee_id),
                inputs={
                    "target_module": target_module,
                    "employee_profile": emp_profile,
                },
                note="Quiz generated from Foundry IQ retrieval trace.",
            )
            print("✅ Quiz generated and saved to active state. Waiting for submission.")
        except Exception as e:
            print(f"❌ Quiz generation failed: {e}")
            return

    # ACTION 3: Grade Answers
    elif requested_action == "SUBMIT_ANSWERS":
        if not emp_state.get("active_quiz") or not submission_payload:
            print("❌ No active quiz state or empty submission found.")
            return

        try:
            curator = CuratorAgent(knowledge_base_path=foundry_iq_path)
            foundry_context = curator.extract_learning_modules(track_id=emp_state["assigned_track"])
            tester = TesterAgent(ai_engine=ai_engine)
            grading_verdict = tester.evaluate_performance(
                json.dumps(emp_state["active_quiz"]),
                submission_payload,
                foundry_context,
            )
            verdict_data = _parse_model_json(grading_verdict, "Grading response")

            current_history = emp_state.get("quiz_submissions", [])
            current_history.append({
                "module": emp_state["active_quiz"].get("module"),
                "verdict": verdict_data
            })

            orchestrator.update_stage(target_employee_id, "COMPLETED_ASSESSMENT", "quiz_submissions", current_history)
            orchestrator.update_stage(target_employee_id, "COMPLETED_ASSESSMENT", "active_quiz", None)
            orchestrator.record_inspection_event(
                action="SUBMIT_ANSWERS",
                employee_id=target_employee_id,
                before_state=before_employee_state,
                after_state=orchestrator.get_employee_state(target_employee_id),
                inputs={
                    "submission_payload": submission_payload,
                    "active_quiz": emp_state.get("active_quiz"),
                    "foundry_context": foundry_context,
                },
                note="Verifier loop compared submission to quiz and Foundry context.",
            )
            if verdict_data.get("verdict") == "FAILED" and "raw_response" in verdict_data:
                print("⚠️ Grading response was not valid JSON, so a fallback failed verdict was saved.")
                print(f"Raw response: {verdict_data['raw_response']}")
            else:
                print("✅ Evaluation processed successfully. Verdict history updated.")
        except Exception as e:
            print(f"❌ Grading failed: {e}")
            return
    elif requested_action == "ENGAGEMENT_NUDGE":
        try:
            engagement_agent = EngagementAgent(work_base_path=work_iq_path, ai_engine=ai_engine)
            nudge_json = engagement_agent.generate_nudge(target_employee_id, emp_profile)
            nudge_data = _parse_model_json(nudge_json, "Engagement response")

            orchestrator.update_stage(target_employee_id, emp_state["current_stage"], "last_engagement_nudge", nudge_data)
            orchestrator.record_inspection_event(
                action="ENGAGEMENT_NUDGE",
                employee_id=target_employee_id,
                before_state=before_employee_state,
                after_state=orchestrator.get_employee_state(target_employee_id),
                inputs={
                    "employee_profile": emp_profile,
                    "work_schedule": _load_json_file(work_iq_path),
                },
                note="Engagement reminder generated from Work IQ focus window analysis.",
            )
            print("✅ Engagement nudge generated and stored.")
            print(json.dumps(nudge_data, indent=4))
        except Exception as e:
            print(f"❌ Engagement generation failed: {e}")
            return
    elif requested_action == "MANAGER_INSIGHTS":
        try:
            manager_agent = ManagerInsightsAgent(
                session_state_path="data/session_state.json",
                telemetry_path="data/system_telemetry.json",
                fabric_base_path=fabric_iq_path,
                ai_engine=ai_engine,
            )
            dashboard_data = manager_agent.generate_dashboard()
            orchestrator.save_team_insights(dashboard_data)
            safe_report = orchestrator.build_inspection_report(include_inspection_log=False)
            orchestrator.record_inspection_event(
                action="MANAGER_INSIGHTS",
                employee_id=None,
                before_state=before_employee_state,
                after_state=safe_report,
                inputs={
                    "session_state": orchestrator.state,
                },
                note="Executive dashboard synthesized from current backend state and team telemetry.",
            )
            print("✅ Manager insights dashboard generated and rendered.")
            print(manager_agent.render_dashboard(dashboard_data))
        except Exception as e:
            print(f"❌ Manager insights failed: {e}")
            return
    elif requested_action == "GENERATE_INSPECTION_REPORT":
        report = orchestrator.build_inspection_report()
        print(CertiFlowOrchestrator.render_inspection_report(report))
    else:
        print(f"❌ Unknown requested action: {requested_action}")


def run_pipeline_step_with_result(target_employee_id: str, requested_action: str, target_module: str = None, submission_payload: str = None) -> dict:
    """Run a pipeline step and return structured results for API or programmatic use."""
    foundry_iq_path = "data/foundry_iq.json"
    work_iq_path = "data/work_iq.json"
    fabric_iq_path = "data/fabric_iq.json"

    result = {
        "employee_id": target_employee_id,
        "action": requested_action,
        "success": False,
        "message": None,
        "error": None,
        "state": None,
    }

    try:
        ai_engine = AzureAIEngine()
        orchestrator = CertiFlowOrchestrator()

        fabric_data = _load_json_file(fabric_iq_path)
        emp_profile = next((e for e in fabric_data.get("employees", []) if e.get("employee_id") == target_employee_id), None)
        if not emp_profile:
            raise ValueError(f"Employee {target_employee_id} not found.")

        orchestrator.initialize_employee_state(target_employee_id, emp_profile["assigned_track"], emp_profile["role"])
        emp_state = orchestrator.get_employee_state(target_employee_id)
    except Exception as e:
        result["error"] = f"Failed to initialize workflow: {e}"
        return result

    before_employee_state = json.loads(json.dumps(emp_state))

    try:
        if requested_action == "GENERATE_SCHEDULE":
            curator = CuratorAgent(knowledge_base_path=foundry_iq_path)
            foundry_context = curator.extract_learning_modules(track_id=emp_state["assigned_track"])

            planner = PlannerAgent(schedule_base_path=work_iq_path, fabric_base_path=fabric_iq_path, ai_engine=ai_engine)
            ai_schedule = planner.generate_ai_schedule(target_employee_id, foundry_context, emp_profile)
            if ai_schedule.startswith("ERROR:"):
                raise RuntimeError(ai_schedule)
            schedule_data = _extract_json_payload(ai_schedule)

            orchestrator.update_stage(target_employee_id, "SCHEDULED", "schedule", schedule_data)
            result["message"] = "Schedule generated and committed to persistent state ledger."

        elif requested_action == "GENERATE_QUIZ":
            if not target_module:
                raise ValueError("Target module required for quiz generation.")

            curator = CuratorAgent(knowledge_base_path=foundry_iq_path)
            foundry_context = curator.extract_learning_modules(track_id=emp_state["assigned_track"])

            tester = TesterAgent(ai_engine=ai_engine)
            quiz_json = tester.generate_quiz(foundry_context, target_module)
            if quiz_json.startswith("ERROR:"):
                raise RuntimeError(quiz_json)
            quiz_data = _extract_json_payload(quiz_json)

            orchestrator.update_stage(target_employee_id, "QUIZ_PENDING", "active_quiz", quiz_data)
            result["message"] = "Quiz generated and saved to active state. Waiting for submission."

        elif requested_action == "SUBMIT_ANSWERS":
            if not emp_state.get("active_quiz") or not submission_payload:
                raise ValueError("No active quiz state or empty submission found.")

            curator = CuratorAgent(knowledge_base_path=foundry_iq_path)
            foundry_context = curator.extract_learning_modules(track_id=emp_state["assigned_track"])
            tester = TesterAgent(ai_engine=ai_engine)
            grading_verdict = tester.evaluate_performance(
                json.dumps(emp_state["active_quiz"]),
                submission_payload,
                foundry_context,
            )
            verdict_data = _parse_model_json(grading_verdict, "Grading response")

            current_history = emp_state.get("quiz_submissions", [])
            current_history.append({
                "module": emp_state["active_quiz"].get("module"),
                "verdict": verdict_data,
            })

            orchestrator.update_stage(target_employee_id, "COMPLETED_ASSESSMENT", "quiz_submissions", current_history)
            orchestrator.update_stage(target_employee_id, "COMPLETED_ASSESSMENT", "active_quiz", None)
            result["message"] = "Evaluation processed successfully. Verdict history updated."

        elif requested_action == "ENGAGEMENT_NUDGE":
            engagement_agent = EngagementAgent(work_base_path=work_iq_path, ai_engine=ai_engine)
            nudge_json = engagement_agent.generate_nudge(target_employee_id, emp_profile)
            nudge_data = _parse_model_json(nudge_json, "Engagement response")

            orchestrator.update_stage(target_employee_id, emp_state["current_stage"], "last_engagement_nudge", nudge_data)
            result["message"] = "Engagement nudge generated and stored."

        elif requested_action == "MANAGER_INSIGHTS":
            manager_agent = ManagerInsightsAgent(
                session_state_path="data/session_state.json",
                telemetry_path="data/system_telemetry.json",
                fabric_base_path=fabric_iq_path,
                ai_engine=ai_engine,
            )
            dashboard_data = manager_agent.generate_dashboard()
            orchestrator.save_team_insights(dashboard_data)
            result["message"] = "Manager insights dashboard generated and rendered."

        elif requested_action == "GENERATE_INSPECTION_REPORT":
            report = orchestrator.build_inspection_report()
            result["message"] = "Inspection report created."
            result["report"] = report

        else:
            raise ValueError(f"Unknown requested action: {requested_action}")

        result["success"] = True
        result["state"] = orchestrator.get_employee_state(target_employee_id)
    except Exception as e:
        result["error"] = str(e)

    return result


if __name__ == "__main__":
    # Simulate an asynchronous workflow split over distinct execution instances
    run_pipeline_step("EMP-001", "GENERATE_SCHEDULE")
    run_pipeline_step("EMP-001", "GENERATE_QUIZ", target_module="Module 1: Core Compute & Storage Fabric")

    mock_submission = json.dumps({
        "submission": [
            {"question_id": 1, "selected_choice": "A"},
            {"question_id": 2, "selected_choice": "B"}
        ]
    })
    run_pipeline_step("EMP-001", "SUBMIT_ANSWERS", submission_payload=mock_submission)
    run_pipeline_step("EMP-001", "ENGAGEMENT_NUDGE")
    run_pipeline_step("EMP-001", "MANAGER_INSIGHTS")
