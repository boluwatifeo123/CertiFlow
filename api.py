from fastapi import FastAPI, HTTPException
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import Optional

from orchestrator import run_pipeline_step_with_result, CertiFlowOrchestrator, _load_json_file

app = FastAPI(title="CertiFlow Backend")
app.mount("/ui", StaticFiles(directory="static"), name="static")


@app.get("/")
async def root_ui():
    return RedirectResponse(url="/ui/index.html")


class PipelineRequest(BaseModel):
    employee_id: str
    action: str
    target_module: Optional[str] = None
    submission_payload: Optional[str] = None


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/pipeline")
async def pipeline_step(request: PipelineRequest):
    result = run_pipeline_step_with_result(
        request.employee_id,
        request.action,
        request.target_module,
        request.submission_payload,
    )
    if not result["success"]:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@app.get("/state/{employee_id}")
async def get_employee_state(employee_id: str):
    orchestrator = CertiFlowOrchestrator()
    state = orchestrator.get_employee_state(employee_id)
    if not state:
        raise HTTPException(status_code=404, detail="Employee not found")
    return state


@app.get("/telemetry/{employee_id}")
async def get_employee_telemetry(employee_id: str):
    orchestrator = CertiFlowOrchestrator()
    telemetry = orchestrator.get_employee_telemetry(employee_id)
    if not telemetry:
        raise HTTPException(status_code=404, detail="Employee telemetry not found")
    return telemetry


@app.get("/inspection")
async def get_inspection_report():
    orchestrator = CertiFlowOrchestrator()
    report = orchestrator.build_inspection_report()
    return report


@app.get("/dashboard")
async def get_dashboard():
    orchestrator = CertiFlowOrchestrator()
    return orchestrator.telemetry.get("manager_insights", {})
