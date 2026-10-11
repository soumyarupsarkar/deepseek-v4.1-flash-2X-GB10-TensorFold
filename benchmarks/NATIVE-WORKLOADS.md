# Native decode by workload and concurrency

These measurements use separate code, prose and counting batches on two GB10s,
with the Keys overlay and the native engine. C1 is one request; C32 is 32
concurrent requests of the same task type. Greedy means temperature 0; sampled
means temperature 1 with explicit per-request seeds.

Measured on 2026-10-11. Each value is the median of three scored waves; C32
rates are aggregate output tok/s across all 32 active decoders.

| Decode configuration | Code | Prose | Counting |
| --- | ---: | ---: | ---: |
| C1 greedy | **100.2** | **59.3** | **140.6** |
| C32 greedy | **313.4** | **268.6** | **377.0** |
| C1 sampled | **98.6** | **62.5** | **139.3** |
| C32 sampled | **268.9** | **251.1** | **366.5** |

[Complete evidence: every request, health sample and repetition](evidence/native-workloads-20261011.json).
The run completed 36 scored waves (594 requests) and 12 warm-up waves
(198 requests), for 792 requests total. All 18 scored C32 waves reached 32
active decoders, with 25.2–44.8 seconds of eligible steady observations each.
Request and token counters matched exactly. Both ranks stayed running with
zero restarts and the paired monitor active.

## All measured repetitions

C1 numbers below use first-to-last-content decode timing; C32 numbers use
aggregate steady decode. The last column retains the complete-wave median,
including admission and prefill, in aggregate output tok/s.

| Configuration | Task | Decode repetitions, output tok/s | Reply tokens per request | End-to-end median, output tok/s |
| --- | --- | --- | --- | ---: |
| C1 greedy | Code | 100.24 / 100.32 / 99.77 | 384 | 96.5 |
| C1 greedy | Prose | 58.99 / 59.30 / 59.31 | 299 | 58.2 |
| C1 greedy | Counting | 136.50 / 140.55 / 141.36 | 384 | 135.4 |
| C32 greedy | Code | 308.66 / 314.64 / 313.41 | 384 | 272.1 |
| C32 greedy | Prose | 269.39 / 268.46 / 268.63 | 362–384 | 243.2 |
| C32 greedy | Counting | 376.97 / 377.32 / 373.15 | 384 | 334.3 |
| C1 sampled | Code | 98.61 / 97.64 / 99.15 | 384 | 94.7 |
| C1 sampled | Prose | 62.32 / 62.68 / 62.50 | 384 | 61.5 |
| C1 sampled | Counting | 139.31 / 138.93 / 139.38 | 384 | 134.2 |
| C32 sampled | Code | 267.94 / 268.85 / 268.87 | 384 | 237.3 |
| C32 sampled | Prose | 251.12 / 250.88 / 251.05 | 354–384 | 228.9 |
| C32 sampled | Counting | 366.26 / 368.20 / 366.51 | 384 | 327.1 |

Input lengths were 43 tokens for C1 code and 23 for C1 prose/counting; the C32
variant suffix made these 48 and 28 tokens. Greedy C1 prose finished at 299
tokens, while sampled prose reached the cap with a different continuation.
Within each configuration, every request index's returned-text hash matched
across all three repetitions. These repetitions reuse fixed fixtures.

## Workloads and timing

The inputs come from [Bertholomus's benchmark kit, set b](../tools/dsv41/kit_bench.py):

- Code: implement a Python LRU cache with O(1) operations and unit tests.
- Prose: write a 400-word essay about the printing press and its effect on Europe.
- Counting: count from 1 to 200, one number per line. The kit calls this task
  `structured`; it uses text output without a JSON grammar.

C1 uses the original prompt. C32 uses the same task with the kit's
` (variant N)` suffix for request indices 0 through 31. There is no random-word
padding. All requests use the chat endpoint with thinking off, the default
drafting policy, a 384-token output cap and normal stopping enabled. Actual
reply lengths are retained, including replies that finish before the cap.
These are public benchmark prompts; no inference-user prompts were used or
adapted.

Each concurrency/task/temperature combination has one unscored warm-up wave,
with a 32-token cap at C1 or 64 at C32, followed by three scored waves. Request
seeds are `42000 + index` and repeat across the three repetitions. The order is
temperature, task, then concurrency. Repetitions reuse the same prompt/seed
fixtures. This is a warm throughput measurement with no cold-prefix claim.
Lazy graph captures during scored waves remain in the timings, and their
counts are retained per wave. No repetition is discarded or replaced.

**C1 decode** uses the kit's `(output tokens - 1) / first-to-last-content time`
calculation, excluding time to first content. **C32 aggregate decode** counts
generated tokens through adjacent health samples while all 32 decoders are
active, with no prefill or queued work. Samples are taken every 0.25 seconds;
eligible observations must span at least two seconds, and gaps over three
seconds are excluded. Request arrival and completion tails are excluded from
that steady rate. Summing individual request rates is not used.

End-to-end aggregate throughput divides all returned output tokens by the time
from the earliest request start to the latest response end. It includes
admission, prefill and completion tails. The complete receipt keeps both timing
methods, individual request timings and lengths, and all health samples.

## Runtime and verification

The running native source is
`6aaec5b3616f4547fabbe2fcc3fb1e779bb75f82`, image
`sha256:baa3fc8d748766476d694da36f3e79ac501f18bed6b9572e36c1c80c4baa7bc7`.
Keys, vision and structured-output support are enabled. The profile has 32
slots, an 8,650,752-token shared KV pool and a 1,048,576-token request limit.
This benchmark uses short text requests.

The [runner](native_workloads.py) reuses the kit's prompt corpus, chat-request
builder and streaming timing implementation. It checks the owned rank/image
identities, readiness, graph budget, paired monitor and exact completed-request
and input/output-token counters. It also checks the entire campaign's counters
to detect traffic between waves. Every scored C32 wave must show all 32 active
decoders and sufficient eligible steady time. No host or server configuration
is changed.

## Reproduction

Use an otherwise idle deployment and a new receipt filename. Run the helper
from this checkout, pointing `--source` at the clean, pinned checkout that owns
the running deployment; use `.` if it is the same checkout.

```bash
mkdir -p deployment/.local/measurements
python3 -B benchmarks/native_workloads.py --source . \
  --out deployment/.local/measurements/native-workloads-new.json
```

The complete campaign consists of 48 waves: 12 unscored warm-ups and 36 scored
waves, covering both concurrency levels, all three task types and both
temperatures. The runner refuses existing receipt paths, preserves failed or
interrupted attempts, and rejects counter contamination. It leaves the ranks
running.

## Related measurements

The [initial unchanged-kit C1 run](NATIVE-DECODE.md) retains its earlier
repetitions and reproduction command. The [mixed C32 drafting investigation](NATIVE-DRAFTING.md)
retains the earlier 11-code/11-prose/10-counting workload with padded inputs,
its steady and end-to-end rates, and ordinary-decoding controls. Those workloads
and timing results remain separately identified.
