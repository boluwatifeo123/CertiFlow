import os
import json

def generate_synthetic_data():
    # Ensure data directory exists
    os.makedirs("data", exist_ok=True)
    print("[seed] data/ directory verified.")

    # 1. FOUNDRY IQ (The Knowledge Layer - Syllabus & Study Tracks)
    foundry_iq = {
        "certification_tracks": [
            {
                "track_id": "TRACK-AZ-ADMIN",
                "track_name": "Synthetic Azure Enterprise Systems Administrator",
                "description": "Fictional track inspired by enterprise cloud infrastructure scale and access boundaries.",
                "modules": [
                    {
                        "module_id": "AZ-MOD-01",
                        "name": "Module 1: Core Compute & Storage Fabric",
                        "estimated_hours_required": 6,
                        "topics": [
                            "Virtual machine scale sets and regional high-availability mapping",
                            "Blob storage tiering strategies and lifecycle rules",
                            "Managed disk encryption keys and replication configurations"
                        ]
                    },
                    {
                        "module_id": "AZ-MOD-02",
                        "name": "Module 2: Virtual Networking & Identity Safeguards",
                        "estimated_hours_required": 8,
                        "topics": [
                            "Virtual network peering, subnet routing policies, and security group rules",
                            "Role-based access control definition and conditional entry parameters",
                            "Hybrid cloud network gateway tunnels and cross-region traffic routing"
                        ]
                    }
                ]
            },
            {
                "track_id": "TRACK-DP-DATA",
                "track_name": "Synthetic Enterprise Data Estate Engineering",
                "description": "Fictional track focused on scalable corporate data assets and privacy structures.",
                "modules": [
                    {
                        "module_id": "DP-MOD-01",
                        "name": "Module 1: Large-Scale Ingestion Fabrics",
                        "estimated_hours_required": 8,
                        "topics": [
                            "Streaming stream-processing architectures and partitioned data lakes",
                            "Batch extraction, transformation, and load pipeline sequencing",
                            "Schema drift mitigation strategies within transactional repositories"
                        ]
                    }
                ]
            },
            {
                "track_id": "TRACK-AI-ENGINEER",
                "track_name": "Synthetic Autonomous Intelligent Agent Systems",
                "description": "Fictional track focused on custom model deployments and multi-agent systems.",
                "modules": [
                    {
                        "module_id": "AI-MOD-01",
                        "name": "Module 1: Grounded Retrieval & Model Provisioning",
                        "estimated_hours_required": 10,
                        "topics": [
                            "Custom large language model endpoint provisioning and prompt engineering",
                            "Vector database indexing and retrieval-augmented generation chunk optimization",
                            "Context window optimization and strict systemic token management"
                        ]
                    }
                ]
            }
        ]
    }

    # 2. FABRIC IQ (The Semantic Business Context - Roles, Requirements & Progress)
    fabric_iq = {
        "employees": [
            {
                "employee_id": "EMP-001",
                "role": "Synthetic Cloud Operations Associate",
                "department": "Engineering-A",
                "assigned_track": "TRACK-AZ-ADMIN",
                "passing_score_threshold": 80,
                "current_status": "Not Started"
            }
        ]
    }

    # 3. WORK IQ (The Operational Workload Context - Calendar Schedules)
    work_iq = {
        "schedules": [
            {
                "employee_id": "EMP-001",
                "weekly_busy_blocks": [
                    {"day": "Monday", "start_time": "09:00", "end_time": "12:00", "description": "Team Sync & Status"},
                    {"day": "Tuesday", "start_time": "13:00", "end_time": "15:00", "description": "Architecture Review"},
                    {"day": "Wednesday", "start_time": "10:00", "end_time": "11:30", "description": "Client Deliverable Review"},
                    {"day": "Thursday", "start_time": "14:00", "end_time": "17:00", "description": "Deep Focus Dev Sprint"},
                    {"day": "Friday", "start_time": "15:00", "end_time": "17:00", "description": "Retrospective & Admin"}
                ],
                "preferred_learning_windows": [
                    {"day": "Tuesday", "start_time": "09:00", "end_time": "11:00"},
                    {"day": "Thursday", "start_time": "09:00", "end_time": "11:00"}
                ]
            }
        ]
    }

    # Write files to the disk
    with open("data/foundry_iq.json", "w") as f:
        json.dump(foundry_iq, f, indent=4)
    print("[seed] Created: data/foundry_iq.json (Knowledge Layer)")

    with open("data/fabric_iq.json", "w") as f:
        json.dump(fabric_iq, f, indent=4)
    print("[seed] Created: data/fabric_iq.json (Semantic Business Context)")

    session_state = {
        "employees": {
            "EMP-001": {
                "assigned_track": "TRACK-AZ-ADMIN",
                "current_stage": "INITIALIZED",
                "active_quiz": None
            }
        }
    }

    telemetry_state = {
        "employees": {
            "EMP-001": {
                "schedule": None,
                "quiz_submissions": [],
                "last_engagement_nudge": None
            }
        },
        "manager_insights": {},
        "inspection_log": []
    }

    with open("data/session_state.json", "w") as f:
        json.dump(session_state, f, indent=4)
    print("[seed] Created: data/session_state.json (Core Session State)")

    with open("data/system_telemetry.json", "w") as f:
        json.dump(telemetry_state, f, indent=4)
    print("[seed] Created: data/system_telemetry.json (Telemetry & Inspection Layer)")

    with open("data/work_iq.json", "w") as f:
        json.dump(work_iq, f, indent=4)
    print("[seed] Created: data/work_iq.json (Workload Context)")

if __name__ == "__main__":
    generate_synthetic_data()
    print("\n[seed] Synthetic Data Mock Layer successfully seeded!")
