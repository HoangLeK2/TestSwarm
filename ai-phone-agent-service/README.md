# AI Phone Agent Service

Standalone local POC service for AI Device Lab. The platform keeps tenant,
approval, lease, policy, device execution and evidence ownership. This service
returns typed plan drafts or bounded action proposals only.

## Local run

```sh
python -m venv .venv
. .venv/bin/activate
pip install -e ".[dev]"
uvicorn app.main:app --host 0.0.0.0 --port 8095
```

## Docker run

From the repository root:

```sh
docker compose -f docker-compose.ai-phone-agent.yml up -d --build
python ai-phone-agent-service/tests/e2e_http.py
docker compose -f docker-compose.ai-phone-agent.yml down
```

The current planner is deterministic and provider-free. Replace
`PlannerPort` with Mobilerun/AutoGLM/model-gateway adapters after the contract
and policy checks are stable.
