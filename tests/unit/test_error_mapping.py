from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from vellum_core.api.errors import FrameworkError
from vellum_core.errors import register_exception_handlers


app = FastAPI()
register_exception_handlers(app)


@app.get("/boom")
async def boom() -> None:
    raise FrameworkError(code="framework_failed", message="framework explosion", details={"k": "v"})


def test_framework_error_mapped_to_api_payload() -> None:
    client = TestClient(app)
    response = client.get("/boom")
    assert response.status_code == 422
    payload = response.json()
    assert payload["error"]["code"] == "framework_failed"
    assert payload["error"]["details"]["k"] == "v"
