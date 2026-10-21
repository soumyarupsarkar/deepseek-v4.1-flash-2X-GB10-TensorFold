# Mia EAQ 1017 with its matching Keys overlay: decode by workload and concurrency

Measured on 2026-10-21 (UTC) on two GB10s. Every value is the median
of three scored waves. C1 is one request; C32 is aggregate output tok/s
with all 32 decoders active. Greedy uses temperature 0; sampled uses
temperature 1 with explicit seeds.

| Decode configuration | Code | Prose | Counting |
| --- | ---: | ---: | ---: |
| C1 greedy | **94.6** | **60.2** | **138.3** |
| C32 greedy | **299.8** | **271.6** | **374.1** |
| C1 sampled | **87.2** | **61.6** | **139.0** |
| C32 sampled | **261.5** | **247.0** | **361.5** |

[Every request, health sample and repetition](evidence/native-workloads-mia-keys-20261020.json).
The campaign completed 36 scored waves (594 requests) and 12 warm-up waves
(198 requests). All 18 scored C32 waves reached 32 decoders, with 28.9–44.6
seconds of eligible steady observations. Exact request and token counters
matched. Both ranks stayed running with zero restarts and the paired monitor active.

## All measured repetitions

Decode uses first-to-last-content timing at C1 and aggregate steady timing
at C32. End-to-end includes admission, prefill and completion tails.
Reply ranges preserve early stopping.

| Configuration | Task | Decode repetitions, output tok/s | Prompt tokens | Reply tokens | End-to-end median, output tok/s |
| --- | --- | --- | --- | --- | ---: |
| C1 greedy | Code | 93.92 / 94.64 / 95.01 | 43 | 384 | 91.2 |
| C1 greedy | Prose | 60.09 / 60.45 / 60.16 | 23 | 384 | 59.2 |
| C1 greedy | Counting | 138.82 / 136.64 / 138.27 | 23 | 384 | 133.3 |
| C32 greedy | Code | 299.81 / 299.13 / 302.08 | 48 | 384 | 262.5 |
| C32 greedy | Prose | 271.99 / 270.66 / 271.63 | 28 | 336–384 | 243.0 |
| C32 greedy | Counting | 375.99 / 374.05 / 372.37 | 28 | 384 | 333.8 |
| C1 sampled | Code | 87.74 / 87.19 / 86.73 | 43 | 384 | 84.3 |
| C1 sampled | Prose | 61.59 / 61.26 / 61.67 | 23 | 384 | 60.6 |
| C1 sampled | Counting | 138.99 / 138.28 / 139.21 | 23 | 384 | 133.8 |
| C32 sampled | Code | 261.50 / 261.53 / 263.74 | 48 | 384 | 231.1 |
| C32 sampled | Prose | 247.03 / 244.62 / 247.43 | 28 | 332–384 | 225.5 |
| C32 sampled | Counting | 361.48 / 361.59 / 361.23 | 28 | 384 | 323.7 |

Returned-text hashes matched across all three repetitions in 12 of
12 configurations. Fixed prompts and seeds are reused; every repetition is retained.

## Runtime

Source `7ebfbdbf3b01da8ab56a4d995324205104082efa`, image
`sha256:304b45701d11c6e852d26984990a6105c64473cef56eb148d9aa5e96dfe1eb87`. Capacity remains 32 slots, an
8,650,752-token shared pool and 1,048,576 tokens per request.

## Workloads and timing

The inputs are [Bertholomus's benchmark kit, set b](../tools/dsv41/kit_bench.py):
Python LRU-cache implementation with tests, a 400-word essay about the printing
press, and a count from 1 to 200 with one number per line. Counting is
ordinary text generation, not JSON-schema constrained output. C32 appends the
kit's numbered ` (variant N)` suffix, for N=0..31.

Thinking is disabled. Each concurrency/task/temperature shape has one unscored
warm-up (32-token cap at C1, 64 at C32), then three scored waves with a
384-token reply cap. EOS is allowed. Seeds are `42000 + request index` and
repeat across repetitions. Order is temperature, task, concurrency. This is a
warm throughput measurement; lazy graph captures remain in the timings.
No repetition is discarded or replaced.

C1 uses `(output tokens - 1) / first-to-last-content seconds`, excluding time
to first content. C32 counts output tokens in adjacent health observations
while all 32 decoders are active, with no prefill or queued work. Polls are
0.25 seconds apart; gaps over three seconds are excluded and at least two
seconds of eligible observations are required. Admission and completion tails
are excluded from that steady rate. Individual request rates are not summed.

End-to-end throughput includes all returned output tokens from the earliest
request start to the latest response end. Raw evidence retains every request's
length and timing, prompt/output hashes, health observations, graph captures,
warm-up and scored repetition. All prompts are public benchmark fixtures;
no private inference history is used.

## Reproduction

Use an otherwise idle deployment and a new receipt filename. Point `--source`
to the clean checkout that owns the running image:

```bash
mkdir -p deployment/.local/measurements
python3 -B benchmarks/native_workloads.py --source . \
  --out deployment/.local/measurements/native-workloads-new.json
```

The runner checks rank/image identity, paired monitor, graph budget, readiness,
C32 occupancy and exact request/input/output counters. It refuses existing
receipts and preserves failures. The 48-wave campaign leaves both ranks running.
This short-prompt test alone does not qualify full-context capacity, vision,
structured output, long-term stability or model quality.


## Related measurements

[Matched LibertAI/Mia comparison](MIA-1017-COMPARISON.md) and
[Mia stock/Keys comparison](KEYS-1017-COMPARISON.md) retain variant differences.
The earlier [LibertAI stock campaign](NATIVE-WORKLOADS-LIBERT-STOCK-20261019.md)
and [original 1017 migration](NATIVE-WORKLOADS-STOCK-1017-20261018.md)
remain scoped to their original images and weights.
