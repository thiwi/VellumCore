pragma circom 2.1.8;

include "circomlib/circuits/comparators.circom";

template BatchCreditCheck(N) {
    signal input limits[N];        // Public
    signal input active_count;     // Public
    signal input balances[N];      // Private

    signal output all_valid;
    signal output active_count_out;

    signal is_active[N];
    signal decision_valid[N];
    signal all_valid_chain[N + 1];

    component active_count_gt_zero = GreaterThan(8);
    component active_count_lt_eq_n = LessThan(8);

    // 0 < active_count <= N (N is compiled as 250)
    active_count_gt_zero.in[0] <== active_count;
    active_count_gt_zero.in[1] <== 0;
    active_count_gt_zero.out === 1;

    active_count_lt_eq_n.in[0] <== active_count;
    active_count_lt_eq_n.in[1] <== N + 1;
    active_count_lt_eq_n.out === 1;

    all_valid_chain[0] <== 1;

    component activity_cmp[N];
    component balance_gt_limit[N];

    for (var i = 0; i < N; i++) {
        // is_active[i] = 1 iff i < active_count
        activity_cmp[i] = GreaterThan(8);
        activity_cmp[i].in[0] <== active_count;
        activity_cmp[i].in[1] <== i;
        is_active[i] <== activity_cmp[i].out;

        balance_gt_limit[i] = GreaterThan(32);
        balance_gt_limit[i].in[0] <== balances[i];
        balance_gt_limit[i].in[1] <== limits[i];

        // Inactive rows are neutral (valid) and must be zero padded.
        decision_valid[i] <== balance_gt_limit[i].out * is_active[i] + (1 - is_active[i]);
        balances[i] * (1 - is_active[i]) === 0;
        limits[i] * (1 - is_active[i]) === 0;

        all_valid_chain[i + 1] <== all_valid_chain[i] * decision_valid[i];
    }

    all_valid <== all_valid_chain[N];
    active_count_out <== active_count;
}

component main {public [limits, active_count]} = BatchCreditCheck(100);
