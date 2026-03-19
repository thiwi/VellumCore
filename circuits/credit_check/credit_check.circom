pragma circom 2.1.8;

template CreditCheck() {
    signal input credit_score;
    signal input debt_ratio;
    signal output risk_score;

    risk_score <== (credit_score * 1000) - debt_ratio;
}

component main = CreditCheck();

