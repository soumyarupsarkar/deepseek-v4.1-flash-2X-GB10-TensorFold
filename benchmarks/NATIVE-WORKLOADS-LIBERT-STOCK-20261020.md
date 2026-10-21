# LibertAIDAI stock 1017, matched migration baseline: decode by workload and concurrency

Measured on 2026-10-21 (UTC) on two GB10s. Every value is the median
of three scored waves. C1 is one request; C32 is aggregate output tok/s
with all 32 decoders active. Greedy uses temperature 0; sampled uses
temperature 1 with explicit seeds.

| Decode configuration | Code | Prose | Counting |
| --- | ---: | ---: | ---: |
| C1 greedy | **92.7** | **59.8** | **133.9** |
| C32 greedy | **301.7** | **253.3** | **370.9** |
| C1 sampled | **95.3** | **56.3** | **130.3** |
| C32 sampled | **264.4** | **238.6** | **360.3** |

[Every request, health sample and repetition](evidence/native-workloads-libert-stock-20261020.json).
The campaign completed 36 scored waves (594 requests) and 12 warm-up waves
(198 requests). All 18 scored C32 waves reached 32 decoders, with 27.0–49.0
seconds of eligible steady observations. Exact request and token counters
matched. Both ranks stayed running with zero restarts and the paired monitor active.

## All measured repetitions

Decode uses first-to-last-content timing at C1 and aggregate steady timing
at C32. End-to-end includes admission, prefill and completion tails.
Reply ranges preserve early stopping.

| Configuration | Task | Decode repetitions, output tok/s | Prompt tokens | Reply tokens | End-to-end median, output tok/s |
| --- | --- | --- | --- | --- | ---: |
| C1 greedy | Code | 92.29 / 92.74 / 95.62 | 43 | 384 | 89.4 |
| C1 greedy | Prose | 59.79 / 59.69 / 59.75 | 23 | 384 | 58.9 |
| C1 greedy | Counting | 133.91 / 133.11 / 134.49 | 23 | 384 | 128.5 |
| C32 greedy | Code | 293.97 / 302.10 / 301.68 | 48 | 384 | 258.8 |
| C32 greedy | Prose | 253.84 / 252.63 / 253.28 | 28 | 322–384 | 229.3 |
| C32 greedy | Counting | 370.91 / 372.76 / 369.52 | 28 | 384 | 328.4 |
| C1 sampled | Code | 95.27 / 93.95 / 95.70 | 43 | 384 | 91.8 |
| C1 sampled | Prose | 55.88 / 56.40 / 56.35 | 23 | 384 | 55.5 |
| C1 sampled | Counting | 132.09 / 130.28 / 129.90 | 23 | 384 | 124.9 |
| C32 sampled | Code | 263.30 / 264.36 / 265.07 | 48 | 384 | 233.4 |
| C32 sampled | Prose | 238.56 / 236.20 / 240.08 | 28 | 383–384 | 218.3 |
| C32 sampled | Counting | 360.40 / 359.47 / 360.30 | 28 | 384 | 321.4 |

Returned-text hashes matched across all three repetitions in 12 of
12 configurations. Fixed prompts and seeds are reused; every repetition is retained.

## Runtime

Source `9f8d14e349be3811147b1fd5b35bcbdac6f824fd`, image
`sha256:eedc8c3acc3109262c92ccb4fcd8221b115f992cc34f644acd1bc40034c1a84a`. Capacity remains 32 slots, an
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
