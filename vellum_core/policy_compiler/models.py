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
    param: str | None = Field(default=None, min_length=1)
    const_int: int | None = None

    @model_validator(mode="after")
    def validate_shape(self) -> "ValueRef":
        has_ref = self.ref is not None
        has_param = self.param is not None
        has_const = self.const_int is not None
        if sum((has_ref, has_param, has_const)) != 1:
            raise ValueError("value node requires exactly one of `ref`, `param`, or `const_int`")
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


class PolicyParameterSpec(BaseModel):
    """Declarative typed policy parameter definition."""

    model_config = ConfigDict(extra="forbid")

    value_type: Literal["int"] = "int"
    minimum: int | None = None
    maximum: int | None = None
    default: int | None = None

    @model_validator(mode="after")
    def validate_bounds(self) -> "PolicyParameterSpec":
        if self.minimum is not None and self.maximum is not None and self.minimum > self.maximum:
            raise ValueError("policy parameter minimum must be <= maximum")
        if self.default is not None:
            if self.minimum is not None and self.default < self.minimum:
                raise ValueError("policy parameter default must be >= minimum")
            if self.maximum is not None and self.default > self.maximum:
                raise ValueError("policy parameter default must be <= maximum")
        return self


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
    policy_parameters: dict[str, PolicyParameterSpec] = Field(default_factory=dict)
    decision: DecisionExpr
    outputs: dict[str, OutputSpec] = Field(min_length=1)
    primitives: list[str] = Field(min_length=1)
    expected_attestation: dict[str, str | int]

    generated_python_path: str = Field(min_length=1)
    generated_circom_path: str = Field(min_length=1)
    generated_debug_trace_path: str | None = None
    circuit_id: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_references(self) -> "PolicyDSLSpec":
        for output_name, output in self.outputs.items():
            if output.expr not in {"decision", "active_count", "policy_params_hash"}:
                raise ValueError(
                    f"output `{output_name}` uses unsupported expr `{output.expr}`"
                )
        if not self.generated_debug_trace_path:
            self.generated_debug_trace_path = self._derive_debug_trace_path()
        return self

    def _derive_debug_trace_path(self) -> str:
        circom_path = self.generated_circom_path
        if circom_path.endswith(".circom"):
            return circom_path.removesuffix(".circom") + ".debug.json"
        return circom_path + ".debug.json"
