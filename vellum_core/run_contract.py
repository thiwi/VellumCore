"""Shared v6 run contract models reused by SDK and HTTP schemas."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class EvidenceInlineV6(BaseModel):
    """Inline evidence payload embedded in a run-create request."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["inline"]
    payload: dict[str, Any]


class EvidenceRefV6(BaseModel):
    """Evidence reference pointer used in a run-create request."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["ref"]
    ref: str = Field(min_length=1)


EvidenceInputV6 = Annotated[
    EvidenceInlineV6 | EvidenceRefV6,
    Field(discriminator="type"),
]


class RunCreateRequestV6(BaseModel):
    """V6 request model for creating one policy run from typed evidence input."""

    model_config = ConfigDict(extra="forbid")

    policy_id: str = Field(min_length=1)
    evidence: EvidenceInputV6
    context: dict[str, Any] = Field(default_factory=dict)
    client_request_id: str | None = None
