"""Pydantic models for the YAML policy DSL used by `vellum-compiler`."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


ComparisonOp = Literal["<", ">", "<=", ">=", "=="]
DecisionExprKind = Literal["comparison", "and", "or", "not", "all", "any"]


class ValueRef(BaseModel):
    """Reference to one DSL input or derived runtime value."""

    model_config = ConfigDict(extra="forbid")

    ref: str | None = Field(default=None, min_length=1)
    const_int: int | None = None

    @model_validator(mode="after")
    def validate_shape(self) -> "ValueRef":
        has_ref = self.ref is not None
        has_const = self.const_int is not None
        if has_ref == has_const:
            raise ValueError("value node requires exactly one of `ref` or `const_int`")
        return self


class ComparisonExpr(BaseModel):
    """Binary comparison expression in DSL."""

    model_config = ConfigDict(extra="forbid")

    op: ComparisonOp
    left: ValueRef
    right: ValueRef


class DecisionExpr(BaseModel):
    """Recursive decision expression model."""

    model_config = ConfigDict(extra="forbid")

    kind: DecisionExprKind
    comparison: ComparisonExpr | None = None
    args: list[DecisionExpr] = Field(default_factory=list)
    inner: DecisionExpr | None = None

    @model_validator(mode="after")
    def validate_shape(self) -> "DecisionExpr":
        if self.kind == "comparison":
            if self.comparison is None:
                raise ValueError("comparison kind requires `comparison` node")
            if self.args or self.inner is not None:
                raise ValueError("comparison kind cannot define args/inner")
            return self

        if self.kind in {"and", "or"}:
            if len(self.args) < 2:
                raise ValueError(f"{self.kind} requires at least two args")
            if self.comparison is not None or self.inner is not None:
                raise ValueError(f"{self.kind} cannot define comparison/inner")
            return self

        if self.kind in {"not", "all", "any"}:
            if self.inner is None:
                raise ValueError(f"{self.kind} requires `inner` expression")
            if self.comparison is not None or self.args:
                raise ValueError(f"{self.kind} cannot define comparison/args")
            return self

        raise ValueError(f"Unsupported decision kind: {self.kind}")


DecisionExpr.model_rebuild()


class InputSpec(BaseModel):
    """Input field declaration in DSL."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["uint32_array"]


class BatchSpec(BaseModel):
    """Batch processing limits for policy DSL."""

    model_config = ConfigDict(extra="forbid")

    batch_size: int = Field(ge=1)


class OutputSpec(BaseModel):
    """Manifest/differential output declaration."""

    model_config = ConfigDict(extra="forbid")

    expr: str = Field(min_length=1)
    value_type: Literal["int", "bool", "string"]
    signal_index: int = Field(ge=0)


class PolicyDSLSpec(BaseModel):
    """Top-level policy DSL document model."""

    model_config = ConfigDict(extra="forbid")

    policy_id: str = Field(min_length=1)
    policy_version: str = Field(min_length=1)
    reference_policy: str = Field(min_length=1)
    spec_version: str = Field(min_length=1)
    compiler_version: str = Field(min_length=1)
    description: str | None = None

    batch: BatchSpec
    inputs: dict[str, InputSpec] = Field(min_length=1)
    decision: DecisionExpr
    outputs: dict[str, OutputSpec] = Field(min_length=1)
    primitives: list[str] = Field(min_length=1)
    expected_attestation: dict[str, str | int]

    generated_python_path: str = Field(min_length=1)
    generated_circom_path: str = Field(min_length=1)
    circuit_id: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_references(self) -> "PolicyDSLSpec":
        for output_name, output in self.outputs.items():
            if output.expr not in {"decision", "active_count"}:
                raise ValueError(
                    f"output `{output_name}` uses unsupported expr `{output.expr}`"
                )
        return self
