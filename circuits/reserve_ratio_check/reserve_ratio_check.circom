pragma circom 2.1.8;

include "circomlib/circuits/comparators.circom";

template ReserveRatioCheck() {
    signal input liquid_assets;           // Private
    signal input short_term_liabilities;  // Private
    signal input min_reserve_ratio_bps;   // Public

    signal output reserve_ok;

    signal scaled_assets;
    signal scaled_required;

    component assets_ge_zero = GreaterEqThan(64);
    component assets_le_max = LessEqThan(64);
    component liabilities_ge_min = GreaterEqThan(64);
    component liabilities_le_max = LessEqThan(64);
    component min_ratio_ge_min = GreaterEqThan(32);
    component min_ratio_le_max = LessEqThan(32);

    assets_ge_zero.in[0] <== liquid_assets;
    assets_ge_zero.in[1] <== 0;
    assets_ge_zero.out === 1;

    assets_le_max.in[0] <== liquid_assets;
    assets_le_max.in[1] <== 1000000000;
    assets_le_max.out === 1;

    liabilities_ge_min.in[0] <== short_term_liabilities;
    liabilities_ge_min.in[1] <== 1;
    liabilities_ge_min.out === 1;

    liabilities_le_max.in[0] <== short_term_liabilities;
    liabilities_le_max.in[1] <== 1000000000;
    liabilities_le_max.out === 1;

    min_ratio_ge_min.in[0] <== min_reserve_ratio_bps;
    min_ratio_ge_min.in[1] <== 1;
    min_ratio_ge_min.out === 1;

    min_ratio_le_max.in[0] <== min_reserve_ratio_bps;
    min_ratio_le_max.in[1] <== 20000;
    min_ratio_le_max.out === 1;

    // liquid_assets / liabilities >= min_reserve_ratio_bps / 10000
    scaled_assets <== liquid_assets * 10000;
    scaled_required <== short_term_liabilities * min_reserve_ratio_bps;

    component reserve_cmp = GreaterEqThan(64);
    reserve_cmp.in[0] <== scaled_assets;
    reserve_cmp.in[1] <== scaled_required;
    reserve_ok <== reserve_cmp.out;
    reserve_ok * (reserve_ok - 1) === 0;
}

component main {public [min_reserve_ratio_bps]} = ReserveRatioCheck();
