pragma circom 2.1.8;

include "circomlib/circuits/comparators.circom";

template DTICheck() {
    signal input monthly_income;          // Private
    signal input monthly_debt_payment;    // Private
    signal input max_dti_bps;             // Public

    signal output dti_ok;

    signal scaled_debt;
    signal scaled_income_limit;

    // debt / income <= max_dti_bps / 10000
    scaled_debt <== monthly_debt_payment * 10000;
    scaled_income_limit <== monthly_income * max_dti_bps;

    component dti_cmp = LessEqThan(64);
    dti_cmp.in[0] <== scaled_debt;
    dti_cmp.in[1] <== scaled_income_limit;
    dti_ok <== dti_cmp.out;
}

component main {public [max_dti_bps]} = DTICheck();
