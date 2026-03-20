"""Service-layer error normalization and FastAPI exception handlers."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from vellum_core.api.errors import FrameworkError


@dataclass
class APIError(Exception):
    """Typed HTTP-facing error used by service routes and adapters."""

    status_code: int
    code: str
    message: str
    details: dict[str, Any] = field(default_factory=dict)

    def to_payload(self) -> dict[str, Any]:
        """Render standardized JSON error body."""
        return {
            "error": {
                "code": self.code,
                "message": self.message,
                "details": self.details,
            }
        }


def register_exception_handlers(app: FastAPI) -> None:
    """Register shared exception handlers for APIError/validation/unexpected errors."""
    @app.exception_handler(FrameworkError)
    async def handle_framework_error(_: Request, exc: FrameworkError) -> JSONResponse:
        payload = APIError(
            status_code=422,
            code=exc.code,
            message=exc.message,
            details=exc.details,
        )
        return JSONResponse(status_code=422, content=payload.to_payload())

    @app.exception_handler(APIError)
    async def handle_api_error(_: Request, exc: APIError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content=exc.to_payload())

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        _: Request, exc: RequestValidationError
    ) -> JSONResponse:
        payload = APIError(
            status_code=422,
            code="validation_error",
            message="Request validation failed",
            details={"errors": exc.errors()},
        )
        return JSONResponse(status_code=422, content=payload.to_payload())

    @app.exception_handler(Exception)
    async def handle_unexpected_error(_: Request, exc: Exception) -> JSONResponse:
        payload = APIError(
            status_code=500,
            code="internal_error",
            message="Unexpected server error",
            details={"type": exc.__class__.__name__},
        )
        return JSONResponse(status_code=500, content=payload.to_payload())
