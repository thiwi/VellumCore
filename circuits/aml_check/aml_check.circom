pragma circom 2.1.8;

include "circomlib/circuits/comparators.circom";

template AMLCheck() {
    signal input amount;
    signal input risk_weight;
    signal output aml_score;

    component amount_ge_zero = GreaterEqThan(64);
    component amount_le_max = LessEqThan(64);
    component weight_ge_zero = GreaterEqThan(32);
    component weight_le_max = LessEqThan(32);

    amount_ge_zero.in[0] <== amount;
    amount_ge_zero.in[1] <== 0;
    amount_ge_zero.out === 1;

    amount_le_max.in[0] <== amount;
    amount_le_max.in[1] <== 1000000000;
    amount_le_max.out === 1;

    weight_ge_zero.in[0] <== risk_weight;
    weight_ge_zero.in[1] <== 0;
    weight_ge_zero.out === 1;

    weight_le_max.in[0] <== risk_weight;
    weight_le_max.in[1] <== 10000;
    weight_le_max.out === 1;

    aml_score <== amount * risk_weight;
}

component main = AMLCheck();
