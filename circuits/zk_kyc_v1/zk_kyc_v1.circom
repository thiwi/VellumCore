pragma circom 2.1.8;

include "circomlib/circuits/comparators.circom";

template ZkKycV1() {
    signal input age;                    // Private
    signal input country_code;           // Private
    signal input min_age;                // Public policy parameter
    signal input allowed_country_code;   // Public policy parameter

    signal output kyc_ok;

    component age_ge_zero = GreaterEqThan(32);
    component age_le_max = LessEqThan(32);
    component min_age_ge_zero = GreaterEqThan(32);
    component min_age_le_max = LessEqThan(32);
    component country_ge_zero = GreaterEqThan(32);
    component country_le_max = LessEqThan(32);

    age_ge_zero.in[0] <== age;
    age_ge_zero.in[1] <== 0;
    age_ge_zero.out === 1;

    age_le_max.in[0] <== age;
    age_le_max.in[1] <== 130;
    age_le_max.out === 1;

    min_age_ge_zero.in[0] <== min_age;
    min_age_ge_zero.in[1] <== 0;
    min_age_ge_zero.out === 1;

    min_age_le_max.in[0] <== min_age;
    min_age_le_max.in[1] <== 130;
    min_age_le_max.out === 1;

    country_ge_zero.in[0] <== country_code;
    country_ge_zero.in[1] <== 0;
    country_ge_zero.out === 1;

    country_le_max.in[0] <== country_code;
    country_le_max.in[1] <== 999;
    country_le_max.out === 1;

    component age_cmp = GreaterEqThan(32);
    age_cmp.in[0] <== age;
    age_cmp.in[1] <== min_age;

    component country_eq = IsEqual();
    country_eq.in[0] <== country_code;
    country_eq.in[1] <== allowed_country_code;

    kyc_ok <== age_cmp.out * country_eq.out;
    kyc_ok * (kyc_ok - 1) === 0;
}

component main {public [min_age, allowed_country_code]} = ZkKycV1();
