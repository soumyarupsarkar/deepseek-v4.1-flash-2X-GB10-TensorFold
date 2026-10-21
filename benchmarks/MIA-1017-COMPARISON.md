# LibertAI stock and Mia EAQ stock on this recipe

Matched campaigns on the same two GB10s, retaining 32 slots, an
8,650,752-token shared pool, a 1,048,576-token request ceiling and the
same drafting policy, graph/grammar budgets and 2 GiB memory guard.

Every value is the median of three scored waves. C1 uses first-to-last-
content decode timing; C32 is aggregate steady output tok/s with all 32
decoders active. Each campaign includes all 48 waves and 792 requests.

| Configuration | Task | LibertAI stock tok/s | Mia stock tok/s | Difference |
| --- | --- | ---: | ---: | ---: |
| C1 greedy | Code | 92.7 | 97.8 | +5.5% |
| C1 greedy | Prose | 59.8 | 63.9 | +6.9% |
| C1 greedy | Counting | 133.9 | 141.4 | +5.6% |
| C32 greedy | Code | 301.7 | 306.9 | +1.7% |
| C32 greedy | Prose | 253.3 | 256.9 | +1.4% |
| C32 greedy | Counting | 370.9 | 380.4 | +2.6% |
| C1 sampled | Code | 95.3 | 89.3 | -6.2% |
| C1 sampled | Prose | 56.3 | 62.8 | +11.4% |
| C1 sampled | Counting | 130.3 | 139.5 | +7.0% |
| C32 sampled | Code | 264.4 | 264.6 | +0.1% |
| C32 sampled | Prose | 238.6 | 242.2 | +1.5% |
| C32 sampled | Counting | 360.3 | 367.3 | +1.9% |

Prompts, seeds, caps and timing methods match. Changed weights can change
replies, stopping points and draft acceptance. These are comparisons of
complete model variants, not isolated kernel-speed measurements or a
model-quality/refusal-rate evaluation. No repetition is discarded.

[Mia stock repetitions and protocol](NATIVE-WORKLOADS.md) ·
[Mia Keys repetitions](NATIVE-WORKLOADS-MIA-KEYS-20261020.md) ·
[Fresh LibertAI baseline](NATIVE-WORKLOADS-LIBERT-STOCK-20261020.md).

## Memory and compatibility

Loaded stock GPU weights changed from 106,193,982,932 to 106,110,129,620 bytes per
rank: **79.97 MiB less**. Mia uses its native FP16
confidence-head storage and K4 MTP dense projections. The matching Keys
sidecar is separately optional; this comparison uses stock on both sides.

Available host RAM also depends on paging and cache state. The migration
therefore retains the same capacity/guard and checks full-context behavior,
sampled memory lows across the run and normalized quiet-window anonymous-plus-swap
footprints. See the [qualification report](../release/native-mia-1017-20261020.json)
and [migration/rollback notes](../deployment/MIA-1017.md).

The separate 192-token draft diagnostic uses one wave per shape. Sampled
C1 code showed lower acceptance with Mia, consistent with its throughput
decrease; prose acceptance improved. Diagnostic counts and every shape
remain in the qualification report. They are separate from the three-
repetition throughput campaign.

## Runtime identities

- libert-stock: source `9f8d14e349be3811147b1fd5b35bcbdac6f824fd`, image `sha256:eedc8c3acc3109262c92ccb4fcd8221b115f992cc34f644acd1bc40034c1a84a`.
- mia-stock: source `7ebfbdbf3b01da8ab56a4d995324205104082efa`, image `sha256:304b45701d11c6e852d26984990a6105c64473cef56eb148d9aa5e96dfe1eb87`.
