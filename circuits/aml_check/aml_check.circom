pragma circom 2.1.8;

template AMLCheck() {
    signal input amount;
    signal input risk_weight;
    signal output aml_score;

    aml_score <== amount * risk_weight;
}

component main = AMLCheck();

