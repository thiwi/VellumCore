pragma circom 2.1.8;

template Complexity1K() {
    signal input seed;
    signal output digest;
    signal states[1001];

    states[0] <== seed;
    for (var i = 0; i < 1000; i++) {
        states[i + 1] <== states[i] * states[i] + 3;
    }

    digest <== states[1000];
}

component main = Complexity1K();

