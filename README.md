# CertiFlow

CertiFlow is a synthetic multi-agent learning orchestrator demo. It simulates a learner journey across:

- Study planning
- Engagement nudges
- Quiz generation and grading
- Manager dashboard insights

The canonical app is now the FastAPI backend in [`api.py`](./api.py) plus the interactive GUI in [`static/index.html`](./static/index.html).

## What Runs Where

- [`app.py`](./app.py) is the main launch entrypoint.
- [`api.py`](./api.py) exposes the GUI backend routes.
- [`main.py`](./main.py) runs the same pipeline from the command line.
- [`orchestrator.py`](./orchestrator.py) holds the agent logic and state manager.
- [`static/index.html`](./static/index.html) is the interactive UI served by the backend.

## Quick Start

```powershell
.\.venv\Scripts\Activate.ps1
python app.py
```

Then open:

```text
http://127.0.0.1:8000/
```

That page gives you the full graphical interface. You can:

- generate a study schedule
- generate a quiz
- submit answers
- view manager insights
- inspect telemetry

For the agent actions to execute, make sure `.env` contains the Azure AI values used by `AzureAIEngine`, especially:

- `AZURE_AI_PROJECT_ENDPOINT`
- `AZURE_AI_MODEL_DEPLOYMENT`

If you prefer the command line demo:

```powershell
python main.py --request sample_request.json
```

## Docker

```powershell
docker build -t certiflow .
docker run -p 8000:8000 certiflow
```

## Data Files

The app uses synthetic JSON data in [`data/`](./data):

- `foundry_iq.json`
- `fabric_iq.json`
- `work_iq.json`
- `session_state.json`
- `system_telemetry.json`

## Safety

[`safety.py`](./safety.py) provides lightweight request validation plus helper utilities for sanitization and schema checks.

## Notes

- The legacy `demo.html` page now redirects to the main app path.
- `demo_server.py` remains as a compatibility launcher, but `python app.py` is the preferred startup command.
- Generated runtime logs are written to `logs/`.

## Next Improvements

- Add automated tests for the safety helpers and backend routes.
- Add a single source of truth for all UI state transformations.
- Persist runtime telemetry in a more explicit database or storage layer if this grows beyond demo usage.
