pragma circom 2.1.8;

include "circomlib/circuits/comparators.circom";

template DTICheck() {
    signal input monthly_income;          // Private
    signal input monthly_debt_payment;    // Private
    signal input max_dti_bps;             // Public

    signal output dti_ok;

    signal scaled_debt;
    signal scaled_income_limit;

    component income_ge_min = GreaterEqThan(64);
    component income_le_max = LessEqThan(64);
    component debt_ge_zero = GreaterEqThan(64);
    component debt_le_max = LessEqThan(64);
    component max_bps_ge_min = GreaterEqThan(32);
    component max_bps_le_max = LessEqThan(32);

    income_ge_min.in[0] <== monthly_income;
    income_ge_min.in[1] <== 1;
    income_ge_min.out === 1;

    income_le_max.in[0] <== monthly_income;
    income_le_max.in[1] <== 1000000000;
    income_le_max.out === 1;

    debt_ge_zero.in[0] <== monthly_debt_payment;
    debt_ge_zero.in[1] <== 0;
    debt_ge_zero.out === 1;

    debt_le_max.in[0] <== monthly_debt_payment;
    debt_le_max.in[1] <== 1000000000;
    debt_le_max.out === 1;

    max_bps_ge_min.in[0] <== max_dti_bps;
    max_bps_ge_min.in[1] <== 1;
    max_bps_ge_min.out === 1;

    max_bps_le_max.in[0] <== max_dti_bps;
    max_bps_le_max.in[1] <== 10000;
    max_bps_le_max.out === 1;

    // debt / income <= max_dti_bps / 10000
    scaled_debt <== monthly_debt_payment * 10000;
    scaled_income_limit <== monthly_income * max_dti_bps;

    component dti_cmp = LessEqThan(64);
    dti_cmp.in[0] <== scaled_debt;
    dti_cmp.in[1] <== scaled_income_limit;
    dti_ok <== dti_cmp.out;
    dti_ok * (dti_ok - 1) === 0;
}

component main {public [max_dti_bps]} = DTICheck();
