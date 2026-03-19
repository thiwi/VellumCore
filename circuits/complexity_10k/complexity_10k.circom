pragma circom 2.1.8;

template Complexity10K() {
    signal input seed;
    signal output digest;
    signal states[10001];

    states[0] <== seed;
    for (var i = 0; i < 10000; i++) {
        states[i + 1] <== states[i] * states[i] + 3;
    }

    digest <== states[10000];
}

component main = Complexity10K();

