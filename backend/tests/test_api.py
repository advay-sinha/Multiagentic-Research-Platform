import os

import pytest
from fastapi.testclient import TestClient

from backend.app.main import app


client = TestClient(app)


@pytest.mark.skipif(not os.environ.get("DATABASE_URL"), reason="DATABASE_URL not set")
def test_health():
    response = client.get("/v1/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["version"] == "0.1.0"


@pytest.mark.skipif(not os.environ.get("DATABASE_URL"), reason="DATABASE_URL not set")
def test_upload_query_trace_flow():
    files = {"file": ("sample.txt", b"Sample content for retrieval.")}
    response = client.post("/v1/documents", files=files)
    assert response.status_code == 200
    document = response.json()
    assert document["status"] == "indexed"

    query_response = client.post("/v1/query", json={"query": "Sample content"})
    assert query_response.status_code == 200
    query_payload = query_response.json()
    assert query_payload["trace_id"].startswith("trace-")

    trace_response = client.get(f"/v1/traces/{query_payload['trace_id']}")
    assert trace_response.status_code == 200
    trace_payload = trace_response.json()
    assert trace_payload["trace_id"] == query_payload["trace_id"]
    assert len(trace_payload["events"]) >= 1
