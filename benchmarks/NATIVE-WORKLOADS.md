# Native decode by workload and concurrency

These measurements use the stock **DeepSeek-V4.1-Flash-1017** checkpoint in
LibertAIDAI's EXL3 2.9 bpw conversion, on two GB10s with the native engine.
No Keys overlay is applied. C1 is one request; C32 is 32 concurrent requests
of the same task type. Greedy means temperature 0; sampled means temperature 1
with explicit per-request seeds.

Measured on 2026-10-18. Each value is the median of all three scored waves.
C32 rates are aggregate output tok/s across all 32 active decoders.

| Decode configuration | Code | Prose | Counting |
| --- | ---: | ---: | ---: |
| C1 greedy | **93.7** | **59.3** | **138.2** |
| C32 greedy | **301.1** | **252.8** | **371.0** |
| C1 sampled | **94.1** | **56.2** | **132.4** |
| C32 sampled | **264.2** | **239.5** | **362.4** |

[Complete evidence: every request, health sample and repetition](evidence/native-workloads-20261018-1017.json).
The campaign completed 36 scored waves (594 requests) and 12 warm-up
waves (198 requests), for 792 requests total. All 18
scored C32 waves reached 32 active decoders, with 28.0–48.5
seconds of eligible steady observations each. Request and token counters
matched exactly. Both ranks stayed running with zero restarts and the paired
monitor active.

## All measured repetitions

C1 uses first-to-last-content decode timing. C32 uses aggregate steady decode.
The final column includes admission, prefill and completion tails. Prompt and
reply ranges retain early stopping; a 384-token cap does not mean every reply
reaches that length.

| Configuration | Task | Decode repetitions, output tok/s | Prompt tokens | Reply tokens | End-to-end median, output tok/s |
| --- | --- | --- | --- | --- | ---: |
| C1 greedy | Code | 91.43 / 93.68 / 95.05 | 43 | 384 | 90.4 |
| C1 greedy | Prose | 58.51 / 59.32 / 59.62 | 23 | 384 | 58.4 |
| C1 greedy | Counting | 136.10 / 138.51 / 138.16 | 23 | 384 | 133.1 |
| C32 greedy | Code | 293.65 / 301.62 / 301.10 | 48 | 384 | 258.2 |
| C32 greedy | Prose | 252.82 / 253.13 / 251.23 | 28 | 322–384 | 228.8 |
| C32 greedy | Counting | 361.73 / 371.00 / 372.64 | 28 | 384 | 324.6 |
| C1 sampled | Code | 93.02 / 94.06 / 94.34 | 43 | 384 | 90.3 |
| C1 sampled | Prose | 56.58 / 55.98 / 56.25 | 23 | 384 | 55.4 |
| C1 sampled | Counting | 132.12 / 132.49 / 132.39 | 23 | 384 | 127.1 |
| C32 sampled | Code | 266.42 / 264.20 / 264.08 | 48 | 384 | 232.9 |
| C32 sampled | Prose | 239.60 / 238.98 / 239.47 | 28 | 383–384 | 220.2 |
| C32 sampled | Counting | 362.92 / 362.45 / 361.01 | 28 | 384 | 323.0 |

Returned-text hashes matched at every request index across all three scored
repetitions in 12 of the 12 configurations. Repetitions reuse fixed
prompt/seed fixtures. All repetitions remain in the report.

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

Runtime source `e2de6d1b2159a311c65ab8433ef0dc9957f32b6b`, image
`sha256:20c86f35699ad32b245933a455606588834baa9f224b2382b4b3d54c916f0aa2`. The profile has 32 slots, an
8,650,752-token shared KV pool and a 1,048,576-token request limit. This
benchmark uses short text requests; it does not independently qualify full
context capacity, vision, structured outputs or long-run stability.

The [runner](native_workloads.py) checks the owned rank/image identities,
readiness, graph budget, paired monitor and exact completed-request and
input/output-token counters. Every scored C32 wave must show all 32 active
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


## Earlier measurements

The [previous Keys workload report](NATIVE-WORKLOADS-KEYS-20261011.md) preserves
its original measurements and evidence. Those results use a different
checkpoint. The [earlier unchanged-kit C1 run](NATIVE-DECODE.md) and
[mixed C32 drafting investigation](NATIVE-DRAFTING.md) retain their original
protocols and runtime identities as well.
