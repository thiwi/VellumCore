pragma circom 2.1.8;

include "circomlib/circuits/comparators.circom";

template ReserveRatioCheck() {
    signal input liquid_assets;           // Private
    signal input short_term_liabilities;  // Private
    signal input min_reserve_ratio_bps;   // Public

    signal output reserve_ok;

    signal scaled_assets;
    signal scaled_required;

    // liquid_assets / liabilities >= min_reserve_ratio_bps / 10000
    scaled_assets <== liquid_assets * 10000;
    scaled_required <== short_term_liabilities * min_reserve_ratio_bps;

    component reserve_cmp = GreaterEqThan(64);
    reserve_cmp.in[0] <== scaled_assets;
    reserve_cmp.in[1] <== scaled_required;
    reserve_ok <== reserve_cmp.out;
}

component main {public [min_reserve_ratio_bps]} = ReserveRatioCheck();
