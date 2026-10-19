# Stock and Keys on the same 1017 runtime

Both campaigns use runtime `9f8d14e349be3811147b1fd5b35bcbdac6f824fd` and image
`sha256:eedc8c3acc3109262c92ccb4fcd8221b115f992cc34f644acd1bc40034c1a84a` on the same two GB10s, with 32 slots,
8,650,752 shared KV tokens and the same drafting, context and memory settings.
The Keys variant substitutes only the 26 attention `wo_b` projections in
layers 10–35, using the pinned 1017 K6 sidecar over the stock 2.9 bpw pack.

Every cell is the median of three scored repetitions, with one warm-up per
configuration. C1 uses first-to-last-content decode timing; C32 uses aggregate
steady decode while all 32 requests are active. Both campaigns include all
48 waves and 792 requests. [Protocol and stock repetitions](NATIVE-WORKLOADS.md) ·
[Keys repetitions](NATIVE-WORKLOADS-KEYS-1017-20261019.md).

| Configuration | Task | Stock tok/s | Keys tok/s | Difference |
| --- | --- | ---: | ---: | ---: |
| C1 greedy | Code | 94.0 | 90.5 | -3.7% |
| C1 greedy | Prose | 59.6 | 58.0 | -2.5% |
| C1 greedy | Counting | 134.2 | 137.4 | +2.4% |
| C32 greedy | Code | 302.2 | 273.7 | -9.4% |
| C32 greedy | Prose | 253.5 | 267.0 | +5.4% |
| C32 greedy | Counting | 372.6 | 372.0 | -0.2% |
| C1 sampled | Code | 96.2 | 90.1 | -6.3% |
| C1 sampled | Prose | 56.3 | 54.2 | -3.8% |
| C1 sampled | Counting | 130.7 | 136.4 | +4.4% |
| C32 sampled | Code | 264.1 | 256.8 | -2.7% |
| C32 sampled | Prose | 241.0 | 245.2 | +1.7% |
| C32 sampled | Counting | 360.8 | 362.4 | +0.4% |

The stock campaign ran first; the Keys campaign ran after switching and finite
validation. Prompts, seeds and output caps match, but changed weights can
change replies, stopping points and draft acceptance. These are end-to-end
model variants, not an isolated comparison of K5 and K6 kernel speed. This
workload suite does not measure model quality or refusal behavior.

All raw waves remain available for [stock](evidence/native-workloads-1017-stock-comparison-20261018.json)
and [Keys](evidence/native-workloads-1017-keys-20261018.json). The earlier
[stock migration campaign](NATIVE-WORKLOADS-STOCK-1017-20261018.md) uses a
different runtime and remains separate.

The stock → Keys → stock → Keys rehearsal preserved every model alias and
replayed all six fixed-seed synthetic prompts identically within each variant.
Both ranks reported 78 loaded replacement slices for Keys and zero for stock.
The measured resident-weight increase was 65 MiB on each GPU; the immutable
stock-cache fingerprints stayed unchanged through the switches.

[Setup, switching and rollback](../deployment/KEYS-1017.md) ·
[Qualification evidence](../release/native-keys-1017-20261018.json).
