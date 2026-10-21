# Mia EAQ stock and its matching Keys overlay

Matched campaigns on the same two GB10s, retaining 32 slots, an
8,650,752-token shared pool, a 1,048,576-token request ceiling and the
same drafting policy, graph/grammar budgets and 2 GiB memory guard.

Every value is the median of three scored waves. C1 uses first-to-last-
content decode timing; C32 is aggregate steady output tok/s with all 32
decoders active. Each campaign includes all 48 waves and 792 requests.

| Configuration | Task | Mia stock tok/s | Mia + Keys tok/s | Difference |
| --- | --- | ---: | ---: | ---: |
| C1 greedy | Code | 97.8 | 94.6 | -3.2% |
| C1 greedy | Prose | 63.9 | 60.2 | -5.8% |
| C1 greedy | Counting | 141.4 | 138.3 | -2.2% |
| C32 greedy | Code | 306.9 | 299.8 | -2.3% |
| C32 greedy | Prose | 256.9 | 271.6 | +5.7% |
| C32 greedy | Counting | 380.4 | 374.1 | -1.7% |
| C1 sampled | Code | 89.3 | 87.2 | -2.4% |
| C1 sampled | Prose | 62.8 | 61.6 | -1.9% |
| C1 sampled | Counting | 139.5 | 139.0 | -0.3% |
| C32 sampled | Code | 264.6 | 261.5 | -1.2% |
| C32 sampled | Prose | 242.2 | 247.0 | +2.0% |
| C32 sampled | Counting | 367.3 | 361.5 | -1.6% |

Prompts, seeds, caps and timing methods match. Changed weights can change
replies, stopping points and draft acceptance. These are comparisons of
complete model variants, not isolated kernel-speed measurements or a
model-quality/refusal-rate evaluation. No repetition is discarded.

[Mia stock repetitions and protocol](NATIVE-WORKLOADS.md) ·
[Mia Keys repetitions](NATIVE-WORKLOADS-MIA-KEYS-20261020.md) ·
[Fresh LibertAI baseline](NATIVE-WORKLOADS-LIBERT-STOCK-20261020.md).

## Variant and switching

The matching Mia sidecar replaces only layers 10–35 `wo_b` tensors. Both
the stock tensors and replacements are EXL3 K5; experts, MTP, Engram and
vision remain stock. Both variants use the same tested source and image.

The stock → Keys → stock → Keys → stock rehearsal preserved aliases and
replayed six fixed-seed synthetic prompts identically within each variant,
including the final stock selection. Both ranks reported 78 loaded slices
for Keys and zero for stock. Additional resident GPU weight bytes were
**zero on both ranks**. Base-cache fingerprints remained unchanged.

[Setup and rollback](../deployment/KEYS-1017.md) ·
[Numeric qualification](../release/native-mia-1017-20261020.json) ·
[Earlier LibertAI/K6 comparison](KEYS-LIBERT-1017-COMPARISON.md).

## Runtime identities

- mia-stock: source `7ebfbdbf3b01da8ab56a4d995324205104082efa`, image `sha256:304b45701d11c6e852d26984990a6105c64473cef56eb148d9aa5e96dfe1eb87`.
- mia-keys: source `7ebfbdbf3b01da8ab56a4d995324205104082efa`, image `sha256:304b45701d11c6e852d26984990a6105c64473cef56eb148d9aa5e96dfe1eb87`.
