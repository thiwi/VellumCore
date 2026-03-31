pragma circom 2.1.8;

include "circomlib/circuits/comparators.circom";

template ProofOfReservesV1() {
    signal input liabilities;    // Private
    signal input assets;         // Private
    signal output solvency_ok;

    component liabilities_ge_zero = GreaterEqThan(64);
    component liabilities_le_max = LessEqThan(64);
    component assets_ge_zero = GreaterEqThan(64);
    component assets_le_max = LessEqThan(64);

    liabilities_ge_zero.in[0] <== liabilities;
    liabilities_ge_zero.in[1] <== 0;
    liabilities_ge_zero.out === 1;

    liabilities_le_max.in[0] <== liabilities;
    liabilities_le_max.in[1] <== 1000000000000;
    liabilities_le_max.out === 1;

    assets_ge_zero.in[0] <== assets;
    assets_ge_zero.in[1] <== 0;
    assets_ge_zero.out === 1;

    assets_le_max.in[0] <== assets;
    assets_le_max.in[1] <== 1000000000000;
    assets_le_max.out === 1;

    component solvency_cmp = GreaterEqThan(64);
    solvency_cmp.in[0] <== assets;
    solvency_cmp.in[1] <== liabilities;

    solvency_ok <== solvency_cmp.out;
    solvency_ok * (solvency_ok - 1) === 0;
}

component main = ProofOfReservesV1();
