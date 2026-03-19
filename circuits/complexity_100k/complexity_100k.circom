pragma circom 2.1.8;

template Complexity100K() {
    signal input seed;
    signal output digest;
    signal states[100001];

    states[0] <== seed;
    for (var i = 0; i < 100000; i++) {
        states[i + 1] <== states[i] * states[i] + 3;
    }

    digest <== states[100000];
}

component main = Complexity100K();

