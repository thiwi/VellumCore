"""Security regression checks for legacy circuit constraints."""

from __future__ import annotations

from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.security
def test_credit_check_has_explicit_range_constraints() -> None:
    src = (ROOT / "circuits" / "credit_check" / "credit_check.circom").read_text(
        encoding="utf-8"
    )
    assert "credit_le_max.in[1] <== 900;" in src
    assert "debt_le_max.in[1] <== 1000000;" in src
    assert "credit_ge_zero.out === 1;" in src
    assert "debt_ge_zero.out === 1;" in src


@pytest.mark.security
def test_aml_check_has_explicit_range_constraints() -> None:
    src = (ROOT / "circuits" / "aml_check" / "aml_check.circom").read_text(encoding="utf-8")
    assert "amount_le_max.in[1] <== 1000000000;" in src
    assert "weight_le_max.in[1] <== 10000;" in src
    assert "amount_ge_zero.out === 1;" in src
    assert "weight_ge_zero.out === 1;" in src


@pytest.mark.security
def test_dti_check_has_domain_and_boolean_constraints() -> None:
    src = (ROOT / "circuits" / "dti_check" / "dti_check.circom").read_text(encoding="utf-8")
    assert "income_ge_min.in[1] <== 1;" in src
    assert "max_bps_le_max.in[1] <== 10000;" in src
    assert "dti_ok * (dti_ok - 1) === 0;" in src


@pytest.mark.security
def test_reserve_ratio_check_has_domain_and_boolean_constraints() -> None:
    src = (
        ROOT / "circuits" / "reserve_ratio_check" / "reserve_ratio_check.circom"
    ).read_text(encoding="utf-8")
    assert "liabilities_ge_min.in[1] <== 1;" in src
    assert "min_ratio_le_max.in[1] <== 20000;" in src
    assert "reserve_ok * (reserve_ok - 1) === 0;" in src

