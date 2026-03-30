pragma circom 2.1.8;

include "circomlib/circuits/comparators.circom";

template CreditCheck() {
    signal input credit_score;
    signal input debt_ratio;
    signal output risk_score;

    component credit_ge_zero = GreaterEqThan(32);
    component credit_le_max = LessEqThan(32);
    component debt_ge_zero = GreaterEqThan(32);
    component debt_le_max = LessEqThan(32);

    credit_ge_zero.in[0] <== credit_score;
    credit_ge_zero.in[1] <== 0;
    credit_ge_zero.out === 1;

    credit_le_max.in[0] <== credit_score;
    credit_le_max.in[1] <== 900;
    credit_le_max.out === 1;

    debt_ge_zero.in[0] <== debt_ratio;
    debt_ge_zero.in[1] <== 0;
    debt_ge_zero.out === 1;

    debt_le_max.in[0] <== debt_ratio;
    debt_le_max.in[1] <== 1000000;
    debt_le_max.out === 1;

    risk_score <== (credit_score * 1000) - debt_ratio;
}

component main = CreditCheck();
